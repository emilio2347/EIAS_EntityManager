/* ========================================
   Corpus — read-only article context for entity curation
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
            throw new Error('Document ingestion is handled in DocumentManager.');
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
        const docs = await api('/corpus/articles');
        if (docs.length === 0) {
            container.innerHTML = '<p style="color: var(--text-muted);">No corpus articles available.</p>';
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
        const doc = await api(`/corpus/articles/${docId}/entity-context`);

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
    alert('Document deletion is handled in DocumentManager.');
}


/* ----------------------------------------------------------------------
   Corpus View — rendered text and entity focus
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
        const docs = await api('/corpus/articles');
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
    switchView('document-view');
    await loadDocumentViewOptions(docId);
}


async function loadDocumentView(docId) {
    const textEl = document.getElementById('document-rendered-text');
    if (!textEl) return;
    showStatus('document-view-status', 'Loading document...', '');
    textEl.innerHTML = '<div class="spinner"></div> Loading...';
    try {
        _currentDocumentViewDoc = await api(`/corpus/articles/${docId}/entity-context`);
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
            html += `<span class="document-entity-box ${documentEntityClass(type)}" data-start="${deco.start}" data-end="${deco.end}" data-mention-id="${escapeAttr(deco.mention.id)}" data-entity-id="${escapeAttr(deco.mention.entity_id)}" data-preferred-label="${escapeAttr(label)}" data-tooltip="${escapeAttr(entityTooltip(entity, deco.mention))}">${escapeHtml(original)}</span>`;
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
        window.setTimeout(showDocumentSelectionPrompt, 0);
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
                    <button class="btn btn-sm btn-danger" onclick="openDeleteDocumentMentionModal('${escapeAttr(anchorEl?.dataset?.mentionId || '')}')">Delete Annotation</button>
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
    prompt.innerHTML = '<button class="btn btn-sm btn-primary" onclick="openDocumentAddEntityModal()">Add Entity</button>';
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
        await api(`/corpus/articles/${_currentDocumentViewDoc.id}/entities`, {
            method: 'POST',
            body: JSON.stringify({
                label: range.text,
                start_char: range.start_char,
                end_char: range.end_char,
                entity_type: type,
            }),
        });
        closeModal();
        removeDocumentSelectionPrompt();
        await loadDocumentView(_currentDocumentViewDoc.id);
        await loadEntities?.();
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
        alert('Entity annotation edits are handled in DocumentManager.');
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


function openDeleteDocumentMentionModal(mentionId) {
    if (!_currentDocumentViewDoc) return;
    const mention = (_currentDocumentViewDoc.mentions || []).find(m => m.id === mentionId);
    if (!mention) {
        alert('No mention found for this annotation.');
        return;
    }
    openModal(`
        <h2 style="margin-bottom: 1rem;">Delete Annotation</h2>
        <p style="color: var(--text-muted); margin-bottom: 1rem;">Remove "${escapeHtml(mention.surface_form)}" from this article. The canonical entity remains.</p>
        <div style="display: flex; gap: 0.5rem;">
            <button class="btn btn-danger" onclick="deleteDocumentMention('${escapeAttr(mention.id)}')">Delete</button>
            <button class="btn" onclick="closeModal()">Cancel</button>
        </div>
    `);
}


async function deleteDocumentMention(mentionId) {
    if (!_currentDocumentViewDoc) return;
    try {
        await api(`/corpus/articles/${_currentDocumentViewDoc.id}/mentions/${mentionId}`, { method: 'DELETE' });
        closeModal();
        await loadDocumentView(_currentDocumentViewDoc.id);
        await loadEntities?.();
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


/* ----------------------------------------------------------------------
   EntityManager Metadata — article metadata, versions, PDF annotations
   ---------------------------------------------------------------------- */

let _entityMetadataArticle = null;
let _entityPdfInfo = null;
let _entityPdfAnnotations = [];
let _entityPdfMode = 'box';
let _entityPdfDrag = null;

document.getElementById('entity-metadata-article-select')?.addEventListener('change', (event) => {
    if (event.target.value) loadEntityMetadataEditor(event.target.value);
});
document.getElementById('entity-pdf-article-select')?.addEventListener('change', (event) => {
    if (event.target.value) loadEntityMetadataEditor(event.target.value);
});

