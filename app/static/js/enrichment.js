/* ========================================
   Enrichment — Browse and import external properties
   ======================================== */

async function openEnrichmentModal(entityId) {
    openModal('<div class="spinner"></div> Fetching available properties...');

    try {
        const data = await api(`/enrichment/${entityId}/available`);
        const props = data.available_properties || [];

        let html = `
            <h2 style="margin-bottom: 1rem;">Enrich: ${escapeHtml(data.entity_name)}</h2>
        `;

        if (props.length === 0) {
            html += '<p style="color: var(--text-muted);">No additional properties found.</p>';
            html += '<button class="btn" onclick="closeModal()">Close</button>';
            document.getElementById('modal-content').innerHTML = html;
            return;
        }

        html += `
            <p style="color: var(--text-muted); margin-bottom: 1rem;">
                Select properties to import into the local database (${props.length} available).
            </p>
            <div style="margin-bottom: 1rem;">
                <button class="btn btn-sm" onclick="toggleAllEnrichment(true)">Select All</button>
                <button class="btn btn-sm" onclick="toggleAllEnrichment(false)">Deselect All</button>
            </div>
            <div id="enrichment-props" style="max-height: 400px; overflow-y: auto;">
        `;

        for (let i = 0; i < props.length; i++) {
            const p = props[i];
            html += `
                <div class="property-item">
                    <input type="checkbox" id="eprop-${i}" data-index="${i}">
                    <label for="eprop-${i}">
                        <span class="prop-name">${escapeHtml(p.property_name)}</span>
                        <br><span class="prop-value">${escapeHtml(truncate(p.value, 120))}</span>
                        <br><span class="prop-source">${p.source}</span>
                    </label>
                </div>
            `;
        }

        html += `
            </div>
            <div style="margin-top: 1.5rem; display: flex; gap: 0.75rem;">
                <button class="btn btn-primary" onclick="importEnrichment('${entityId}')">Import Selected</button>
                <button class="btn" onclick="closeModal()">Cancel</button>
            </div>
        `;

        // Store props for import
        window._enrichmentProps = props;
        document.getElementById('modal-content').innerHTML = html;
    } catch (err) {
        document.getElementById('modal-content').innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


function toggleAllEnrichment(checked) {
    document.querySelectorAll('#enrichment-props input[type="checkbox"]').forEach(cb => {
        cb.checked = checked;
    });
}


async function importEnrichment(entityId) {
    const checkboxes = document.querySelectorAll('#enrichment-props input[type="checkbox"]:checked');
    const selected = [];

    checkboxes.forEach(cb => {
        const idx = parseInt(cb.dataset.index);
        if (window._enrichmentProps && window._enrichmentProps[idx]) {
            selected.push(window._enrichmentProps[idx]);
        }
    });

    if (selected.length === 0) {
        alert('Please select at least one property.');
        return;
    }

    try {
        const result = await api(`/enrichment/${entityId}/import`, {
            method: 'POST',
            body: JSON.stringify({ properties: selected }),
        });
        closeModal();
        showEntityDetail(entityId);
        alert(`Imported ${result.imported_count} properties.`);
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


function truncate(str, maxLen) {
    if (!str) return '';
    return str.length > maxLen ? str.substring(0, maxLen) + '...' : str;
}
