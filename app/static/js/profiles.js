/* ========================================
   Extraction Profiles — manage NER type filters used at upload time
   ======================================== */

let _knownNerTypes = [];
let _editingProfileId = null;
let _profilesCache = [];
let _standardTripleGroups = [];

const NER_TYPE_DESCRIPTIONS = {
    PERSON: 'People, named individuals, fictional or historical persons.',
    ORG: 'Companies, institutions, agencies, collectives, and formal groups.',
    GPE: 'Countries, cities, states, and other geopolitical units.',
    LOC: 'Non-political locations such as regions, landmarks, and bodies of water.',
    WORK_OF_ART: 'Titles of books, artworks, films, songs, and other creative works.',
    EVENT: 'Named historical, cultural, sports, and organized events.',
    DATE: 'Absolute or relative dates and named periods.',
    NORP: 'Nationalities, religious groups, political groups, and ethnic groups.',
    FAC: 'Buildings, airports, bridges, highways, and other facilities.',
    PRODUCT: 'Named products, tools, platforms, vehicles, and artifacts.',
    LAW: 'Named laws, legal documents, treaties, and regulations.',
    LANGUAGE: 'Named languages.',
    MONEY: 'Monetary values.',
    QUANTITY: 'Measurements such as weight, distance, or amount.',
    ORDINAL: 'Ordinal values such as first, second, or third.',
    CARDINAL: 'Numerals that are not another more specific type.',
    PERCENT: 'Percentage expressions.',
    TIME: 'Times smaller than a day.',
    MISC: 'Manually added entities that need a more specific type later.',
    CONCEPT: 'Abstract concepts, theories, ideas, categories, and recurring topics.',
};


async function loadKnownNerTypes() {
    if (_knownNerTypes.length) return _knownNerTypes;
    try {
        const data = await api('/profiles/types');
        _knownNerTypes = data.types || [];
        setEntityTypes(_knownNerTypes);
    } catch {
        _knownNerTypes = [...ENTITY_TYPES];
        setEntityTypes(_knownNerTypes);
    }
    return _knownNerTypes;
}


async function loadSettingsView() {
    await loadKnownNerTypes();
    await loadActiveProfileSelect();
    renderTypeCheckboxes(new Set());
    resetProfileForm();
    await renderProfileList();
    await loadStandardTriplesSettings();
    await loadPipelineSettings();
}

async function loadProfilesView() {
    await loadSettingsView();
}


async function loadActiveProfileSelect() {
    const select = document.getElementById('settings-active-profile-select');
    if (!select) return;

    const profiles = await api('/profiles');
    _profilesCache = profiles;
    const stored = localStorage.getItem('eias.activeProfileId');
    const fallback = profiles.find(p => p.is_default) || profiles[0];
    const selectedId = profiles.some(p => p.id === stored) ? stored : fallback?.id || '';

    select.innerHTML = profiles.map(p =>
        `<option value="${p.id}">${escapeHtml(p.name)}${p.is_default ? ' (default)' : ''}</option>`
    ).join('');
    select.value = selectedId;
    _activeProfile = profiles.find(p => p.id === selectedId) || null;
    if (selectedId) localStorage.setItem('eias.activeProfileId', selectedId);
    updateActiveProfileLabels();
}


document.getElementById('settings-active-profile-select')?.addEventListener('change', (e) => {
    const profileId = e.target.value;
    localStorage.setItem('eias.activeProfileId', profileId);
    _activeProfile = _profilesCache.find(p => p.id === profileId) || null;
    updateActiveProfileLabels();
    loadDocumentFilterOptions();
});


