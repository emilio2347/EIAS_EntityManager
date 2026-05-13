/* ========================================
   EIAS Entity Manager — App Router & Shared Utilities
   ======================================== */

// All known NER entity types
const ENTITY_TYPES = [
    'PERSON', 'ORG', 'GPE', 'LOC', 'WORK_OF_ART', 'EVENT',
    'DATE', 'NORP', 'FAC', 'PRODUCT', 'LAW', 'LANGUAGE',
    'MONEY', 'QUANTITY', 'ORDINAL', 'CARDINAL', 'PERCENT', 'TIME', 'MISC',
];

let _activeProfile = null;

function applyUiTheme(theme) {
    const liquidGlassEnabled = theme === 'liquid-glass';
    document.body.classList.toggle('theme-liquid-glass', liquidGlassEnabled);
    document.documentElement.classList.toggle('theme-boot-liquid-glass', liquidGlassEnabled);

    const select = document.getElementById('settings-ui-theme-select');
    if (select) {
        select.value = liquidGlassEnabled ? 'liquid-glass' : 'classic';
    }
}

function initializeUiTheme() {
    const storedTheme = localStorage.getItem('eias.uiTheme') || 'liquid-glass';
    applyUiTheme(storedTheme);

    document.getElementById('settings-ui-theme-select')?.addEventListener('change', (event) => {
        const nextTheme = event.target.value === 'classic' ? 'classic' : 'liquid-glass';
        localStorage.setItem('eias.uiTheme', nextTheme);
        applyUiTheme(nextTheme);
    });
}

// Navigation
document.querySelectorAll('.nav-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        // Update nav active state
        document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');

        // Show the correct view
        const viewName = btn.dataset.view;
        document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
        const target = document.getElementById(`view-${viewName}`);
        if (target) {
            target.classList.remove('hidden');
            target.classList.add('active');
        }

        // Trigger refresh on view activation
        if (viewName === 'documents') {
            loadDocuments();
            updateActiveProfileLabels();
        }
        if (viewName === 'document-view') {
            loadDocumentViewOptions();
        }
        if (viewName === 'entities') {
            loadDocumentFilterOptions();
            loadEntities();
        }
        if (viewName === 'ontology') loadOntologyData();
        if (viewName === 'settings') loadSettingsView();
        if (viewName === 'export') updateExportProfileSummary();
    });
});


// --- Shared Utilities ---

async function api(path, options = {}) {
    const resp = await fetch(`/api${path}`, {
        headers: { 'Content-Type': 'application/json', ...options.headers },
        ...options,
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || 'API error');
    }
    return resp.json();
}

async function apiUpload(path, formData) {
    const resp = await fetch(`/api${path}`, {
        method: 'POST',
        body: formData,
    });
    if (!resp.ok) {
        const err = await resp.json().catch(() => ({ detail: resp.statusText }));
        throw new Error(err.detail || 'Upload failed');
    }
    return resp.json();
}

/**
 * Render an entity type tag.
 *
 * @param {string} type       - The NER label (e.g. "PERSON")
 * @param {string} [entityId] - If provided, tag becomes clickable to change the type
 */
function entityTypeTag(type, entityId) {
    const colorTypes = ['PERSON', 'ORG', 'GPE', 'LOC', 'WORK_OF_ART', 'EVENT'];
    const cls = colorTypes.includes(type) ? `tag-${type}` : 'tag-default';

    if (entityId) {
        return `<span class="tag tag-editable ${cls}" title="Click to change type" onclick="event.stopPropagation(); openTypeEditor('${entityId}', '${type}', this)">${type}</span>`;
    }
    return `<span class="tag ${cls}">${type}</span>`;
}


/**
 * Open an inline dropdown to change an entity's type.
 * Replaces the tag element with a <select> that auto-saves on change.
 */
function openTypeEditor(entityId, currentType, tagElement) {
    // Don't open if already editing
    if (tagElement.dataset.editing === 'true') return;

    const options = ENTITY_TYPES.map(t =>
        `<option value="${t}" ${t === currentType ? 'selected' : ''}>${t}</option>`
    ).join('');

    const select = document.createElement('select');
    select.className = 'type-editor-select';
    select.innerHTML = options;

    // Replace the tag with the select
    tagElement.replaceWith(select);
    select.focus();

    async function commitChange() {
        const newType = select.value;
        if (newType === currentType) {
            // Revert to tag — re-render
            const newTag = document.createElement('span');
            newTag.innerHTML = entityTypeTag(newType, entityId);
            select.replaceWith(newTag.firstElementChild);
            return;
        }

        try {
            await api(`/entities/${entityId}/type`, {
                method: 'PATCH',
                body: JSON.stringify({ entity_type: newType }),
            });

            // Refresh everything that might show this entity
            loadEntities();
            showEntityDetail(entityId);
        } catch (err) {
            alert('Error changing type: ' + err.message);
            // Revert
            const newTag = document.createElement('span');
            newTag.innerHTML = entityTypeTag(currentType, entityId);
            select.replaceWith(newTag.firstElementChild);
        }
    }

    select.addEventListener('change', commitChange);
    select.addEventListener('blur', commitChange);
}


function groundingDot(entity) {
    const grounded = entity.wikidata_uri || entity.dbpedia_uri || entity.worldcat_uri;
    return `<span class="grounding-dot ${grounded ? 'grounded' : 'ungrounded'}" title="${grounded ? 'Grounded' : 'Ungrounded'}"></span>`;
}

function getActiveProfileId() {
    const select = document.getElementById('settings-active-profile-select');
    return select?.value || _activeProfile?.id || localStorage.getItem('eias.activeProfileId') || '';
}

function getActiveProfileName() {
    const select = document.getElementById('settings-active-profile-select');
    if (select && select.selectedOptions.length) {
        return select.selectedOptions[0].textContent.replace(' (default)', '');
    }
    return _activeProfile?.name || 'No profile';
}

function updateActiveProfileLabels() {
    const label = getActiveProfileName();
    const uploadLabel = document.getElementById('upload-profile-label');
    if (uploadLabel) uploadLabel.textContent = `Profile: ${label}`;

    const summary = document.getElementById('active-profile-summary');
    if (summary) summary.textContent = label ? `Current track: ${label}` : '';

    updateExportProfileSummary();
}

function updateExportProfileSummary() {
    const el = document.getElementById('export-profile-summary');
    if (el) el.textContent = `Download entities from the active profile: ${getActiveProfileName()}.`;
}

function showStatus(elementId, message, type = '') {
    const el = document.getElementById(elementId);
    if (el) {
        el.textContent = message;
        el.className = `status-msg ${type}`;
    }
}

function openModal(html) {
    document.getElementById('modal-content').innerHTML = html;
    document.getElementById('modal-overlay').classList.remove('hidden');
}

function closeModal() {
    document.getElementById('modal-overlay').classList.add('hidden');
    document.getElementById('modal-content').innerHTML = '';
}

// Close modal on overlay click
document.getElementById('modal-overlay')?.addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
});

// Initialize on load
document.addEventListener('DOMContentLoaded', () => {
    initializeUiTheme();
    loadSettingsView();
});
