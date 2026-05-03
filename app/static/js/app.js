/* ========================================
   EIAS Entity Manager — App Router & Shared Utilities
   ======================================== */

// All known NER entity types
const ENTITY_TYPES = [
    'PERSON', 'ORG', 'GPE', 'LOC', 'WORK_OF_ART', 'EVENT',
    'DATE', 'NORP', 'FAC', 'PRODUCT', 'LAW', 'LANGUAGE',
    'MONEY', 'QUANTITY', 'ORDINAL', 'CARDINAL', 'PERCENT', 'TIME',
];

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
            loadProfilesIntoUploadSelect();
        }
        if (viewName === 'entities') {
            loadDocumentFilterOptions();
            loadEntities();
        }
        if (viewName === 'ontology') loadOntologyData();
        if (viewName === 'profiles') loadProfilesView();
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
    loadDocuments();
    loadProfilesIntoUploadSelect();
});
