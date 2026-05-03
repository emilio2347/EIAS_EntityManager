/* ========================================
   Entities — List, search, detail, merge, alt-labels, particulars, delete
   ======================================== */

let _debounceTimer = null;

// Wire up search/filter
document.getElementById('entity-search')?.addEventListener('input', () => {
    clearTimeout(_debounceTimer);
    _debounceTimer = setTimeout(loadEntities, 300);
});
document.getElementById('entity-type-filter')?.addEventListener('change', loadEntities);
document.getElementById('entity-grounded-filter')?.addEventListener('change', loadEntities);
document.getElementById('entity-document-filter')?.addEventListener('change', loadEntities);
document.getElementById('entity-clear-all-btn')?.addEventListener('click', clearAllEntities);


async function clearAllEntities() {
    const first = confirm('Delete ALL entities? This also removes all mentions, coreference chains, and enrichment data. This cannot be undone.');
    if (!first) return;
    const second = prompt('Type DELETE to confirm clearing every entity:');
    if (second !== 'DELETE') return;

    try {
        const result = await api('/entities', { method: 'DELETE' });
        document.getElementById('entity-detail')?.classList.add('hidden');
        await loadEntities();
        alert(`Deleted ${result.deleted_count} entities.`);
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


async function loadEntities() {
    const container = document.getElementById('entity-list');
    if (!container) return;

    const q = document.getElementById('entity-search')?.value || '';
    const entityType = document.getElementById('entity-type-filter')?.value || '';
    const grounded = document.getElementById('entity-grounded-filter')?.value || '';
    const documentId = document.getElementById('entity-document-filter')?.value || '';

    const params = new URLSearchParams();
    if (q) params.set('q', q);
    if (entityType) params.set('entity_type', entityType);
    if (grounded) params.set('grounded', grounded);
    if (documentId) params.set('document_id', documentId);

    try {
        const entities = await api(`/entities?${params}`);
        if (entities.length === 0) {
            container.innerHTML = '<p style="color: var(--text-muted);">No entities found.</p>';
            return;
        }

        container.innerHTML = entities.map(e => {
            const altCount = (e.alternative_labels || []).length;
            const altSummary = altCount
                ? ` · <span title="${escapeAttr((e.alternative_labels || []).join(', '))}">${altCount} alt label${altCount === 1 ? '' : 's'}</span>`
                : '';
            return `
                <div class="list-item" onclick="showEntityDetail('${e.id}')">
                    <div class="list-item-main">
                        <span class="list-item-title">
                            ${groundingDot(e)}
                            ${escapeHtml(e.canonical_name)}
                        </span>
                        <span class="list-item-subtitle">
                            ${entityTypeTag(e.entity_type, e.id)} · ${e.mention_count} mention${e.mention_count === 1 ? '' : 's'}${altSummary}
                        </span>
                    </div>
                    <div class="list-item-actions">
                        <button class="btn btn-sm" onclick="event.stopPropagation(); openMergeModal('${e.id}')">Merge</button>
                        <button class="btn btn-sm" onclick="event.stopPropagation(); openGroundingModal('${e.id}')">Ground</button>
                        <button class="btn btn-danger btn-sm" onclick="event.stopPropagation(); deleteEntity('${e.id}')">Delete</button>
                    </div>
                </div>
            `;
        }).join('');
    } catch (err) {
        container.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


async function showEntityDetail(entityId) {
    const detailEl = document.getElementById('entity-detail');
    const contentEl = document.getElementById('entity-detail-content');
    detailEl.classList.remove('hidden');

    contentEl.innerHTML = '<div class="spinner"></div> Loading...';

    try {
        const e = await api(`/entities/${entityId}`);

        document.getElementById('entity-detail-title').textContent = e.canonical_name;

        let groundingHtml = '';
        if (e.wikidata_uri) groundingHtml += `<div class="detail-row"><span class="detail-label">Wikidata</span><span class="detail-value"><a href="${e.wikidata_uri}" target="_blank">${e.wikidata_uri}</a></span></div>`;
        if (e.dbpedia_uri) groundingHtml += `<div class="detail-row"><span class="detail-label">DBpedia</span><span class="detail-value"><a href="${e.dbpedia_uri}" target="_blank">${e.dbpedia_uri}</a></span></div>`;
        if (e.worldcat_uri) groundingHtml += `<div class="detail-row"><span class="detail-label">WorldCat</span><span class="detail-value"><a href="${e.worldcat_uri}" target="_blank">${e.worldcat_uri}</a></span></div>`;

        if (!groundingHtml) groundingHtml = '<p style="color: var(--text-muted);">Not grounded yet. <a href="#" onclick="event.preventDefault(); openGroundingModal(\'' + entityId + '\')">Search now</a></p>';

        const enrichmentHtml = e.enrichment.length > 0
            ? `<table><thead><tr><th>Property</th><th>Value</th><th>Source</th></tr></thead><tbody>
                ${e.enrichment.map(ep => `<tr><td>${escapeHtml(ep.property_name)}</td><td>${escapeHtml(ep.value)}</td><td>${ep.source}</td></tr>`).join('')}
               </tbody></table>`
            : '<p style="color: var(--text-muted);">No enrichment data.</p>';

        const canEnrich = e.wikidata_uri || e.dbpedia_uri;

        const altLabels = e.alternative_labels || [];
        const altLabelsHtml = altLabels.length
            ? altLabels.map(lab => `
                <span class="alt-label">
                    ${escapeHtml(lab)}
                    <button class="alt-label-action" title="Promote to preferred label" onclick="setPreferredLabel('${entityId}', '${escapeAttr(lab)}')">★</button>
                    <button class="alt-label-action" title="Remove alternative label" onclick="removeAltLabel('${entityId}', '${escapeAttr(lab)}')">×</button>
                </span>
            `).join(' ')
            : '<span style="color: var(--text-muted);">None — merge another entity to add alternatives.</span>';

        const ontologyClassHtml = e.ontology_class_uri
            ? `<a href="${escapeAttr(e.ontology_class_uri)}" target="_blank">${escapeHtml(e.ontology_class_uri)}</a>`
            : '<em>unmapped</em>';

        const individualHtml = e.ontology_individual_uri
            ? `<a href="${escapeAttr(e.ontology_individual_uri)}" target="_blank">${escapeHtml(e.ontology_individual_uri)}</a>
               <button class="btn btn-sm" style="margin-left: 0.5rem;" onclick="openIndividualModal('${entityId}')">Change</button>
               <button class="btn btn-sm" style="margin-left: 0.25rem;" onclick="clearIndividualLink('${entityId}')">Clear</button>`
            : `<em>not linked</em>
               <button class="btn btn-sm" style="margin-left: 0.5rem;" onclick="openIndividualModal('${entityId}')">Link…</button>`;

        contentEl.innerHTML = `
            <div class="detail-section">
                <h3>Info</h3>
                <div class="detail-row"><span class="detail-label">Type</span><span class="detail-value">${entityTypeTag(e.entity_type, e.id)}</span></div>
                <div class="detail-row"><span class="detail-label">Preferred Label</span><span class="detail-value">${escapeHtml(e.canonical_name)}</span></div>
                <div class="detail-row"><span class="detail-label">Alt Labels</span><span class="detail-value">${altLabelsHtml}</span></div>
                <div class="detail-row"><span class="detail-label">Ontology Class</span><span class="detail-value">${ontologyClassHtml}</span></div>
                <div class="detail-row"><span class="detail-label">Particular</span><span class="detail-value">${individualHtml}</span></div>
                <div class="detail-row"><span class="detail-label">Created</span><span class="detail-value">${e.created_at || ''}</span></div>
                <div style="margin-top: 0.5rem;">
                    <button class="btn btn-sm" onclick="openMergeModal('${entityId}')">Merge with another entity…</button>
                </div>
            </div>
            <div class="detail-section">
                <h3>Grounding</h3>
                ${groundingHtml}
                <div style="margin-top: 0.5rem;">
                    <button class="btn btn-sm" onclick="openGroundingModal('${entityId}')">Search Grounding</button>
                </div>
            </div>
            <div class="detail-section">
                <h3>Enrichment</h3>
                ${enrichmentHtml}
                ${canEnrich ? `<button class="btn btn-sm btn-primary" style="margin-top: 0.5rem;" onclick="openEnrichmentModal('${entityId}')">Browse Properties</button>` : ''}
            </div>
            <div class="detail-section">
                <h3>Mentions (${e.mentions.length})</h3>
                <table>
                    <thead><tr><th>Surface Form</th><th>Document</th><th>Position</th></tr></thead>
                    <tbody>
                        ${e.mentions.slice(0, 30).map(m => `
                            <tr>
                                <td>${escapeHtml(m.surface_form)}</td>
                                <td>${m.document_id.substring(0, 8)}...</td>
                                <td>${m.start_char}–${m.end_char}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>
            ${e.coreference_chains.length > 0 ? `
            <div class="detail-section">
                <h3>Coreference Chains (${e.coreference_chains.length})</h3>
                ${e.coreference_chains.map(ch => `
                    <div style="margin-bottom: 0.5rem;">
                        <strong>Chain ${ch.chain_index}:</strong>
                        ${ch.members.map(m => `<span class="tag tag-default">${escapeHtml(m.surface_form)}</span>`).join(' ')}
                    </div>
                `).join('')}
            </div>
            ` : ''}
        `;
    } catch (err) {
        contentEl.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


async function deleteEntity(entityId) {
    if (!confirm('Delete this entity and all its mentions?')) return;
    try {
        await api(`/entities/${entityId}`, { method: 'DELETE' });
        loadEntities();
        document.getElementById('entity-detail')?.classList.add('hidden');
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


/* ----------------------------------------------------------------------
   Alt-labels
   ---------------------------------------------------------------------- */

async function setPreferredLabel(entityId, label) {
    try {
        await api(`/entities/${entityId}/preflabel`, {
            method: 'PATCH',
            body: JSON.stringify({ label }),
        });
        loadEntities();
        showEntityDetail(entityId);
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


async function removeAltLabel(entityId, label) {
    if (!confirm(`Remove alternative label "${label}"?`)) return;
    try {
        const e = await api(`/entities/${entityId}`);
        const remaining = (e.alternative_labels || []).filter(l => l !== label);
        await api(`/entities/${entityId}/altlabels`, {
            method: 'PATCH',
            body: JSON.stringify({ labels: remaining }),
        });
        showEntityDetail(entityId);
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


/* ----------------------------------------------------------------------
   Merge UI
   ---------------------------------------------------------------------- */

let _mergeSearchTimer = null;
let _mergeSourceId = null;


async function openMergeModal(sourceId) {
    _mergeSourceId = sourceId;
    let source;
    try {
        source = await api(`/entities/${sourceId}`);
    } catch (err) {
        alert('Error: ' + err.message);
        return;
    }

    const html = `
        <h2 style="margin-bottom: 1rem;">Merge "${escapeHtml(source.canonical_name)}" into…</h2>
        <p style="color: var(--text-muted); margin-bottom: 1rem;">
            Pick the entity that should remain. Its preferred label is kept; <strong>${escapeHtml(source.canonical_name)}</strong>${(source.alternative_labels || []).length ? ` and its ${(source.alternative_labels || []).length} alt label(s)` : ''} will be added as alternative labels.
        </p>
        <input type="text" id="merge-search" placeholder="Search target entity..." style="width: 100%;" autofocus>
        <div id="merge-results" style="max-height: 320px; overflow-y: auto; margin-top: 0.75rem;"></div>
        <div style="margin-top: 1rem;">
            <button class="btn" onclick="closeModal()">Cancel</button>
        </div>
    `;
    openModal(html);
    document.getElementById('merge-search').addEventListener('input', () => {
        clearTimeout(_mergeSearchTimer);
        _mergeSearchTimer = setTimeout(searchMergeTargets, 200);
    });
    searchMergeTargets();
}


async function searchMergeTargets() {
    const q = document.getElementById('merge-search')?.value || '';
    const resultsEl = document.getElementById('merge-results');
    if (!resultsEl) return;
    try {
        const params = new URLSearchParams();
        if (q) params.set('q', q);
        const all = await api(`/entities?${params}`);
        const candidates = all.filter(e => e.id !== _mergeSourceId).slice(0, 50);

        if (!candidates.length) {
            resultsEl.innerHTML = '<p style="color: var(--text-muted);">No matching entities.</p>';
            return;
        }
        resultsEl.innerHTML = candidates.map(c => `
            <div class="merge-candidate" onclick="confirmMerge('${c.id}', '${escapeAttr(c.canonical_name)}')">
                <div>
                    <strong>${escapeHtml(c.canonical_name)}</strong>
                    ${entityTypeTag(c.entity_type)}
                </div>
                <div style="font-size: 0.75rem; color: var(--text-muted);">
                    ${c.mention_count} mentions${(c.alternative_labels || []).length ? ` · alt: ${escapeHtml((c.alternative_labels || []).join(', '))}` : ''}
                </div>
            </div>
        `).join('');
    } catch (err) {
        resultsEl.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


async function confirmMerge(targetId, targetName) {
    if (!_mergeSourceId) return;
    if (!confirm(`Merge into "${targetName}"? The source entity will be deleted.`)) return;
    try {
        await api(`/entities/${_mergeSourceId}/merge`, {
            method: 'POST',
            body: JSON.stringify({ target_entity_id: targetId }),
        });
        closeModal();
        document.getElementById('entity-detail')?.classList.add('hidden');
        loadEntities();
        showEntityDetail(targetId);
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


/* ----------------------------------------------------------------------
   Particulars / NamedIndividuals linking
   ---------------------------------------------------------------------- */

let _individualEntityId = null;
let _individualSearchTimer = null;
let _individualsCache = null;


async function openIndividualModal(entityId) {
    _individualEntityId = entityId;
    if (_individualsCache === null) {
        try {
            const data = await api('/ontology/individuals');
            _individualsCache = data.individuals || [];
        } catch {
            _individualsCache = [];
        }
    }

    const html = `
        <h2 style="margin-bottom: 1rem;">Link to Ontology Particular</h2>
        <p style="color: var(--text-muted); margin-bottom: 1rem;">
            Pick an existing NamedIndividual from the loaded ontology, or add a new one if none matches.
        </p>
        <input type="text" id="individual-search" placeholder="Search individuals..." style="width: 100%;" autofocus>
        <div id="individual-results" style="max-height: 280px; overflow-y: auto; margin-top: 0.75rem;"></div>
        <div class="detail-section" style="margin-top: 1rem;">
            <h3>Add a new Individual</h3>
            <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                <input type="text" id="new-individual-label" placeholder="Label (e.g. Basic Formal Ontology)" style="flex: 1; min-width: 200px;">
                <select id="new-individual-class" style="min-width: 220px;">
                    <option value="">— no class —</option>
                </select>
                <button type="button" class="btn btn-primary" onclick="createAndLinkIndividual()">Add &amp; Link</button>
            </div>
            <p id="individual-status" class="status-msg"></p>
        </div>
        <div style="margin-top: 1rem;">
            <button class="btn" onclick="closeModal()">Cancel</button>
        </div>
    `;
    openModal(html);

    // Populate class dropdown for new-individual creation
    try {
        const data = await api('/ontology/classes');
        const classes = data.classes || [];
        const sel = document.getElementById('new-individual-class');
        if (sel) {
            sel.innerHTML = '<option value="">— no class —</option>' +
                classes.map(c =>
                    `<option value="${escapeAttr(c.uri)}">${escapeHtml(c.label)}</option>`
                ).join('');
        }
    } catch {
        /* if classes fetch fails the user can still link without a class */
    }

    document.getElementById('individual-search').addEventListener('input', () => {
        clearTimeout(_individualSearchTimer);
        _individualSearchTimer = setTimeout(renderIndividualResults, 150);
    });
    renderIndividualResults();
}


function renderIndividualResults() {
    const q = (document.getElementById('individual-search')?.value || '').toLowerCase();
    const resultsEl = document.getElementById('individual-results');
    if (!resultsEl) return;

    const all = _individualsCache || [];
    const filtered = q
        ? all.filter(ind => ind.label.toLowerCase().includes(q) || ind.uri.toLowerCase().includes(q))
        : all;
    const limited = filtered.slice(0, 80);

    if (!limited.length) {
        resultsEl.innerHTML = '<p style="color: var(--text-muted);">No matching individuals. Use the form below to add one.</p>';
        return;
    }

    resultsEl.innerHTML = limited.map(ind => `
        <div class="merge-candidate" onclick="linkIndividual('${escapeAttr(ind.uri)}')">
            <div><strong>${escapeHtml(ind.label)}</strong></div>
            <div style="font-size: 0.75rem; color: var(--text-muted); font-family: monospace;">${escapeHtml(ind.uri)}</div>
        </div>
    `).join('');
}


async function linkIndividual(uri) {
    if (!_individualEntityId) return;
    try {
        await api(`/entities/${_individualEntityId}/individual`, {
            method: 'PATCH',
            body: JSON.stringify({ ontology_individual_uri: uri }),
        });
        const eid = _individualEntityId;
        closeModal();
        showEntityDetail(eid);
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


async function clearIndividualLink(entityId) {
    try {
        await api(`/entities/${entityId}/individual`, {
            method: 'PATCH',
            body: JSON.stringify({ ontology_individual_uri: null }),
        });
        showEntityDetail(entityId);
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


async function createAndLinkIndividual() {
    const label = document.getElementById('new-individual-label')?.value.trim();
    const classUri = document.getElementById('new-individual-class')?.value || null;
    if (!label) {
        showStatus('individual-status', 'A label is required.', 'error');
        return;
    }
    showStatus('individual-status', 'Adding to ontology...', '');
    try {
        const result = await api('/ontology/individuals', {
            method: 'POST',
            body: JSON.stringify({ label, class_uri: classUri }),
        });
        // Invalidate cache so the new individual is searchable next time the modal opens
        _individualsCache = null;
        await linkIndividual(result.individual.uri);
    } catch (err) {
        showStatus('individual-status', `Error: ${err.message}`, 'error');
    }
}