document.getElementById('entity-metadata-save-btn')?.addEventListener('click', saveEntityMetadata);
document.getElementById('entity-metadata-apply-template-btn')?.addEventListener('click', applyMetadataTemplateToEmptyArticles);
document.getElementById('entity-version-upload-form')?.addEventListener('submit', uploadEntityArticleVersion);
document.getElementById('entity-pdf-annotation-form')?.addEventListener('submit', createEntityPdfAnnotation);
document.getElementById('entity-pdf-source-select')?.addEventListener('change', () => loadEntityPdfWorkspace());
document.getElementById('entity-pdf-page-number')?.addEventListener('change', scrollEntityPdfToPage);
document.getElementById('entity-pdf-zoom')?.addEventListener('change', () => loadEntityPdfWorkspace({ preservePage: true }));
document.getElementById('entity-pdf-clear-selection-btn')?.addEventListener('click', clearEntityPdfSelection);
document.getElementById('entity-pdf-annotation-type')?.addEventListener('change', updatePdfAnnotationTypeControls);
document.getElementById('entity-pdf-scroll-viewer')?.addEventListener('mouseup', capturePdfTextSelection);
document.querySelectorAll('.pdf-mode-btn').forEach(button => {
    button.addEventListener('click', () => setEntityPdfMode(button.dataset.pdfMode || 'box'));
});

async function loadEntityMetadataOptions(selectedId = '') {
    const select = document.getElementById('entity-metadata-article-select');
    if (!select) return [];
    try {
        const articles = await api('/document-manager/articles');
        const current = selectedId || select.value;
        select.innerHTML = '<option value="">Select an article</option>' +
            articles.map(article => `<option value="${article.id}">${escapeHtml(article.filename)}</option>`).join('');
        if (current && articles.some(article => article.id === current)) {
            select.value = current;
            await loadEntityMetadataEditor(current);
        }
        return articles;
    } catch (err) {
        showStatus('entity-metadata-status', `Error: ${err.message}`, 'error');
        return [];
    }
}

async function loadPdfAnnotationArticleOptions(selectedId = '') {
    const select = document.getElementById('entity-pdf-article-select');
    if (!select) return [];
    try {
        const articles = await api('/document-manager/articles');
        const current = selectedId || select.value || _entityMetadataArticle?.id || '';
        select.innerHTML = '<option value="">Select an article</option>' +
            articles.map(article => `<option value="${article.id}">${escapeHtml(article.filename)}</option>`).join('');
        if (current && articles.some(article => article.id === current)) {
            select.value = current;
            await loadEntityMetadataEditor(current);
        }
        return articles;
    } catch (err) {
        showStatus('entity-pdf-status', `Error: ${err.message}`, 'error');
        return [];
    }
}

async function loadEntityMetadataEditor(articleId) {
    if (!articleId) return;
    showStatus('entity-metadata-status', 'Loading article metadata...', '');
    try {
        _entityMetadataArticle = await api(`/document-manager/articles/${articleId}`);
        syncArticleSelectionControls(articleId);
        const editor = document.getElementById('entity-metadata-json');
        if (editor) {
            const hasMetadata = _entityMetadataArticle.has_metadata;
            const metadata = hasMetadata
                ? (_entityMetadataArticle.metadata || {})
                : (_entityMetadataArticle.metadata_template || buildFallbackMetadataTemplate(_entityMetadataArticle));
            editor.value = JSON.stringify(metadata, null, 2);
        }
        renderEntityVersionList();
        renderEntityPdfSources();
        await loadEntityPdfWorkspace();
        await loadEntityPdfAnnotations();
        updatePdfAnnotationTypeControls();
        showStatus('entity-pdf-status', `${_entityMetadataArticle.filename} PDF annotation workspace loaded.`, 'success');
        showStatus(
            'entity-metadata-status',
            _entityMetadataArticle.has_metadata
                ? `${_entityMetadataArticle.filename} loaded.`
                : `${_entityMetadataArticle.filename} has no saved metadata. Template loaded; save to persist it.`,
            _entityMetadataArticle.has_metadata ? 'success' : ''
        );
    } catch (err) {
        _entityMetadataArticle = null;
        showStatus('entity-metadata-status', `Error: ${err.message}`, 'error');
    }
}

function syncArticleSelectionControls(articleId) {
    for (const id of ['entity-metadata-article-select', 'entity-pdf-article-select']) {
        const select = document.getElementById(id);
        if (select && Array.from(select.options).some(option => option.value === articleId)) {
            select.value = articleId;
        }
    }
}

