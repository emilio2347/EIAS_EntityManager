/* ========================================
   Grounding — Search and confirm entity groundings
   ======================================== */

let _groundingSelection = { wikidata: null, dbpedia: null, worldcat: null };


async function openGroundingModal(entityId) {
    _groundingSelection = { wikidata: null, dbpedia: null, worldcat: null };

    openModal('<div class="spinner"></div> Searching Wikidata, DBpedia, and WorldCat...');

    try {
        const data = await api(`/grounding/${entityId}/search`, { method: 'POST' });

        let html = `
            <h2 style="margin-bottom: 1rem;">Ground Entity: ${escapeHtml(data.entity_name)}</h2>
            <p style="color: var(--text-muted); margin-bottom: 1.5rem;">
                Type: ${entityTypeTag(data.entity_type)} — Select a candidate from each source, or enter a custom URI.
            </p>
        `;

        // Wikidata
        html += renderCandidateSection('Wikidata', 'wikidata', data.candidates.wikidata, entityId);
        html += renderCandidateSection('DBpedia', 'dbpedia', data.candidates.dbpedia, entityId);
        html += renderCandidateSection('WorldCat', 'worldcat', data.candidates.worldcat, entityId);

        html += `
            <div style="margin-top: 1.5rem; display: flex; gap: 0.75rem;">
                <button class="btn btn-primary" onclick="confirmGrounding('${entityId}')">Confirm Selection</button>
                <button class="btn" onclick="closeModal()">Cancel</button>
            </div>
        `;

        document.getElementById('modal-content').innerHTML = html;
    } catch (err) {
        document.getElementById('modal-content').innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


function renderCandidateSection(title, source, candidates, entityId) {
    let html = `<div class="detail-section"><h3>${title}</h3>`;

    if (!candidates || candidates.length === 0) {
        html += '<p style="color: var(--text-muted);">No candidates found.</p>';
    } else {
        for (let i = 0; i < candidates.length; i++) {
            const c = candidates[i];
            html += `
                <div class="candidate-card" id="card-${source}-${i}" onclick="selectCandidate('${source}', ${i}, '${escapeAttr(c.uri)}')">
                    <div class="candidate-source">${source}</div>
                    <div class="candidate-label">${escapeHtml(c.label)}</div>
                    <div class="candidate-desc">${escapeHtml(c.description || '')}</div>
                    <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.25rem; font-family: monospace;">${escapeHtml(c.uri)}</div>
                </div>
            `;
        }
    }

    // Custom URI input — always shown so the user can override or fill in manually
    html += `
        <div class="custom-uri-row">
            <label for="custom-uri-${source}">Custom URI:</label>
            <input type="text" id="custom-uri-${source}"
                   placeholder="https://..."
                   oninput="onCustomUriInput('${source}', this.value)">
        </div>
    `;

    html += '</div>';
    return html;
}


function selectCandidate(source, index, uri) {
    // Deselect all cards in this source
    document.querySelectorAll(`[id^="card-${source}-"]`).forEach(el => el.classList.remove('selected'));

    // If clicking the already-selected one, deselect
    if (_groundingSelection[source] === uri) {
        _groundingSelection[source] = null;
        return;
    }

    // Select this one
    document.getElementById(`card-${source}-${index}`).classList.add('selected');
    _groundingSelection[source] = uri;

    // Clear the custom input since user picked a candidate
    const customInput = document.getElementById(`custom-uri-${source}`);
    if (customInput) customInput.value = '';
}


function onCustomUriInput(source, value) {
    // When user types a custom URI, deselect any candidate card for this source
    document.querySelectorAll(`[id^="card-${source}-"]`).forEach(el => el.classList.remove('selected'));

    const trimmed = value.trim();
    _groundingSelection[source] = trimmed || null;
}


async function confirmGrounding(entityId) {
    const body = {};
    if (_groundingSelection.wikidata) body.wikidata_uri = _groundingSelection.wikidata;
    if (_groundingSelection.dbpedia) body.dbpedia_uri = _groundingSelection.dbpedia;
    if (_groundingSelection.worldcat) body.worldcat_uri = _groundingSelection.worldcat;

    if (Object.keys(body).length === 0) {
        alert('Please select at least one candidate or enter a custom URI.');
        return;
    }

    try {
        await api(`/grounding/${entityId}/confirm`, {
            method: 'POST',
            body: JSON.stringify(body),
        });
        closeModal();
        loadEntities();
        showEntityDetail(entityId);
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


function escapeAttr(str) {
    return (str || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
}
