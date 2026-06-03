/* ========================================
   Export — Download entity database
   ======================================== */

function downloadExport(fmt) {
    window.location = `/api/export/${fmt}`;
}

function renderExportEntityTypes() {
    const container = document.getElementById('export-entity-types');
    if (!container) return;
    container.innerHTML = (ENTITY_TYPES || []).map(type => `
        <label class="type-checkbox compact">
            <input type="checkbox" value="${escapeAttr(type)}" checked>
            <span>${escapeHtml(type)}</span>
        </label>
    `).join('');
}

function selectedExportEntityTypes() {
    return Array.from(document.querySelectorAll('#export-entity-types input[type="checkbox"]:checked'))
        .map(input => input.value)
        .filter(Boolean);
}

function downloadEntityQuickExport(fmt) {
    const params = new URLSearchParams();
    for (const type of selectedExportEntityTypes()) {
        params.append('entity_types', type);
    }
    const include = document.getElementById('export-include-enrichments')?.checked !== false;
    params.set('include_enrichments', include ? 'true' : 'false');
    window.location = `/api/export/${fmt}?${params.toString()}`;
}