async function saveEntityMetadata() {
    if (!_entityMetadataArticle) {
        showStatus('entity-metadata-status', 'Select an article first.', 'error');
        return;
    }
    const editor = document.getElementById('entity-metadata-json');
    const merge = document.getElementById('entity-metadata-merge')?.checked ?? true;
    try {
        const data = JSON.parse(editor?.value || '{}');
        await api(`/document-manager/articles/${_entityMetadataArticle.id}/metadata`, {
            method: 'PUT',
            body: JSON.stringify({ data, merge }),
        });
        await loadEntityMetadataEditor(_entityMetadataArticle.id);
        showStatus('entity-metadata-status', 'Metadata saved.', 'success');
    } catch (err) {
        showStatus('entity-metadata-status', `Error: ${err.message}`, 'error');
    }
}

function buildFallbackMetadataTemplate(article) {
    return {
        title: article?.filename || '',
        subtitle: '',
        creators: [{ name: '', role: 'author', affiliation: '', identifier: '' }],
        publication: {
            date: article?.publication_date || '',
            venue: '',
            volume: '',
            issue: '',
            pages: '',
            publisher: '',
        },
        identifiers: {
            doi: '',
            isbn: '',
            issn: '',
            url: '',
            canonical_uri: article?.canonical_uri || '',
        },
        language: article?.language || '',
        abstract: '',
        keywords: [],
        source_files: {
            formatted_pdf: '',
            machine_readable_text: '',
        },
        rights: {
            copyright: '',
            license: '',
            access: '',
        },
        notes: '',
    };
}

async function applyMetadataTemplateToEmptyArticles() {
    showStatus('entity-metadata-status', 'Applying metadata template to articles without metadata...', '');
    try {
        const result = await api('/document-manager/metadata-template/apply-to-empty', { method: 'POST' });
        if (_entityMetadataArticle) {
            await loadEntityMetadataEditor(_entityMetadataArticle.id);
        }
        showStatus(
            'entity-metadata-status',
            `Template added to ${result.updated_count || 0} article${result.updated_count === 1 ? '' : 's'} without metadata.`,
            'success'
        );
    } catch (err) {
        showStatus('entity-metadata-status', `Error: ${err.message}`, 'error');
    }
}

async function uploadEntityArticleVersion(event) {
    event.preventDefault();
    if (!_entityMetadataArticle) {
        showStatus('entity-pdf-status', 'Select an article first.', 'error');
        return;
    }
    const fileInput = document.getElementById('entity-version-file-input');
    if (!fileInput?.files?.length) {
        showStatus('entity-metadata-status', 'Choose a version file first.', 'error');
        return;
    }
    const formData = new FormData();
    formData.append('file', fileInput.files[0]);
    const role = document.getElementById('entity-version-format-role')?.value;
    const setCurrent = document.getElementById('entity-version-set-current')?.checked;
    if (role) formData.append('format_role', role);
    formData.append('set_current', setCurrent ? 'true' : 'false');

    showStatus('entity-metadata-status', 'Uploading article version...', '');
    try {
        _entityMetadataArticle = await apiUpload(`/document-manager/articles/${_entityMetadataArticle.id}/versions/upload`, formData);
        fileInput.value = '';
        renderEntityVersionList();
        renderEntityPdfSources();
        await loadEntityPdfWorkspace();
        await loadEntityPdfAnnotations();
        showStatus('entity-metadata-status', 'Article version added.', 'success');
    } catch (err) {
        showStatus('entity-metadata-status', `Error: ${err.message}`, 'error');
    }
}

function renderEntityVersionList() {
    const container = document.getElementById('entity-version-list');
    if (!container || !_entityMetadataArticle) return;
    const textVersions = _entityMetadataArticle.text_versions || [];
    const sourceFiles = _entityMetadataArticle.source_files || [];
    container.innerHTML = `
        <div class="detail-section">
            <h3>Text Versions</h3>
            ${textVersions.map(version => `
                <div class="list-item compact-list-item">
                    <div class="list-item-main">
                        <span class="list-item-title">${escapeHtml(version.id)} ${version.is_current ? '<span class="runtime-pill ok">current</span>' : ''}</span>
                        <span class="list-item-subtitle">${escapeHtml(version.normalization_method || '')} · ${escapeHtml(version.created_at || '')}</span>
                    </div>
                    <div class="list-item-actions">
                        <button type="button" class="btn btn-sm" onclick="setEntityCurrentTextVersion('${escapeAttr(version.id)}')" ${version.is_current ? 'disabled' : ''}>Use</button>
                    </div>
                </div>
            `).join('') || '<p style="color: var(--text-muted);">No text versions.</p>'}
        </div>
        <div class="detail-section">
            <h3>Source Files</h3>
            ${sourceFiles.map(source => `
                <div class="list-item compact-list-item">
                    <div class="list-item-main">
                        <span class="list-item-title">${escapeHtml(source.original_filename || source.id)}</span>
                        <span class="list-item-subtitle">${escapeHtml(source.format_role || source.source_type || '')} · ${escapeHtml(source.mime_type || '')} · ${(source.file_size_bytes || 0).toLocaleString()} bytes</span>
                    </div>
                    <div class="list-item-actions">
                        ${isPdfSource(source) ? `<button type="button" class="btn btn-sm" onclick="selectEntityPdfSource('${escapeAttr(source.id)}')">Open PDF</button>` : ''}
                    </div>
                </div>
            `).join('') || '<p style="color: var(--text-muted);">No source files.</p>'}
        </div>
    `;
}