async function renderProfileList() {
    const container = document.getElementById('profile-list');
    if (!container) return;

    try {
        const profiles = await api('/profiles');
        _profilesCache = profiles;
        if (!profiles.length) {
            container.innerHTML = '<p style="color: var(--text-muted);">No profiles yet.</p>';
            return;
        }
        container.innerHTML = profiles.map(p => `
            <div class="list-item">
                <div class="list-item-main">
                    <span class="list-item-title">
                        ${escapeHtml(p.name)}
                        ${p.is_default ? '<span class="tag tag-default" style="margin-left: 0.5rem;">DEFAULT</span>' : ''}
                    </span>
                    <span class="list-item-subtitle profile-tag-list">
                        ${p.allowed_types.map(t => entityTypeTag(t)).join(' ')}
                    </span>
                </div>
                <div class="list-item-actions">
                    <button class="btn btn-sm" onclick="editProfile('${p.id}')">Edit</button>
                    <button class="btn btn-danger btn-sm" onclick="deleteProfile('${p.id}')">Delete</button>
                </div>
            </div>
        `).join('');
    } catch (err) {
        container.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


function renderTypeCheckboxes(selectedSet) {
    const grid = document.getElementById('profile-types-grid');
    if (!grid) return;
    grid.innerHTML = _knownNerTypes.map(t => `
        <label class="type-checkbox profile-type-checkbox">
            <input type="checkbox" value="${t}" ${selectedSet.has(t) ? 'checked' : ''}>
            <span class="profile-type-copy">
                ${entityTypeTag(t)}
                <span class="profile-type-description">${escapeHtml(NER_TYPE_DESCRIPTIONS[t] || 'Named entity recognized by the NER pipeline.')}</span>
            </span>
        </label>
    `).join('');
}


function readSelectedTypes() {
    const boxes = document.querySelectorAll('#profile-types-grid input[type="checkbox"]:checked');
    return Array.from(boxes).map(b => b.value);
}


async function editProfile(profileId) {
    const profiles = await api('/profiles');
    const p = profiles.find(x => x.id === profileId);
    if (!p) return;

    _editingProfileId = p.id;
    document.getElementById('profile-form-title').textContent = `Edit: ${p.name}`;
    document.getElementById('profile-id').value = p.id;
    document.getElementById('profile-name').value = p.name;
    document.getElementById('profile-is-default').checked = !!p.is_default;
    renderTypeCheckboxes(new Set(p.allowed_types));
    document.getElementById('profile-save-btn').textContent = 'Update Profile';
    document.getElementById('view-settings')?.scrollIntoView({ behavior: 'smooth' });
}


function resetProfileForm() {
    _editingProfileId = null;
    document.getElementById('profile-form-title').textContent = 'New Profile';
    document.getElementById('profile-id').value = '';
    document.getElementById('profile-name').value = '';
    document.getElementById('profile-is-default').checked = false;
    renderTypeCheckboxes(new Set());
    const saveBtn = document.getElementById('profile-save-btn');
    if (saveBtn) saveBtn.textContent = 'Save Profile';
    showStatus('profile-status', '', '');
}


document.getElementById('profile-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('profile-name').value.trim();
    const isDefault = document.getElementById('profile-is-default').checked;
    const allowedTypes = readSelectedTypes();

    if (!allowedTypes.length) {
        showStatus('profile-status', 'Select at least one entity type.', 'error');
        return;
    }

    try {
        if (_editingProfileId) {
            await api(`/profiles/${_editingProfileId}`, {
                method: 'PATCH',
                body: JSON.stringify({ name, allowed_types: allowedTypes, is_default: isDefault }),
            });
            showStatus('profile-status', 'Profile updated.', 'success');
        } else {
            await api('/profiles', {
                method: 'POST',
                body: JSON.stringify({ name, allowed_types: allowedTypes, is_default: isDefault }),
            });
            showStatus('profile-status', 'Profile created.', 'success');
        }
        resetProfileForm();
        await renderProfileList();
        await loadActiveProfileSelect();
    } catch (err) {
        showStatus('profile-status', `Error: ${err.message}`, 'error');
    }
});


document.getElementById('profile-reset-btn')?.addEventListener('click', resetProfileForm);


document.getElementById('ner-type-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const input = document.getElementById('ner-type-label');
    const label = input.value.trim();
    if (!label) {
        showStatus('ner-type-status', 'Enter a label first.', 'error');
        return;
    }

    const selectedBeforeCreate = new Set(readSelectedTypes());
    try {
        const result = await api('/profiles/types', {
            method: 'POST',
            body: JSON.stringify({ label }),
        });
        _knownNerTypes = result.types || [];
        setEntityTypes(_knownNerTypes);
        selectedBeforeCreate.add(result.label);
        renderTypeCheckboxes(selectedBeforeCreate);
        input.value = '';
        showStatus('ner-type-status', `Entity type ${result.label} is available. Select it in profiles that should keep it during extraction.`, 'success');
    } catch (err) {
        showStatus('ner-type-status', `Error: ${err.message}`, 'error');
    }
});


