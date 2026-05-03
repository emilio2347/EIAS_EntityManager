/* ========================================
   Documents — Upload, list, detail
   ======================================== */

// Upload form
document.getElementById('upload-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fileInput = document.getElementById('file-input');
    const btn = document.getElementById('upload-btn');

    if (!fileInput.files.length) return;

    btn.disabled = true;
    btn.textContent = 'Processing...';
    showStatus('upload-status', 'Uploading and processing document...', '');

    try {
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        const profileSelect = document.getElementById('upload-profile-select');
        const profileId = profileSelect?.value || '';
        if (profileId) formData.append('profile_id', profileId);

        const result = await apiUpload('/documents/upload', formData);

        showStatus('upload-status',
            `Done! Found ${result.entities_found} entities, ${result.coref_chains} coreference chains.`,
            'success'
        );
        fileInput.value = '';
        loadDocuments();
    } catch (err) {
        showStatus('upload-status', `Error: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        btn.textContent = 'Upload & Process';
    }
});


async function loadDocuments() {
    const container = document.getElementById('document-list');
    if (!container) return;

    try {
        const docs = await api('/documents');
        if (docs.length === 0) {
            container.innerHTML = '<p style="color: var(--text-muted);">No documents uploaded yet.</p>';
            return;
        }

        container.innerHTML = docs.map(doc => `
            <div class="list-item" onclick="showDocument('${doc.id}')">
                <div class="list-item-main">
                    <span class="list-item-title">${escapeHtml(doc.filename)}</span>
                    <span class="list-item-subtitle">
                        ${doc.filetype.toUpperCase()} · ${doc.text_length.toLocaleString()} chars · ${doc.mention_count} mentions
                        · ${doc.uploaded_at ? new Date(doc.uploaded_at).toLocaleDateString() : ''}
                    </span>
                </div>
                <div class="list-item-actions">
                    <button class="btn btn-danger btn-sm" onclick="event.stopPropagation(); deleteDocument('${doc.id}')">Delete</button>
                </div>
            </div>
        `).join('');
    } catch (err) {
        container.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


async function showDocument(docId) {
    const detailEl = document.getElementById('document-detail');
    const contentEl = document.getElementById('doc-detail-content');
    detailEl.classList.remove('hidden');

    contentEl.innerHTML = '<div class="spinner"></div> Loading...';

    try {
        const doc = await api(`/documents/${docId}`);

        // Group mentions by entity
        const byEntity = {};
        for (const m of doc.mentions) {
            if (!byEntity[m.entity_id]) byEntity[m.entity_id] = [];
            byEntity[m.entity_id].push(m);
        }

        const textPreview = doc.content_text.length > 500
            ? doc.content_text.substring(0, 500) + '...'
            : doc.content_text;

        contentEl.innerHTML = `
            <div class="detail-section">
                <h3>Info</h3>
                <div class="detail-row"><span class="detail-label">Filename</span><span class="detail-value">${escapeHtml(doc.filename)}</span></div>
                <div class="detail-row"><span class="detail-label">Type</span><span class="detail-value">${doc.filetype}</span></div>
                <div class="detail-row"><span class="detail-label">Uploaded</span><span class="detail-value">${doc.uploaded_at || ''}</span></div>
            </div>
            <div class="detail-section">
                <h3>Text Preview</h3>
                <p style="font-size: 0.85rem; white-space: pre-wrap; color: var(--text-muted);">${escapeHtml(textPreview)}</p>
            </div>
            <div class="detail-section">
                <h3>Entity Mentions (${doc.mentions.length})</h3>
                <table>
                    <thead><tr><th>Surface Form</th><th>Entity ID</th><th>Position</th><th>Sentence</th></tr></thead>
                    <tbody>
                        ${doc.mentions.slice(0, 50).map(m => `
                            <tr>
                                <td>${escapeHtml(m.surface_form)}</td>
                                <td><a href="#" onclick="event.preventDefault(); switchToEntity('${m.entity_id}')">${m.entity_id.substring(0, 8)}...</a></td>
                                <td>${m.start_char}–${m.end_char}</td>
                                <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(m.sentence || '')}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
                ${doc.mentions.length > 50 ? `<p style="color: var(--text-muted); margin-top: 0.5rem;">Showing 50 of ${doc.mentions.length} mentions.</p>` : ''}
            </div>
        `;
    } catch (err) {
        contentEl.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


async function deleteDocument(docId) {
    if (!confirm('Delete this document and its mentions?')) return;
    try {
        await api(`/documents/${docId}`, { method: 'DELETE' });
        loadDocuments();
        document.getElementById('document-detail')?.classList.add('hidden');
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


function switchToEntity(entityId) {
    // Switch to entities view and show detail
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('[data-view="entities"]').classList.add('active');
    document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
    document.getElementById('view-entities').classList.remove('hidden');
    loadEntities();
    showEntityDetail(entityId);
}


function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}


/**
 * Populate the per-document filter dropdown in the entities view.
 * Preserves the current selection if the document still exists.
 */
async function loadDocumentFilterOptions() {
    const select = document.getElementById('entity-document-filter');
    if (!select) return;
    try {
        const docs = await api('/documents');
        const previous = select.value;
        select.innerHTML = '<option value="">All documents</option>' +
            docs.map(d => `<option value="${d.id}">${escapeHtml(d.filename)}</option>`).join('');
        if (previous && docs.some(d => d.id === previous)) {
            select.value = previous;
        }
    } catch {
        // Silent — search still works without filter
    }
}