async function setEntityCurrentTextVersion(textVersionId) {
    if (!_entityMetadataArticle) return;
    try {
        _entityMetadataArticle = await api(`/document-manager/articles/${_entityMetadataArticle.id}/text-version`, {
            method: 'PATCH',
            body: JSON.stringify({ text_version_id: textVersionId }),
        });
        renderEntityVersionList();
        showStatus('entity-metadata-status', 'Current machine-readable text version updated.', 'success');
    } catch (err) {
        showStatus('entity-metadata-status', `Error: ${err.message}`, 'error');
    }
}

function isPdfSource(source) {
    const name = String(source.original_filename || '').toLowerCase();
    const mime = String(source.mime_type || '').toLowerCase();
    return name.endsWith('.pdf') || mime.includes('pdf') || source.format_role === 'formatted_pdf';
}

function renderEntityPdfSources() {
    const select = document.getElementById('entity-pdf-source-select');
    if (!select || !_entityMetadataArticle) return;
    const sources = (_entityMetadataArticle.source_files || []).filter(isPdfSource);
    const current = select.value;
    select.innerHTML = '<option value="">Select PDF source</option>' +
        sources.map(source => `<option value="${source.id}">${escapeHtml(source.original_filename || source.id)}</option>`).join('');
    if (current && sources.some(source => source.id === current)) {
        select.value = current;
    } else if (sources.length === 1) {
        select.value = sources[0].id;
    }
}

function selectEntityPdfSource(sourceId) {
    const select = document.getElementById('entity-pdf-source-select');
    if (select) {
        select.value = sourceId;
        loadEntityPdfWorkspace();
    }
}

function setEntityPdfMode(mode) {
    _entityPdfMode = mode === 'text' ? 'text' : 'box';
    document.querySelectorAll('.pdf-mode-btn').forEach(button => {
        button.classList.toggle('active', button.dataset.pdfMode === _entityPdfMode);
    });
    document.querySelectorAll('.pdf-page-canvas').forEach(canvas => {
        canvas.classList.toggle('text-mode', _entityPdfMode === 'text');
    });
}

function currentEntityPdfSourceId() {
    return document.getElementById('entity-pdf-source-select')?.value || '';
}

function currentEntityPdfZoom() {
    return Number(document.getElementById('entity-pdf-zoom')?.value || 1.5);
}

async function loadEntityPdfWorkspace(options = {}) {
    const stack = document.getElementById('entity-pdf-page-stack');
    const empty = document.getElementById('entity-pdf-preview-empty');
    const pageCount = document.getElementById('entity-pdf-page-count');
    const sourceId = currentEntityPdfSourceId();
    const requestedPage = Math.max(1, Number(document.getElementById('entity-pdf-page-number')?.value || 1));
    _entityPdfInfo = null;
    clearEntityPdfSelection();
    if (!stack || !empty) return;
    stack.innerHTML = '';
    if (!sourceId) {
        empty.textContent = 'Select an article and PDF source.';
        empty.classList.remove('hidden');
        if (pageCount) pageCount.textContent = 'No PDF loaded';
        return;
    }
    empty.textContent = 'Loading PDF pages...';
    empty.classList.remove('hidden');
    try {
        _entityPdfInfo = await api(`/document-manager/source-files/${sourceId}/pdf-info`);
        if (pageCount) pageCount.textContent = `${_entityPdfInfo.page_count || 0} pages`;
        renderEntityPdfPageStack(_entityPdfInfo);
        empty.classList.add('hidden');
        renderSavedPdfAnnotationOverlays();
        if (options.preservePage !== false) {
            requestAnimationFrame(() => scrollEntityPdfToPage(requestedPage));
        }
    } catch (err) {
        stack.innerHTML = '';
        empty.textContent = `Could not load PDF: ${err.message}`;
        empty.classList.remove('hidden');
        if (pageCount) pageCount.textContent = 'PDF unavailable';
    }
}

