/* ========================================
   Ontology — Upload, view classes, manage mappings
   ======================================== */

// Upload ontology
document.getElementById('ontology-upload-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fileInput = document.getElementById('ontology-file-input');
    if (!fileInput.files.length) return;

    showStatus('ontology-status', 'Uploading ontology...', '');

    try {
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        const result = await apiUpload('/ontology/upload', formData);
        showStatus('ontology-status', `Loaded ${result.class_count} classes from ${result.filename}`, 'success');
        fileInput.value = '';
        loadOntologyData();
    } catch (err) {
        showStatus('ontology-status', `Error: ${err.message}`, 'error');
    }
});


async function loadOntologyData() {
    await Promise.all([loadOntologyClasses(), loadMappings()]);
}


async function loadOntologyClasses() {
    const container = document.getElementById('ontology-classes');
    if (!container) return;

    try {
        const data = await api('/ontology/classes');
        const classes = data.classes || [];

        if (classes.length === 0) {
            container.innerHTML = '<p style="color: var(--text-muted);">No ontology loaded. Upload a .ttl file above.</p>';
            // Clear the ontology class dropdown
            const sel = document.getElementById('mapping-ontology-class');
            if (sel) sel.innerHTML = '<option value="">-- upload ontology first --</option>';
            return;
        }

        container.innerHTML = classes.map(cls => `
            <div class="class-item">
                <strong>${escapeHtml(cls.label)}</strong>
                ${cls.comment ? ` — <em>${escapeHtml(cls.comment)}</em>` : ''}
                <br><span class="class-uri">${escapeHtml(cls.uri)}</span>
                ${cls.superclass_uri ? `<br><span style="color: var(--text-muted); font-size: 0.75rem;">↳ subclass of ${escapeHtml(cls.superclass_uri)}</span>` : ''}
            </div>
        `).join('');

        // Populate the ontology class dropdown for mappings
        const sel = document.getElementById('mapping-ontology-class');
        if (sel) {
            sel.innerHTML = classes.map(cls =>
                `<option value="${escapeHtml(cls.uri)}" data-label="${escapeHtml(cls.label)}">${escapeHtml(cls.label)} (${escapeHtml(cls.uri.split('/').pop().split('#').pop())})</option>`
            ).join('');
        }
    } catch (err) {
        container.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


async function loadMappings() {
    const container = document.getElementById('mapping-editor');
    if (!container) return;

    try {
        const mappings = await api('/ontology/mappings');

        if (mappings.length === 0) {
            container.innerHTML = '<p style="color: var(--text-muted);">No mappings configured. Add one below.</p>';
            return;
        }

        container.innerHTML = `
            <table>
                <thead><tr><th>spaCy Label</th><th>Ontology Class</th><th></th></tr></thead>
                <tbody>
                    ${mappings.map(m => `
                        <tr>
                            <td>${entityTypeTag(m.spacy_label)}</td>
                            <td>${escapeHtml(m.ontology_class_label || '')} <span class="class-uri">${escapeHtml(m.ontology_class_uri)}</span></td>
                            <td><button class="btn btn-danger btn-sm" onclick="deleteMapping('${m.id}')">Remove</button></td>
                        </tr>
                    `).join('')}
                </tbody>
            </table>
        `;
    } catch (err) {
        container.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


// Add mapping
document.getElementById('mapping-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();

    const spacyLabel = document.getElementById('mapping-spacy-label').value;
    const classSelect = document.getElementById('mapping-ontology-class');
    const classUri = classSelect.value;
    const classLabel = classSelect.selectedOptions[0]?.dataset.label || '';

    if (!classUri) {
        alert('Please upload an ontology first and select a class.');
        return;
    }

    try {
        await api('/ontology/mappings', {
            method: 'POST',
            body: JSON.stringify({
                spacy_label: spacyLabel,
                ontology_class_uri: classUri,
                ontology_class_label: classLabel,
            }),
        });
        loadMappings();
    } catch (err) {
        alert('Error: ' + err.message);
    }
});


async function deleteMapping(mappingId) {
    try {
        await api(`/ontology/mappings/${mappingId}`, { method: 'DELETE' });
        loadMappings();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}
