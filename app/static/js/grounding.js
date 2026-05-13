/* ========================================
   Grounding — Search and confirm entity groundings
   ======================================== */

let _groundingSelection = { wikidata: null };


async function openGroundingModal(entityId) {
    _groundingSelection = { wikidata: null };

    openModal('<div class="spinner"></div> Searching Wikidata...');

    try {
        const data = await api(`/grounding/${entityId}/search`, { method: 'POST' });
        const hasGrounding = data.grounding && (
            data.grounding.wikidata_uri || data.grounding.dbpedia_uri || data.grounding.worldcat_uri
        );

        let html = `
            <h2 style="margin-bottom: 1rem;">Ground Entity: ${escapeHtml(data.entity_name)}</h2>
            <p style="color: var(--text-muted); margin-bottom: 1.5rem;">
                Type: ${entityTypeTag(data.entity_type)} — Select the Wikidata item. DBpedia and WorldCat URIs are filled from Wikidata when available.
            </p>
        `;

        if (hasGrounding) {
            html += renderCurrentGrounding(data.grounding);
        }

        html += renderCandidateSection('Wikidata', 'wikidata', data.candidates.wikidata, entityId);
        html += renderDerivedWorldCatSection(data.candidates.worldcat);

        html += `
            <div style="margin-top: 1.5rem; display: flex; gap: 0.75rem;">
                <button class="btn btn-primary" onclick="confirmGrounding('${entityId}', ${hasGrounding ? 'true' : 'false'})">${hasGrounding ? 'Replace Grounding' : 'Confirm Selection'}</button>
                <button class="btn" onclick="closeModal()">Cancel</button>
            </div>
        `;

        document.getElementById('modal-content').innerHTML = html;
    } catch (err) {
        document.getElementById('modal-content').innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


function renderCurrentGrounding(grounding) {
    const rows = [
        ['Wikidata', grounding.wikidata_uri],
        ['DBpedia', grounding.dbpedia_uri],
        ['WorldCat', grounding.worldcat_uri],
    ].filter(([, uri]) => uri);

    return `
        <div class="detail-section grounding-current">
            <h3>Current Grounding</h3>
            ${rows.map(([label, uri]) => `
                <div class="detail-row">
                    <span class="detail-label">${label}</span>
                    <span class="detail-value"><a href="${escapeAttr(uri)}" target="_blank">${escapeHtml(uri)}</a></span>
                </div>
            `).join('')}
            <p style="color: var(--text-muted); margin-top: 0.75rem;">
                Replacing this grounding removes the existing enrichment properties and imports the standard triples for the new Wikidata item.
            </p>
        </div>
    `;
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


function renderDerivedWorldCatSection(candidates) {
    let html = `<div class="detail-section"><h3>WorldCat Entities Found Through Wikidata</h3>`;
    if (!candidates || candidates.length === 0) {
        html += '<p style="color: var(--text-muted);">No WorldCat Entity IDs were found on the current Wikidata candidates.</p>';
    } else {
        html += candidates.slice(0, 5).map(c => `
            <div class="candidate-card derived-candidate">
                <div class="candidate-source">worldcat</div>
                <div class="candidate-label">${escapeHtml(c.label)}</div>
                <div class="candidate-desc">${escapeHtml(c.description || '')}</div>
                <div style="font-size: 0.75rem; color: var(--text-muted); margin-top: 0.25rem; font-family: monospace;">${escapeHtml(c.uri)}</div>
            </div>
        `).join('');
    }
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


async function confirmGrounding(entityId, isReplacement = false) {
    const body = {};
    if (_groundingSelection.wikidata) body.wikidata_uri = _groundingSelection.wikidata;

    if (!body.wikidata_uri) {
        alert('Please select a Wikidata candidate or enter a custom Wikidata URI.');
        return;
    }
    body.replace_enrichment = true;

    if (isReplacement) {
        const ok = confirm('Replace this grounding? Existing enrichment properties for this entity will be removed and standard triples will be imported for the new grounding.');
        if (!ok) return;
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


async function clearGrounding(entityId) {
    const ok = confirm('Remove this grounding? This clears Wikidata, DBpedia, WorldCat, and all enrichment properties for this entity.');
    if (!ok) return;

    try {
        await api(`/grounding/${entityId}`, { method: 'DELETE' });
        loadEntities();
        showEntityDetail(entityId);
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


function escapeAttr(str) {
    return (str || '').replace(/'/g, "\\'").replace(/"/g, '&quot;');
}