function renderEntityPdfPageStack(info) {
    const stack = document.getElementById('entity-pdf-page-stack');
    if (!stack) return;
    const sourceId = currentEntityPdfSourceId();
    const scale = currentEntityPdfZoom();
    stack.innerHTML = (info.pages || []).map(page => `
        <div class="pdf-page-shell" data-page-number="${page.page_number}">
            <div class="pdf-page-label">Page ${page.page_number}</div>
            <div class="pdf-page-canvas ${_entityPdfMode === 'text' ? 'text-mode' : ''}" data-page-number="${page.page_number}">
                <img class="pdf-preview-image" alt="Rendered PDF page ${page.page_number}" loading="lazy"
                    src="/api/document-manager/source-files/${sourceId}/pages/${page.page_number}/image?scale=${scale}&ts=${Date.now()}">
                <div class="pdf-text-layer" aria-label="Selectable PDF text layer"></div>
                <div class="pdf-annotation-layer"></div>
                <div class="pdf-interaction-layer"></div>
            </div>
        </div>
    `).join('');
    stack.querySelectorAll('.pdf-page-canvas').forEach(canvas => {
        const image = canvas.querySelector('img');
        const layer = canvas.querySelector('.pdf-interaction-layer');
        const pageNumber = Number(canvas.dataset.pageNumber || 1);
        if (image) {
            image.addEventListener('load', () => {
                canvas.style.width = `${image.naturalWidth}px`;
                canvas.style.height = `${image.naturalHeight}px`;
                loadEntityPdfTextLayer(pageNumber, canvas);
                renderSavedPdfAnnotationOverlays();
            });
            image.addEventListener('error', () => {
                canvas.innerHTML = '<div class="pdf-preview-empty">Could not render this page.</div>';
            });
        }
        layer?.addEventListener('pointerdown', startEntityPdfBoxSelection);
    });
}

async function loadEntityPdfTextLayer(pageNumber, canvas) {
    const textLayer = canvas.querySelector('.pdf-text-layer');
    if (!textLayer || !currentEntityPdfSourceId()) return;
    try {
        const pageText = await api(`/document-manager/source-files/${currentEntityPdfSourceId()}/pages/${pageNumber}/text`);
        textLayer.innerHTML = (pageText.words || []).map(word => `
            <span class="pdf-word"
                style="left:${word.x * 100}%; top:${word.y * 100}%; width:${word.width * 100}%; height:${word.height * 100}%; font-size:${Math.max(6, word.height * canvas.clientHeight * 0.9)}px"
                data-word="${escapeAttr(word.text)}">${escapeHtml(word.text)}</span>
        `).join('');
    } catch (_err) {
        textLayer.innerHTML = '';
    }
}

function normalizedBoxFromPointer(canvas, start, end) {
    const rect = canvas.getBoundingClientRect();
    const left = Math.max(0, Math.min(start.x, end.x));
    const top = Math.max(0, Math.min(start.y, end.y));
    const right = Math.min(rect.width, Math.max(start.x, end.x));
    const bottom = Math.min(rect.height, Math.max(start.y, end.y));
    return {
        x: left / rect.width,
        y: top / rect.height,
        width: Math.max(0, (right - left) / rect.width),
        height: Math.max(0, (bottom - top) / rect.height),
    };
}

function startEntityPdfBoxSelection(event) {
    if (!['box', 'text'].includes(_entityPdfMode)) return;
    const canvas = event.currentTarget.closest('.pdf-page-canvas');
    if (!canvas) return;
    event.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const start = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    const dragBox = document.createElement('div');
    dragBox.className = 'pdf-drag-selection';
    canvas.appendChild(dragBox);
    _entityPdfDrag = { canvas, start, current: start, dragBox, pointerId: event.pointerId, layer: event.currentTarget };
    event.currentTarget.setPointerCapture?.(event.pointerId);
    document.addEventListener('pointermove', moveEntityPdfBoxSelection, true);
    document.addEventListener('pointerup', finishEntityPdfBoxSelection, { once: true, capture: true });
    document.addEventListener('pointercancel', cancelEntityPdfBoxSelection, { once: true, capture: true });
}

