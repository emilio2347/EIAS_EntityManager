/* ========================================
   EIAS — App Router & Shared Utilities
   ======================================== */

let ENTITY_TYPES = [
    'PERSON', 'ORG', 'GPE', 'LOC', 'WORK_OF_ART', 'EVENT',
    'DATE', 'NORP', 'FAC', 'PRODUCT', 'LAW', 'LANGUAGE',
    'MONEY', 'QUANTITY', 'ORDINAL', 'CARDINAL', 'PERCENT', 'TIME', 'MISC', 'CONCEPT',
];

const APP_DEFAULT_VIEWS = {
    'document-manager': 'dm-ingest',
    'entity-manager': 'entities',
    'topic-manager': 'tm-article-topics',
    'database': 'database-tables',
    'export': 'export',
    'settings': 'settings-entity-manager',
};

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

async function loadKnownNerTypes() {
    setEntityTypes(ENTITY_TYPES);
    return ENTITY_TYPES;
}

function setEntityTypes(types) {
    const seen = new Set();
    ENTITY_TYPES = (types || [])
        .map(t => String(t || '').trim().toUpperCase())
        .filter(t => t && !seen.has(t) && seen.add(t));
    populateEntityTypeSelects();
}

function entityTypeOptionsHtml(selectedValue = '', includeAllOption = false) {
    const selected = String(selectedValue || '').toUpperCase();
    const options = includeAllOption ? '<option value="">All types</option>' : '';
    return options + ENTITY_TYPES.map(t =>
        `<option value="${t}" ${t === selected ? 'selected' : ''}>${t}</option>`
    ).join('');
}

function populateEntityTypeSelects() {
    const entityFilter = document.getElementById('entity-type-filter');
    if (entityFilter) {
        const current = entityFilter.value;
        entityFilter.innerHTML = entityTypeOptionsHtml(current, true);
    }

    const mappingSelect = document.getElementById('mapping-spacy-label');
    if (mappingSelect) {
        const current = mappingSelect.value;
        mappingSelect.innerHTML = entityTypeOptionsHtml(current, false);
    }
}

function currentAppForView(viewName) {
    const target = document.getElementById(`view-${viewName}`);
    return target?.dataset.app || 'document-manager';
}

function switchApp(appName, preferredView = '') {
    const viewName = preferredView || APP_DEFAULT_VIEWS[appName] || 'dm-ingest';

    document.querySelectorAll('.app-nav-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.app === appName);
    });

    document.querySelectorAll('.subnav-btn').forEach(btn => {
        const matchesApp = btn.dataset.app === appName;
        btn.classList.toggle('hidden', !matchesApp);
        btn.classList.toggle('active', matchesApp && btn.dataset.view === viewName);
    });

    switchView(viewName, { updateApp: false });
}

function switchView(viewName, options = {}) {
    const target = document.getElementById(`view-${viewName}`);
    if (!target) return;
    const appName = currentAppForView(viewName);
    if (options.updateApp !== false) {
        switchApp(appName, viewName);
        return;
    }

    document.querySelectorAll('.view').forEach(v => {
        v.classList.add('hidden');
        v.classList.remove('active');
    });
    target.classList.remove('hidden');
    target.classList.add('active');

    document.querySelectorAll('.subnav-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.app === appName && btn.dataset.view === viewName);
    });

    refreshView(viewName);
}

function refreshView(viewName) {
    if (viewName === 'dm-articles') loadDocumentManagerArticles?.();
    if (viewName === 'dm-renderer') loadDocumentManagerArticleOptions?.('dm-renderer-select');
    if (viewName === 'dm-metadata') loadEntityMetadataOptions?.();
    if (viewName === 'dm-pdf-annotations') loadPdfAnnotationArticleOptions?.();
    if (viewName === 'dm-annotations') loadDocumentManagerArticleOptions?.('dm-annotations-article-select');
    if (viewName === 'dm-pipeline') loadDocumentManagerPipeline?.();
    if (viewName === 'document-view') loadDocumentViewOptions?.();
    if (viewName === 'grounding-enrichment') loadEntities?.();
    if (viewName === 'entities') {
        loadDocumentFilterOptions?.();
        loadEntities?.();
    }
    if (viewName === 'ontology') loadOntologyData?.();
    if (viewName === 'settings-entity-manager') loadSettingsView?.();
    if (viewName === 'settings-document-manager') loadDocumentManagerSettings?.();
    if (viewName === 'settings-topic-manager') loadTopicManagerSettings?.();
    if (viewName === 'database-tables') loadDatabaseTables?.();
    if (viewName === 'export') {
        updateExportSummary?.();
        renderExportEntityTypes?.();
    }
    if (viewName === 'tm-article-topics') loadTopicArticleOptions?.();
    if (viewName === 'tm-keyterm-renderer') loadTopicRendererOptions?.();
    if (viewName === 'tm-fast-review') loadTopicReviewOptions?.();
    if (viewName === 'tm-schemas') loadTopicSchemas?.();
}

function initializeNavigation() {
    document.querySelectorAll('.app-nav-btn').forEach(btn => {
        btn.addEventListener('click', () => switchApp(btn.dataset.app));
    });
    document.querySelectorAll('.subnav-btn').forEach(btn => {
        btn.addEventListener('click', () => switchView(btn.dataset.view));
    });
}

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

function entityTypeTag(type, entityId) {
    const colorTypes = ['PERSON', 'ORG', 'GPE', 'LOC', 'WORK_OF_ART', 'EVENT', 'CONCEPT'];
    const cls = colorTypes.includes(type) ? `tag-${type}` : 'tag-default';

    if (entityId) {
        return `<span class="tag tag-editable ${cls}" title="Click to change type" onclick="event.stopPropagation(); openTypeEditor('${entityId}', '${type}', this)">${type}</span>`;
    }
    return `<span class="tag ${cls}">${type}</span>`;
}

function openTypeEditor(entityId, currentType, tagElement) {
    if (tagElement.dataset.editing === 'true') return;

    const select = document.createElement('select');
    select.className = 'type-editor-select';
    select.innerHTML = entityTypeOptionsHtml(currentType, false);

    tagElement.replaceWith(select);
    select.focus();

    async function commitChange() {
        const newType = select.value;
        if (newType === currentType) {
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
            loadEntities?.();
            showEntityDetail?.(entityId);
        } catch (err) {
            alert('Error changing type: ' + err.message);
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

function updateSharedScopeLabels() {
    updateExportSummary();
}

function updateExportSummary() {
    const el = document.getElementById('export-summary');
    if (el) el.textContent = 'Download all entities from the shared corpus database.';
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

document.getElementById('modal-overlay')?.addEventListener('click', (e) => {
    if (e.target === e.currentTarget) closeModal();
});

document.addEventListener('DOMContentLoaded', () => {
    initializeUiTheme();
    initializeNavigation();
    loadKnownNerTypes();
    switchApp('document-manager', 'dm-ingest');
});
