/* ========================================
   Shared settings — standard triples and pipeline runtime
   ======================================== */

let _standardTripleGroups = [];

async function loadSettingsView() {
    await loadStandardTriplesSettings();
    await loadPipelineSettings();
}

function loadDocumentManagerSettings() {
    return Promise.resolve();
}

function loadTopicManagerSettings() {
    return loadTopicManagerExtractionSettings();
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
        <div class="runtime-pill ${corefReady ? 'ok' : 'bad'}">coreference: ${corefReady ? 'ready' : 'not ready'}</div>
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
        showStatus('pipeline-settings-status', 'Pipeline settings saved.', 'success');
    } catch (err) {
        showStatus('pipeline-settings-status', `Error: ${err.message}`, 'error');
    }
});

document.getElementById('pipeline-settings-reload-btn')?.addEventListener('click', loadPipelineSettings);

async function loadTopicManagerExtractionSettings() {
    const statusEl = document.getElementById('topic-manager-settings-status');
    const form = document.getElementById('topic-manager-settings-form');
    if (!form) return;
    try {
        const data = await api('/settings/topic-manager');
        const settings = data.settings || {};
        document.getElementById('tm-settings-max-keywords').value = settings.max_keywords ?? 40;
        document.getElementById('tm-settings-min-phrase-chars').value = settings.min_phrase_chars ?? 3;
        document.getElementById('tm-settings-max-phrase-words').value = settings.max_phrase_words ?? 5;
        document.getElementById('tm-settings-unigram-mode').value = settings.unigram_mode || 'proper_nouns_only';
        document.getElementById('tm-settings-fast-limit').value = settings.fast_autocache_limit ?? 15;
        document.getElementById('tm-settings-fast-rows').value = settings.fast_autocache_rows ?? 5;
        if (statusEl) statusEl.textContent = '';
    } catch (err) {
        if (statusEl) statusEl.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}

document.getElementById('topic-manager-settings-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    showStatus('topic-manager-settings-status', 'Saving...', '');
    try {
        const payload = {
            max_keywords: parseInt(document.getElementById('tm-settings-max-keywords').value, 10),
            min_phrase_chars: parseInt(document.getElementById('tm-settings-min-phrase-chars').value, 10),
            max_phrase_words: parseInt(document.getElementById('tm-settings-max-phrase-words').value, 10),
            unigram_mode: document.getElementById('tm-settings-unigram-mode').value,
            fast_autocache_limit: parseInt(document.getElementById('tm-settings-fast-limit').value, 10),
            fast_autocache_rows: parseInt(document.getElementById('tm-settings-fast-rows').value, 10),
        };
        await api('/settings/topic-manager', {
            method: 'PUT',
            body: JSON.stringify(payload),
        });
        showStatus('topic-manager-settings-status', 'TopicManager settings saved.', 'success');
    } catch (err) {
        showStatus('topic-manager-settings-status', `Error: ${err.message}`, 'error');
    }
});

document.getElementById('topic-manager-settings-reload-btn')?.addEventListener('click', loadTopicManagerExtractionSettings);