function moveEntityPdfBoxSelection(event) {
    if (!_entityPdfDrag) return;
    const rect = _entityPdfDrag.canvas.getBoundingClientRect();
    const current = { x: event.clientX - rect.left, y: event.clientY - rect.top };
    _entityPdfDrag.current = current;
    const box = normalizedBoxFromPointer(_entityPdfDrag.canvas, _entityPdfDrag.start, current);
    positionPdfBox(_entityPdfDrag.dragBox, box);
}

function finishEntityPdfBoxSelection(event) {
    if (!_entityPdfDrag) return;
    const layer = _entityPdfDrag.layer;
    layer?.releasePointerCapture?.(_entityPdfDrag.pointerId);
    document.removeEventListener('pointermove', moveEntityPdfBoxSelection, true);
    const rect = _entityPdfDrag.canvas.getBoundingClientRect();
    const end = event?.clientX
        ? { x: event.clientX - rect.left, y: event.clientY - rect.top }
        : _entityPdfDrag.current;
    const box = normalizedBoxFromPointer(_entityPdfDrag.canvas, _entityPdfDrag.start, end);
    const mode = _entityPdfMode;
    const selectedText = mode === 'text' ? selectedTextFromPdfWords(_entityPdfDrag.canvas, box) : '';
    _entityPdfDrag.dragBox.remove();
    _entityPdfDrag = null;
    if (box.width < 0.003 || box.height < 0.003) return;
    applyEntityPdfSelection(Number(layer.closest('.pdf-page-canvas')?.dataset.pageNumber || 1), box, selectedText);
    if (mode === 'text' && !selectedText) {
        showStatus('entity-pdf-status', 'No extracted PDF text was found inside that region.', '');
    }
}

function cancelEntityPdfBoxSelection() {
    if (!_entityPdfDrag) return;
    document.removeEventListener('pointermove', moveEntityPdfBoxSelection, true);
    _entityPdfDrag.dragBox.remove();
    _entityPdfDrag = null;
}

function selectedTextFromPdfWords(canvas, box) {
    const pageRect = canvas.getBoundingClientRect();
    const selectedWords = Array.from(canvas.querySelectorAll('.pdf-word')).filter(word => {
        const rect = word.getBoundingClientRect();
        const wordBox = {
            x: (rect.left - pageRect.left) / pageRect.width,
            y: (rect.top - pageRect.top) / pageRect.height,
            width: rect.width / pageRect.width,
            height: rect.height / pageRect.height,
        };
        return wordBox.x < box.x + box.width
            && wordBox.x + wordBox.width > box.x
            && wordBox.y < box.y + box.height
            && wordBox.y + wordBox.height > box.y;
    });
    selectedWords.sort((a, b) => {
        const ar = a.getBoundingClientRect();
        const br = b.getBoundingClientRect();
        if (Math.abs(ar.top - br.top) > 4) return ar.top - br.top;
        return ar.left - br.left;
    });
    return selectedWords.map(word => word.textContent.trim()).filter(Boolean).join(' ');
}

function capturePdfTextSelection() {
    if (_entityPdfMode !== 'text') return;
    const selection = window.getSelection();
    if (!selection || selection.isCollapsed || !selection.toString().trim()) return;
    const range = selection.getRangeAt(0);
    const anchor = range.commonAncestorContainer.nodeType === Node.ELEMENT_NODE
        ? range.commonAncestorContainer
        : range.commonAncestorContainer.parentElement;
    const canvas = anchor?.closest?.('.pdf-page-canvas');
    if (!canvas || !document.getElementById('entity-pdf-scroll-viewer')?.contains(canvas)) return;
    const rangeRect = range.getBoundingClientRect();
    const pageRect = canvas.getBoundingClientRect();
    const box = {
        x: Math.max(0, (rangeRect.left - pageRect.left) / pageRect.width),
        y: Math.max(0, (rangeRect.top - pageRect.top) / pageRect.height),
        width: Math.min(1, rangeRect.width / pageRect.width),
        height: Math.min(1, rangeRect.height / pageRect.height),
    };
    applyEntityPdfSelection(Number(canvas.dataset.pageNumber || 1), box, selection.toString().trim());
}

function applyEntityPdfSelection(pageNumber, box, selectedText) {
    document.getElementById('entity-pdf-selected-page').value = pageNumber;
    document.getElementById('entity-pdf-page-number').value = pageNumber;
    document.getElementById('entity-pdf-selected-text').value = selectedText || '';
    setPdfBboxInputs(box);
    renderTemporaryPdfSelection(pageNumber, box);
}

