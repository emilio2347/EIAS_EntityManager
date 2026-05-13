/* ========================================
   Documents — Upload, list, detail
   ======================================== */

// Upload form
document.getElementById('upload-form')?.addEventListener('submit', async (e) => {
    e.preventDefault();
    const fileInput = document.getElementById('file-input');
    const btn = document.getElementById('upload-btn');

    if (!fileInput.files.length) return;

    const files = Array.from(fileInput.files);
    btn.disabled = true;
    btn.textContent = files.length === 1 ? 'Processing...' : `Processing 1/${files.length}...`;
    showStatus('upload-status', `Queued ${files.length} document${files.length === 1 ? '' : 's'} for processing.`, '');
    renderUploadQueue(files.map(file => ({ name: file.name, status: 'queued' })));

    const queue = files.map(file => ({ file, name: file.name, status: 'queued', result: null, error: '' }));
    let successCount = 0;

    for (let i = 0; i < queue.length; i++) {
        queue[i].status = 'processing';
        btn.textContent = `Processing ${i + 1}/${queue.length}...`;
        renderUploadQueue(queue);
        try {
            const formData = new FormData();
            formData.append('file', queue[i].file);
            const profileId = getActiveProfileId();
            if (profileId) formData.append('profile_id', profileId);

            queue[i].result = await apiUpload('/documents/upload', formData);
            queue[i].status = 'done';
            successCount += 1;
        } catch (err) {
            queue[i].status = 'error';
            queue[i].error = err.message;
        }
        renderUploadQueue(queue);
    }

    fileInput.value = '';
    await loadDocuments();
    await loadDocumentFilterOptions();
    showStatus(
        'upload-status',
        `Finished ${successCount}/${queue.length} document${queue.length === 1 ? '' : 's'}.`,
        successCount === queue.length ? 'success' : 'error'
    );
    if (_currentDocumentViewDoc) {
        await loadDocumentViewOptions(_currentDocumentViewDoc.id);
    }

    btn.disabled = false;
    btn.textContent = 'Upload & Process';
});


function renderUploadQueue(items) {
    const queueEl = document.getElementById('upload-queue');
    if (!queueEl) return;
    if (!items.length) {
        queueEl.innerHTML = '';
        return;
    }
    queueEl.innerHTML = items.map(item => {
        const result = item.result
            ? `${item.result.entities_found} entities · ${item.result.coref_chains} coref chains`
            : item.error;
        return `
            <div class="upload-queue-item ${item.status}">
                <span class="upload-queue-name">${escapeHtml(item.name)}</span>
                <span class="upload-queue-status">${escapeHtml(item.status)}${result ? ` · ${escapeHtml(result)}` : ''}</span>
            </div>
        `;
    }).join('');
}