async function deleteProfile(profileId) {
    if (!confirm('Delete this extraction profile?')) return;
    try {
        await api(`/profiles/${profileId}`, { method: 'DELETE' });
        if (_editingProfileId === profileId) resetProfileForm();
        await renderProfileList();
        await loadActiveProfileSelect();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


/**
 * Backwards-compatible alias for older callers.
 */
async function loadProfilesIntoUploadSelect() {
    await loadActiveProfileSelect();
}


async function loadStandardTriplesSettings() {
    const container = document.getElementById('standard-triples-settings');
    if (!container) return;

    try {
        const data = await api('/settings/standard-triples');
        _standardTripleGroups = data.groups || [];
        renderStandardTriplesSettings(new Set(data.enabled_property_ids || []));
    } catch (err) {
        container.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


function renderStandardTriplesSettings(enabledSet) {
    const container = document.getElementById('standard-triples-settings');
    if (!container) return;

    container.innerHTML = _standardTripleGroups.map(group => `
        <div class="standard-triples-group">
            <h3>${escapeHtml(group.label)}</h3>
            ${(group.properties || []).map(prop => `
                <label class="type-checkbox">
                    <input type="checkbox" value="${escapeAttr(prop.id)}" ${enabledSet.has(prop.id) ? 'checked' : ''}>
                    <span>${escapeHtml(prop.label)} <span class="class-uri">${escapeHtml(prop.id)}</span></span>
                </label>
            `).join('')}
        </div>
    `).join('');
}


function readSelectedStandardTriples() {
    return Array.from(document.querySelectorAll('#standard-triples-settings input[type="checkbox"]:checked'))
        .map(cb => cb.value);
}


document.getElementById('standard-triples-save-btn')?.addEventListener('click', async () => {
    showStatus('standard-triples-status', 'Saving...', '');
    try {
        const enabled = readSelectedStandardTriples();
        await api('/settings/standard-triples', {
            method: 'PUT',
            body: JSON.stringify({ enabled_property_ids: enabled }),
        });
        showStatus('standard-triples-status', 'Standard triples saved.', 'success');
    } catch (err) {
        showStatus('standard-triples-status', `Error: ${err.message}`, 'error');
    }
});


document.getElementById('standard-triples-reset-btn')?.addEventListener('click', loadStandardTriplesSettings);


async function loadPipelineSettings() {
    const statusEl = document.getElementById('pipeline-runtime-status');
    if (!statusEl) return;
    try {
        const data = await api('/settings/pipeline');
        const settings = data.settings || {};
        document.getElementById('pipeline-spacy-model').value = settings.spacy_model || '';
        document.getElementById('pipeline-fuzzy-threshold').value = settings.fuzzy_match_threshold ?? 85;
        document.getElementById('pipeline-grounding-limit').value = settings.grounding_search_limit ?? 5;
        document.getElementById('pipeline-timeout').value = settings.external_request_timeout ?? 15;
        document.getElementById('pipeline-coreference-enabled').checked = !!settings.coreference_enabled;
        document.getElementById('pipeline-wikidata-type-filter').checked = !!settings.wikidata_type_filter_enabled;
        renderPipelineRuntimeStatus(data);
    } catch (err) {
        statusEl.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


function renderPipelineRuntimeStatus(data) {
    const statusEl = document.getElementById('pipeline-runtime-status');
    if (!statusEl) return;
    const corefReady = data.coreferee_installed && data.coreferee_pipe_available;
    const modelVersionText = data.spacy_model_version
        ? `model ${escapeHtml(data.spacy_model_version)}`
        : 'model version unknown';
    const modelOk = data.spacy_model_installed && (data.spacy_model_version_ok ?? true);
    statusEl.innerHTML = `
        <div class="runtime-pill ${modelOk ? 'ok' : 'bad'}">spaCy ${escapeHtml(data.spacy_version || '')}: ${data.spacy_model_installed ? modelVersionText : 'model missing'}</div>
        ${data.spacy_model_required_version && !data.spacy_model_version_ok ? `<div class="status-msg error">Expected en_core_web_lg ${escapeHtml(data.spacy_model_required_version)}.</div>` : ''}
        <div class="runtime-pill ${corefReady ? 'ok' : 'bad'}">coreferee: ${corefReady ? 'ready' : 'not ready'}</div>
        ${data.coreferee_error ? `<div class="status-msg error">${escapeHtml(data.coreferee_error)}</div>` : ''}
    `;
}


document.getElementById('pipeline-settings-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    showStatus('pipeline-settings-status', 'Saving...', '');
    try {
        const payload = {
            spacy_model: document.getElementById('pipeline-spacy-model').value.trim(),
            fuzzy_match_threshold: parseInt(document.getElementById('pipeline-fuzzy-threshold').value, 10),
            grounding_search_limit: parseInt(document.getElementById('pipeline-grounding-limit').value, 10),
            external_request_timeout: parseInt(document.getElementById('pipeline-timeout').value, 10),
            coreference_enabled: document.getElementById('pipeline-coreference-enabled').checked,
            wikidata_type_filter_enabled: document.getElementById('pipeline-wikidata-type-filter').checked,
        };
        const result = await api('/settings/pipeline', {
            method: 'PUT',
            body: JSON.stringify(payload),
        });
        renderPipelineRuntimeStatus(result.status || {});
        showStatus('pipeline-settings-status', 'Pipeline settings saved. New uploads use these values.', 'success');
    } catch (err) {
        showStatus('pipeline-settings-status', `Error: ${err.message}`, 'error');
    }
});


document.getElementById('pipeline-settings-reload-btn')?.addEventListener('click', loadPipelineSettings);