function setPdfBboxInputs(box) {
    for (const [key, id] of Object.entries({
        x: 'entity-pdf-bbox-x',
        y: 'entity-pdf-bbox-y',
        width: 'entity-pdf-bbox-width',
        height: 'entity-pdf-bbox-height',
    })) {
        const input = document.getElementById(id);
        if (input) input.value = Number(box[key] || 0).toFixed(3);
    }
}

function readPdfBboxInputs() {
    const bbox = {};
    for (const [key, id] of Object.entries({
        x: 'entity-pdf-bbox-x',
        y: 'entity-pdf-bbox-y',
        width: 'entity-pdf-bbox-width',
        height: 'entity-pdf-bbox-height',
    })) {
        const raw = document.getElementById(id)?.value;
        if (raw !== '') bbox[key] = Number(raw);
    }
    return bbox;
}

function renderTemporaryPdfSelection(pageNumber, box) {
    document.querySelectorAll('.pdf-temp-selection').forEach(el => el.remove());
    const canvas = document.querySelector(`.pdf-page-canvas[data-page-number="${pageNumber}"]`);
    const layer = canvas?.querySelector('.pdf-annotation-layer');
    if (!layer) return;
    const el = document.createElement('div');
    el.className = 'pdf-temp-selection';
    positionPdfBox(el, box);
    layer.appendChild(el);
}

function clearEntityPdfSelection() {
    document.querySelectorAll('.pdf-temp-selection, .pdf-drag-selection').forEach(el => el.remove());
    for (const id of ['entity-pdf-selected-text', 'entity-pdf-bbox-x', 'entity-pdf-bbox-y', 'entity-pdf-bbox-width', 'entity-pdf-bbox-height']) {
        const field = document.getElementById(id);
        if (field) field.value = '';
    }
    const selectedPage = document.getElementById('entity-pdf-selected-page');
    if (selectedPage) selectedPage.value = document.getElementById('entity-pdf-page-number')?.value || 1;
}

function positionPdfBox(el, box) {
    el.style.left = `${box.x * 100}%`;
    el.style.top = `${box.y * 100}%`;
    el.style.width = `${box.width * 100}%`;
    el.style.height = `${box.height * 100}%`;
}

function pdfBoxFromStored(bbox, canvas) {
    const x = Number(bbox?.x);
    const y = Number(bbox?.y);
    const width = Number(bbox?.width);
    const height = Number(bbox?.height);
    if ([x, y, width, height].some(value => Number.isNaN(value))) return null;
    if (x <= 1 && y <= 1 && width <= 1 && height <= 1) {
        return { x, y, width, height };
    }
    return {
        x: x / Math.max(1, canvas.clientWidth),
        y: y / Math.max(1, canvas.clientHeight),
        width: width / Math.max(1, canvas.clientWidth),
        height: height / Math.max(1, canvas.clientHeight),
    };
}

function renderSavedPdfAnnotationOverlays() {
    document.querySelectorAll('.pdf-saved-annotation-box').forEach(el => el.remove());
    for (const annotation of _entityPdfAnnotations) {
        const body = annotation.body || {};
        const pageNumber = Number(body.page_number || 1);
        const canvas = document.querySelector(`.pdf-page-canvas[data-page-number="${pageNumber}"]`);
        const layer = canvas?.querySelector('.pdf-annotation-layer');
        if (!canvas || !layer) continue;
        const box = pdfBoxFromStored(body.bbox || {}, canvas);
        if (!box || box.width <= 0 || box.height <= 0) continue;
        const el = document.createElement('div');
        el.className = `pdf-saved-annotation-box ${pdfAnnotationCategory(annotation.annotation_type)}`;
        el.title = body.label || annotation.annotation_type;
        positionPdfBox(el, box);
        layer.appendChild(el);
    }
}

function pdfAnnotationCategory(type) {
    if (type === 'pdf_text_hierarchy' || type === 'pdf_table_of_contents') return 'structure';
    if (type === 'pdf_footnote' || type === 'pdf_page_number') return 'paratext';
    return 'content';
}

function scrollEntityPdfToPage(pageOverride) {
    const pageNumber = Number(pageOverride?.target?.value || pageOverride || document.getElementById('entity-pdf-page-number')?.value || 1);
    const shell = document.querySelector(`.pdf-page-shell[data-page-number="${pageNumber}"]`);
    shell?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    const selectedPage = document.getElementById('entity-pdf-selected-page');
    if (selectedPage && !selectedPage.value) selectedPage.value = pageNumber;
}