async function loadDocuments() {
    const container = document.getElementById('document-list');
    if (!container) return;

    try {
        const profileId = getActiveProfileId();
        const params = new URLSearchParams();
        if (profileId) params.set('profile_id', profileId);
        const docs = await api(`/documents?${params}`);
        if (docs.length === 0) {
            container.innerHTML = '<p style="color: var(--text-muted);">No documents uploaded yet.</p>';
            return;
        }

        container.innerHTML = docs.map(doc => `
            <div class="list-item" onclick="showDocument('${doc.id}')">
                <div class="list-item-main">
                    <span class="list-item-title">${escapeHtml(doc.filename)}</span>
                    <span class="list-item-subtitle">
                        ${doc.filetype.toUpperCase()} · ${doc.text_length.toLocaleString()} chars · ${doc.mention_count} mentions
                        · ${doc.uploaded_at ? new Date(doc.uploaded_at).toLocaleDateString() : ''}
                    </span>
                </div>
                <div class="list-item-actions">
                    <button class="btn btn-sm" onclick="event.stopPropagation(); switchToDocumentView('${doc.id}')">Open View</button>
                    <button class="btn btn-danger btn-sm" onclick="event.stopPropagation(); deleteDocument('${doc.id}')">Delete</button>
                </div>
            </div>
        `).join('');
    } catch (err) {
        container.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


async function showDocument(docId) {
    const detailEl = document.getElementById('document-detail');
    const contentEl = document.getElementById('doc-detail-content');
    detailEl.classList.remove('hidden');

    contentEl.innerHTML = '<div class="spinner"></div> Loading...';

    try {
        const doc = await api(`/documents/${docId}`);

        // Group mentions by entity
        const byEntity = {};
        for (const m of doc.mentions) {
            if (!byEntity[m.entity_id]) byEntity[m.entity_id] = [];
            byEntity[m.entity_id].push(m);
        }

        const textPreview = doc.content_text.length > 500
            ? doc.content_text.substring(0, 500) + '...'
            : doc.content_text;

        contentEl.innerHTML = `
            <div class="detail-section">
                <h3>Info</h3>
                <div class="detail-row"><span class="detail-label">Filename</span><span class="detail-value">${escapeHtml(doc.filename)}</span></div>
                <div class="detail-row"><span class="detail-label">Type</span><span class="detail-value">${doc.filetype}</span></div>
                <div class="detail-row"><span class="detail-label">Uploaded</span><span class="detail-value">${doc.uploaded_at || ''}</span></div>
            </div>
            <div class="detail-section">
                <h3>Text Preview</h3>
                <p style="font-size: 0.85rem; white-space: pre-wrap; color: var(--text-muted);">${escapeHtml(textPreview)}</p>
            </div>
            <div class="detail-section">
                <h3>Entity Mentions (${doc.mentions.length})</h3>
                <table>
                    <thead><tr><th>Surface Form</th><th>Entity ID</th><th>Position</th><th>Sentence</th></tr></thead>
                    <tbody>
                        ${doc.mentions.slice(0, 50).map(m => `
                            <tr>
                                <td>${escapeHtml(m.surface_form)}</td>
                                <td><a href="#" onclick="event.preventDefault(); switchToEntity('${m.entity_id}')">${m.entity_id.substring(0, 8)}...</a></td>
                                <td>${m.start_char}–${m.end_char}</td>
                                <td style="max-width: 300px; overflow: hidden; text-overflow: ellipsis;">${escapeHtml(m.sentence || '')}</td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
                ${doc.mentions.length > 50 ? `<p style="color: var(--text-muted); margin-top: 0.5rem;">Showing 50 of ${doc.mentions.length} mentions.</p>` : ''}
            </div>
        `;
    } catch (err) {
        contentEl.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


async function deleteDocument(docId) {
    if (!confirm('Delete this document and its mentions? Entities that only appear in this document will also be deleted.')) return;
    try {
        const result = await api(`/documents/${docId}`, { method: 'DELETE' });
        await loadDocuments();
        await loadDocumentFilterOptions();
        document.getElementById('document-detail')?.classList.add('hidden');
        if (_currentDocumentViewDoc?.id === docId) {
            _currentDocumentViewDoc = null;
            const renderedText = document.getElementById('document-rendered-text');
            if (renderedText) renderedText.innerHTML = '';
            document.getElementById('document-entity-focus')?.classList.add('hidden');
            await loadDocumentViewOptions();
        }
        showStatus(
            'upload-status',
            `Deleted document and ${result.deleted_entity_count || 0} document-only entit${result.deleted_entity_count === 1 ? 'y' : 'ies'}.`,
            'success'
        );
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


/* ----------------------------------------------------------------------
   Document View — rendered text, entity focus, manual mentions
   ---------------------------------------------------------------------- */

let _currentDocumentViewDoc = null;
let _documentSelectionRange = null;
let _documentMergeSearchTimer = null;

document.getElementById('document-view-select')?.addEventListener('change', (e) => {
    if (e.target.value) loadDocumentView(e.target.value);
});


async function loadDocumentViewOptions(selectedId = '') {
    const select = document.getElementById('document-view-select');
    if (!select) return;
    try {
        const profileId = getActiveProfileId();
        const params = new URLSearchParams();
        if (profileId) params.set('profile_id', profileId);
        const docs = await api(`/documents?${params}`);
        select.innerHTML = '<option value="">Select a document</option>' +
            docs.map(d => `<option value="${d.id}">${escapeHtml(d.filename)}</option>`).join('');
        const targetId = selectedId || select.value;
        if (targetId && docs.some(d => d.id === targetId)) {
            select.value = targetId;
            await loadDocumentView(targetId);
        }
    } catch (err) {
        showStatus('document-view-status', `Error: ${err.message}`, 'error');
    }
}


async function switchToDocumentView(docId) {
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('[data-view="document-view"]')?.classList.add('active');
    document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
    document.getElementById('view-document-view')?.classList.remove('hidden');
    await loadDocumentViewOptions(docId);
}


async function loadDocumentView(docId) {
    const textEl = document.getElementById('document-rendered-text');
    if (!textEl) return;
    showStatus('document-view-status', 'Loading document...', '');
    textEl.innerHTML = '<div class="spinner"></div> Loading...';
    try {
        _currentDocumentViewDoc = await api(`/documents/${docId}`);
        textEl.innerHTML = renderDocumentText(_currentDocumentViewDoc);
        bindDocumentViewInteractions();
        showStatus(
            'document-view-status',
            `${_currentDocumentViewDoc.filename} · ${_currentDocumentViewDoc.mentions.length} mentions · ${(_currentDocumentViewDoc.coreference_chains || []).length} coreference chains`,
            'success'
        );
    } catch (err) {
        showStatus('document-view-status', `Error: ${err.message}`, 'error');
        textEl.innerHTML = '';
    }
}


function renderDocumentText(doc) {
    const text = doc.content_text || '';
    const decorations = [];
    const occupied = [];

    for (const mention of [...(doc.mentions || [])].sort((a, b) => a.start_char - b.start_char)) {
        const trimmed = trimDecorationRange(text, mention.start_char, mention.end_char);
        if (!trimmed) continue;
        if (rangeOverlapsAny(trimmed.start, trimmed.end, occupied)) continue;
        occupied.push([trimmed.start, trimmed.end]);
        decorations.push({
            kind: 'mention',
            start: trimmed.start,
            end: trimmed.end,
            mention,
        });
    }

    for (const chain of doc.coreference_chains || []) {
        if (!chain.entity_id) continue;
        for (const member of chain.members || []) {
            const trimmed = trimDecorationRange(text, member.start_char, member.end_char);
            if (!trimmed) continue;
            if (rangeOverlapsAny(trimmed.start, trimmed.end, occupied)) continue;
            occupied.push([trimmed.start, trimmed.end]);
            decorations.push({
                kind: 'coref',
                start: trimmed.start,
                end: trimmed.end,
                entityId: chain.entity_id,
                member,
            });
        }
    }

    decorations.sort((a, b) => a.start - b.start);
    let cursor = 0;
    let html = '';
    for (const deco of decorations) {
        if (deco.start > cursor) {
            html += textSpan(text.slice(cursor, deco.start), cursor);
        }
        const original = text.slice(deco.start, deco.end);
        if (deco.kind === 'mention') {
            const entity = deco.mention.entity || {};
            const label = normalizeInlineLabel(entity.canonical_name || deco.mention.surface_form || original);
            const type = entity.entity_type || 'MISC';
            html += `<span class="document-entity-box ${documentEntityClass(type)}" data-start="${deco.start}" data-end="${deco.end}" data-entity-id="${escapeAttr(deco.mention.entity_id)}" data-preferred-label="${escapeAttr(label)}" data-tooltip="${escapeAttr(entityTooltip(entity, deco.mention))}">${escapeHtml(original)}</span>`;
        } else {
            html += `<span class="document-coref-marker" data-start="${deco.start}" data-end="${deco.end}" data-coref-entity="${escapeAttr(deco.entityId)}">${escapeHtml(original)}</span>`;
        }
        cursor = deco.end;
    }
    if (cursor < text.length) {
        html += textSpan(text.slice(cursor), cursor);
    }
    return html || '<p style="color: var(--text-muted);">This document has no text.</p>';
}


function trimDecorationRange(text, start, end) {
    let nextStart = Math.max(0, start);
    let nextEnd = Math.min(text.length, end);
    while (nextStart < nextEnd && /\s/.test(text[nextStart])) nextStart += 1;
    while (nextEnd > nextStart && /\s/.test(text[nextEnd - 1])) nextEnd -= 1;
    if (nextEnd <= nextStart) return null;
    return { start: nextStart, end: nextEnd };
}


function normalizeInlineLabel(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
}


function documentEntityClass(type) {
    const colorTypes = ['PERSON', 'ORG', 'GPE', 'LOC', 'WORK_OF_ART', 'EVENT', 'CONCEPT'];
    return colorTypes.includes(type) ? `tag-${type}` : 'tag-default';
}


function textSpan(text, start) {
    return `<span data-start="${start}" data-end="${start + text.length}">${escapeHtml(text)}</span>`;
}


function rangeOverlapsAny(start, end, ranges) {
    return ranges.some(([a, b]) => start < b && end > a);
}


function entityTooltip(entity, mention) {
    const lines = [
        normalizeInlineLabel(entity.canonical_name || mention.surface_form),
        entity.entity_type || '',
        (entity.alternative_labels || []).length ? `Alt: ${(entity.alternative_labels || []).join(', ')}` : '',
        entity.ontology_individual_uri ? 'Linked to ontology' : 'Not linked to ontology',
    ].filter(Boolean);
    return lines.join('\n');
}


function bindDocumentViewInteractions() {
    const textEl = document.getElementById('document-rendered-text');
    if (!textEl) return;

    textEl.querySelectorAll('.document-entity-box').forEach(box => {
        box.addEventListener('mouseenter', () => setCorefHighlight(box.dataset.entityId, true));
        box.addEventListener('mouseleave', () => setCorefHighlight(box.dataset.entityId, false));
        box.addEventListener('click', (e) => {
            e.stopPropagation();
            showDocumentEntityFocus(box.dataset.entityId, box);
        });
    });

    textEl.addEventListener('mouseup', () => {
        setTimeout(showDocumentSelectionPrompt, 0);
    });
}


function setCorefHighlight(entityId, active) {
    document.querySelectorAll(`.document-coref-marker[data-coref-entity="${CSS.escape(entityId)}"]`).forEach(el => {
        el.classList.toggle('active', active);
    });
}


async function showDocumentEntityFocus(entityId, anchorEl = null) {
    const focus = document.getElementById('document-entity-focus');
    const title = document.getElementById('document-entity-focus-title');
    const content = document.getElementById('document-entity-focus-content');
    if (!focus || !title || !content) return;
    focus.classList.remove('hidden');
    positionDocumentFocusPreview(focus, anchorEl);
    content.innerHTML = '<div class="spinner"></div> Loading...';
    try {
        const e = await api(`/entities/${entityId}`);
        title.textContent = e.canonical_name;
        const grounding = [e.wikidata_uri, e.dbpedia_uri, e.worldcat_uri].filter(Boolean);
        const previewHtml = e.image_url
            ? `<div class="entity-preview"><img src="${escapeAttr(e.image_url)}" alt="${escapeAttr(e.canonical_name)}"></div>`
            : '';
        content.innerHTML = `
            ${previewHtml}
            <div class="detail-section">
                <h3>Info</h3>
                <div class="detail-row"><span class="detail-label">Type</span><span class="detail-value">${entityTypeTag(e.entity_type, e.id)}</span></div>
                <div class="detail-row"><span class="detail-label">Preferred Label</span><span class="detail-value">${escapeHtml(e.canonical_name)}</span></div>
                <div class="detail-row"><span class="detail-label">Alt Labels</span><span class="detail-value">${(e.alternative_labels || []).map(escapeHtml).join(', ') || '<em>None</em>'}</span></div>
                <div class="detail-row"><span class="detail-label">Particular</span><span class="detail-value">${e.ontology_individual_uri ? escapeHtml(formatEiasUri(e.ontology_individual_uri)) : '<em>not linked</em>'}</span></div>
                <div class="detail-row"><span class="detail-label">Grounding</span><span class="detail-value">${grounding.length ? grounding.map(escapeHtml).join('<br>') : '<em>not grounded</em>'}</span></div>
                <div style="margin-top: 0.75rem; display: flex; gap: 0.5rem; flex-wrap: wrap;">
                    <button class="btn btn-sm" onclick="openAltLabelsModal('${entityId}')">Edit Alt Labels</button>
                    <button class="btn btn-sm" onclick="openIndividualModal('${entityId}')">Link Ontology</button>
                    <button class="btn btn-sm" onclick="openGroundingModal('${entityId}')">Ground</button>
                    <button class="btn btn-sm btn-primary" onclick="switchToEntity('${entityId}')">Open Entity Tab</button>
                </div>
            </div>
            <div class="detail-section">
                <h3>Mentions (${e.mentions.length})</h3>
                <table>
                    <tbody>
                        ${e.mentions.slice(0, 12).map(m => `<tr><td>${escapeHtml(m.surface_form)}</td><td>${escapeHtml(m.document_filename || '')}</td><td>${m.start_char}-${m.end_char}</td></tr>`).join('')}
                    </tbody>
                </table>
            </div>
        `;
    } catch (err) {
        content.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


function positionDocumentFocusPreview(focusEl, anchorEl) {
    if (!focusEl || !anchorEl) return;
    focusEl.classList.add('anchored-focus-panel');
    const container = document.getElementById('view-document-view');
    const containerRect = container?.getBoundingClientRect();
    const anchorRect = anchorEl.getBoundingClientRect();
    const anchorTop = anchorRect.top + window.scrollY;
    if (containerRect && window.matchMedia('(min-width: 900px)').matches) {
        const containerTop = containerRect.top + window.scrollY;
        focusEl.style.alignSelf = 'start';
        focusEl.style.marginTop = `${Math.max(0, anchorTop - containerTop)}px`;
        return;
    }
    focusEl.style.alignSelf = '';
    focusEl.style.marginTop = '1rem';
    window.requestAnimationFrame(() => {
        focusEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    });
}


function showDocumentSelectionPrompt() {
    const container = document.getElementById('document-rendered-text');
    const selection = window.getSelection();
    if (!container || !selection || selection.isCollapsed || !container.contains(selection.anchorNode)) return;
    const range = getSelectionCharRange(selection, container);
    if (!range) return;

    _documentSelectionRange = range;
    removeDocumentSelectionPrompt();
    const rect = selection.getRangeAt(0).getBoundingClientRect();
    const prompt = document.createElement('div');
    prompt.id = 'document-selection-prompt';
    prompt.className = 'document-selection-prompt';
    prompt.style.left = `${Math.min(window.innerWidth - 170, Math.max(12, rect.left + window.scrollX))}px`;
    prompt.style.top = `${rect.bottom + window.scrollY + 8}px`;
    prompt.innerHTML = `
        <button class="btn btn-primary btn-sm" onclick="openDocumentAddEntityModal()">Add</button>
        <button class="btn btn-sm" onclick="openDocumentMentionMergeModal()">Merge</button>
    `;
    document.body.appendChild(prompt);
}


function removeDocumentSelectionPrompt() {
    document.getElementById('document-selection-prompt')?.remove();
}


function getSelectionCharRange(selection, container) {
    const range = selection.getRangeAt(0);
    const start = charOffsetFromNode(range.startContainer, range.startOffset, container);
    const end = charOffsetFromNode(range.endContainer, range.endOffset, container);
    if (start === null || end === null || start === end) return null;
    return {
        start_char: Math.min(start, end),
        end_char: Math.max(start, end),
        text: selection.toString().trim(),
    };
}


function charOffsetFromNode(node, offset, container) {
    const element = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
    const carrier = element?.closest?.('[data-start][data-end]');
    if (!carrier || !container.contains(carrier)) return null;
    const start = parseInt(carrier.dataset.start, 10);
    const end = parseInt(carrier.dataset.end, 10);
    const textLength = node.textContent?.length || 1;
    const ratio = Math.min(1, Math.max(0, offset / textLength));
    return Math.round(start + ((end - start) * ratio));
}


async function addEntityFromDocumentSelection() {
    if (!_currentDocumentViewDoc || !_documentSelectionRange) return;
    const range = _documentSelectionRange;
    const type = document.getElementById('document-new-entity-type')?.value || 'MISC';
    try {
        const result = await api(`/documents/${_currentDocumentViewDoc.id}/entities`, {
            method: 'POST',
            body: JSON.stringify({
                label: range.text,
                start_char: range.start_char,
                end_char: range.end_char,
                entity_type: type,
            }),
        });
        closeModal();
        await loadDocumentView(_currentDocumentViewDoc.id);
        showDocumentEntityFocus(result.entity_id);
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


async function openDocumentAddEntityModal() {
    if (!_currentDocumentViewDoc || !_documentSelectionRange) return;
    removeDocumentSelectionPrompt();
    await loadKnownNerTypes();
    const html = `
        <h2 style="margin-bottom: 1rem;">Add Entity</h2>
        <p style="color: var(--text-muted); margin-bottom: 1rem;">Create "${escapeHtml(_documentSelectionRange.text)}" as a new entity.</p>
        <div class="custom-uri-row">
            <label for="document-new-entity-type">Type:</label>
            <select id="document-new-entity-type">${entityTypeOptionsHtml('MISC', false)}</select>
        </div>
        <div style="margin-top: 1rem; display: flex; gap: 0.5rem;">
            <button class="btn btn-primary" onclick="addEntityFromDocumentSelection()">Create</button>
            <button class="btn" onclick="closeModal()">Cancel</button>
        </div>
    `;
    openModal(html);
}


function openDocumentMentionMergeModal() {
    if (!_currentDocumentViewDoc || !_documentSelectionRange) return;
    removeDocumentSelectionPrompt();
    const html = `
        <h2 style="margin-bottom: 1rem;">Merge Selected Text</h2>
        <p style="color: var(--text-muted); margin-bottom: 1rem;">Choose the existing entity that should receive "${escapeHtml(_documentSelectionRange.text)}" as a mention.</p>
        <input type="text" id="document-mention-entity-search" placeholder="Search entities..." style="width: 100%;" autofocus>
        <div id="document-mention-entity-results" style="max-height: 320px; overflow-y: auto; margin-top: 0.75rem;"></div>
    `;
    openModal(html);
    document.getElementById('document-mention-entity-search')?.addEventListener('input', () => {
        clearTimeout(_documentMergeSearchTimer);
        _documentMergeSearchTimer = setTimeout(searchDocumentMentionTargets, 150);
    });
    searchDocumentMentionTargets();
}


async function searchDocumentMentionTargets() {
    const q = document.getElementById('document-mention-entity-search')?.value || '';
    const resultsEl = document.getElementById('document-mention-entity-results');
    if (!resultsEl) return;
    const params = new URLSearchParams();
    if (q) params.set('q', q);
    const profileId = getActiveProfileId();
    if (profileId) params.set('profile_id', profileId);
    try {
        const entities = await api(`/entities?${params}`);
        resultsEl.innerHTML = entities.slice(0, 50).map(e => `
            <div class="merge-candidate" onclick="appendDocumentMention('${e.id}')">
                <strong>${escapeHtml(e.canonical_name)}</strong>
                ${entityTypeTag(e.entity_type)}
                <div style="font-size: 0.75rem; color: var(--text-muted);">${e.mention_count} mentions</div>
            </div>
        `).join('') || '<p style="color: var(--text-muted);">No matching entities.</p>';
    } catch (err) {
        resultsEl.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


async function appendDocumentMention(entityId) {
    if (!_currentDocumentViewDoc || !_documentSelectionRange) return;
    try {
        await api(`/documents/${_currentDocumentViewDoc.id}/mentions`, {
            method: 'POST',
            body: JSON.stringify({
                entity_id: entityId,
                start_char: _documentSelectionRange.start_char,
                end_char: _documentSelectionRange.end_char,
            }),
        });
        closeModal();
        await loadDocumentView(_currentDocumentViewDoc.id);
        showDocumentEntityFocus(entityId);
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


document.addEventListener('mousedown', (e) => {
    const prompt = document.getElementById('document-selection-prompt');
    if (prompt && !prompt.contains(e.target)) {
        removeDocumentSelectionPrompt();
    }
});


function switchToEntity(entityId) {
    // Switch to entities view and show detail
    document.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('[data-view="entities"]').classList.add('active');
    document.querySelectorAll('.view').forEach(v => v.classList.add('hidden'));
    document.getElementById('view-entities').classList.remove('hidden');
    loadEntities();
    showEntityDetail(entityId);
}


function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}


/**
 * Populate the per-document filter dropdown in the entities view.
 * Preserves the current selection if the document still exists.
 */
async function loadDocumentFilterOptions() {
    const select = document.getElementById('entity-document-filter');
    if (!select) return;
    try {
        const profileId = getActiveProfileId();
        const params = new URLSearchParams();
        if (profileId) params.set('profile_id', profileId);
        const docs = await api(`/documents?${params}`);
        const previous = select.value;
        select.innerHTML = '<option value="">All documents</option>' +
            docs.map(d => `<option value="${d.id}">${escapeHtml(d.filename)}</option>`).join('');
        if (previous && docs.some(d => d.id === previous)) {
            select.value = previous;
        }
    } catch {
        // Silent — search still works without filter
    }
}