function focusEntityPdfAnnotation(annotationId) {
    const annotation = _entityPdfAnnotations.find(item => item.id === annotationId);
    if (!annotation) return;
    const pageNumber = Number(annotation.body?.page_number || 1);
    document.getElementById('entity-pdf-page-number').value = pageNumber;
    scrollEntityPdfToPage(pageNumber);
    const box = annotation.body?.bbox;
    if (box) {
        const canvas = document.querySelector(`.pdf-page-canvas[data-page-number="${pageNumber}"]`);
        const normalized = canvas ? pdfBoxFromStored(box, canvas) : null;
        if (normalized) renderTemporaryPdfSelection(pageNumber, normalized);
    }
}

function updatePdfAnnotationTypeControls() {
    const type = document.getElementById('entity-pdf-annotation-type')?.value;
    const hierarchyField = document.getElementById('entity-pdf-hierarchy-field');
    const hierarchySelect = document.getElementById('entity-pdf-hierarchy-level');
    if (hierarchyField) hierarchyField.classList.toggle('hidden', type !== 'text_hierarchy');
    if (type === 'text_hierarchy' && hierarchySelect && !hierarchySelect.value) {
        hierarchySelect.value = 'body_text';
    }
}

async function createEntityPdfAnnotation(event) {
    event.preventDefault();
    if (!_entityMetadataArticle) {
        showStatus('entity-metadata-status', 'Select an article first.', 'error');
        return;
    }
    const sourceId = document.getElementById('entity-pdf-source-select')?.value;
    if (!sourceId) {
        showStatus('entity-pdf-status', 'Select a PDF source first.', 'error');
        return;
    }
    const annotationType = document.getElementById('entity-pdf-annotation-type')?.value || 'figure_graphic';
    const selectedPage = Number(document.getElementById('entity-pdf-selected-page')?.value || document.getElementById('entity-pdf-page-number')?.value || 1);
    const payload = {
        source_file_id: sourceId,
        annotation_type: annotationType,
        page_number: selectedPage,
        hierarchy_level: annotationType === 'text_hierarchy' ? (document.getElementById('entity-pdf-hierarchy-level')?.value || 'body_text') : null,
        label: document.getElementById('entity-pdf-label')?.value || '',
        description: document.getElementById('entity-pdf-description')?.value || '',
        selected_text: document.getElementById('entity-pdf-selected-text')?.value || '',
        bbox: readPdfBboxInputs(),
    };
    try {
        await api(`/document-manager/articles/${_entityMetadataArticle.id}/pdf-annotations`, {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        document.getElementById('entity-pdf-label').value = '';
        document.getElementById('entity-pdf-description').value = '';
        clearEntityPdfSelection();
        await loadEntityPdfAnnotations();
        showStatus('entity-pdf-status', 'PDF annotation added.', 'success');
    } catch (err) {
        showStatus('entity-pdf-status', `Error: ${err.message}`, 'error');
    }
}

async function loadEntityPdfAnnotations() {
    const container = document.getElementById('entity-pdf-annotation-list');
    if (!container || !_entityMetadataArticle) return;
    try {
        const result = await api(`/document-manager/articles/${_entityMetadataArticle.id}/pdf-annotations`);
        _entityPdfAnnotations = result.annotations || [];
        renderSavedPdfAnnotationOverlays();
        container.innerHTML = _entityPdfAnnotations.map(annotation => {
            const body = annotation.body || {};
            const label = body.label || body.selected_text || body.hierarchy_level || annotation.annotation_type;
            const description = body.description || body.selected_text || '';
            return `
                <div class="list-item compact-list-item" onclick="focusEntityPdfAnnotation('${escapeAttr(annotation.id)}')">
                    <div class="list-item-main">
                        <span class="list-item-title">${escapeHtml(label)}</span>
                        <span class="list-item-subtitle">${escapeHtml(annotation.annotation_type)} · page ${body.page_number || '?'}${description ? ` · ${escapeHtml(description)}` : ''}</span>
                    </div>
                </div>
            `;
        }).join('') || '<p style="color: var(--text-muted);">No PDF annotations yet.</p>';
    } catch (err) {
        container.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}


function switchToEntity(entityId) {
    // Switch to entities view and show detail
    switchView('entities');
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
        const docs = await api('/corpus/articles');
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
