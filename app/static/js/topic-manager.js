/* ========================================
   TopicManager — Keywords, FAST review, schemas
   ======================================== */

let _tmArticles = [];
let _tmKeywords = [];
let _tmSelectedKeyword = null;
let _tmRendererArticle = null;
let _tmRendererKeywords = [];
let _tmSelectionRange = null;

async function loadTopicArticles() {
    _tmArticles = await api('/document-manager/articles');
    return _tmArticles;
}

async function loadTopicArticleOptions(selectedId = '') {
    const select = document.getElementById('tm-article-select');
    if (!select) return;
    const articles = await loadTopicArticles();
    const current = selectedId || select.value;
    select.innerHTML = '<option value="">Select an article</option>' +
        articles.map(article => `<option value="${article.id}">${escapeHtml(article.filename)}</option>`).join('');
    if (current && articles.some(article => article.id === current)) select.value = current;
    if (select.value) await loadTopicKeywords(select.value);
}

async function loadTopicReviewOptions(selectedId = '') {
    const select = document.getElementById('tm-review-article-select');
    if (!select) return;
    const articles = _tmArticles.length ? _tmArticles : await loadTopicArticles();
    const current = selectedId || select.value;
    select.innerHTML = '<option value="">Select an article</option>' +
        articles.map(article => `<option value="${article.id}">${escapeHtml(article.filename)}</option>`).join('');
    if (current && articles.some(article => article.id === current)) select.value = current;
    if (select.value) await loadTopicReviewKeywords(select.value);
}

document.getElementById('tm-article-select')?.addEventListener('change', (event) => {
    if (event.target.value) loadTopicKeywords(event.target.value);
});

document.getElementById('tm-review-article-select')?.addEventListener('change', (event) => {
    if (event.target.value) loadTopicReviewKeywords(event.target.value);
});

document.getElementById('tm-renderer-article-select')?.addEventListener('change', (event) => {
    if (event.target.value) loadTopicRenderer(event.target.value);
});

document.getElementById('tm-extract-keywords-btn')?.addEventListener('click', async () => {
    const articleId = document.getElementById('tm-article-select')?.value;
    if (!articleId) {
        showStatus('tm-topic-status', 'Select an article first.', 'error');
        return;
    }
    showStatus('tm-topic-status', 'Extracting keywords...', '');
    try {
        await api(`/topic-manager/articles/${articleId}/keywords/extract`, {
            method: 'POST',
        });
        await loadTopicKeywords(articleId);
        showStatus('tm-topic-status', 'Keywords extracted.', 'success');
    } catch (err) {
        showStatus('tm-topic-status', `Error: ${err.message}`, 'error');
    }
});

document.getElementById('tm-clear-generated-keywords-btn')?.addEventListener('click', () => {
    const articleId = document.getElementById('tm-article-select')?.value;
    if (!articleId) {
        showStatus('tm-topic-status', 'Select an article first.', 'error');
        return;
    }
    openModal(`
        <h2 style="margin-bottom: 1rem;">Clear Generated Keywords</h2>
        <p style="color: var(--text-muted); margin-bottom: 1rem;">Delete machine-extracted keywords for this article. Manual key terms stay in place.</p>
        <div style="display: flex; gap: 0.5rem;">
            <button class="btn btn-danger" onclick="clearGeneratedKeywordsForArticle('${escapeAttr(articleId)}')">Clear Generated</button>
            <button class="btn" onclick="closeModal()">Cancel</button>
        </div>
    `);
});

async function clearGeneratedKeywordsForArticle(articleId) {
    showStatus('tm-topic-status', 'Clearing generated keywords...', '');
    try {
        const result = await api(`/topic-manager/articles/${articleId}/keywords/generated`, { method: 'DELETE' });
        closeModal();
        await loadTopicKeywords(articleId);
        if (_tmRendererArticle?.id === articleId) {
            await loadTopicRenderer(articleId);
        }
        showStatus(
            'tm-topic-status',
            `Deleted ${result.deleted_keywords} generated keyword${result.deleted_keywords === 1 ? '' : 's'}; kept ${result.preserved_manual_keywords} manual.`,
            'success'
        );
    } catch (err) {
        showStatus('tm-topic-status', `Error: ${err.message}`, 'error');
    }
}

async function loadTopicKeywords(articleId) {
    const container = document.getElementById('tm-keyword-list');
    if (!container) return;
    container.innerHTML = '<div class="spinner"></div> Loading...';
    try {
        const data = await api(`/topic-manager/articles/${articleId}/keywords`);
        _tmKeywords = data.keywords || [];
        renderTopicKeywords(container, _tmKeywords, { review: false });
    } catch (err) {
        container.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}

async function loadTopicReviewKeywords(articleId) {
    const container = document.getElementById('tm-review-keywords');
    if (!container) return;
    container.innerHTML = '<div class="spinner"></div> Loading...';
    try {
        const data = await api(`/topic-manager/articles/${articleId}/keywords`);
        _tmKeywords = data.keywords || [];
        renderTopicKeywords(container, _tmKeywords, { review: true });
    } catch (err) {
        container.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}

async function loadTopicRendererOptions(selectedId = '') {
    const select = document.getElementById('tm-renderer-article-select');
    if (!select) return;
    const articles = _tmArticles.length ? _tmArticles : await loadTopicArticles();
    const current = selectedId || select.value;
    select.innerHTML = '<option value="">Select an article</option>' +
        articles.map(article => `<option value="${article.id}">${escapeHtml(article.filename)}</option>`).join('');
    if (current && articles.some(article => article.id === current)) select.value = current;
    if (select.value) await loadTopicRenderer(select.value);
}

async function loadTopicRenderer(articleId) {
    const textEl = document.getElementById('tm-rendered-text');
    if (!textEl) return;
    showStatus('tm-renderer-status', 'Loading article...', '');
    textEl.innerHTML = '<div class="spinner"></div> Loading...';
    try {
        _tmRendererArticle = await api(`/document-manager/articles/${articleId}`);
        const data = await api(`/topic-manager/articles/${articleId}/keywords`);
        _tmRendererKeywords = data.keywords || [];
        textEl.innerHTML = renderTopicRendererText(_tmRendererArticle.content_text || '', _tmRendererKeywords);
        bindTopicRendererInteractions();
        showStatus('tm-renderer-status', `${_tmRendererArticle.filename} · ${_tmRendererKeywords.length} key terms`, 'success');
    } catch (err) {
        textEl.innerHTML = '';
        showStatus('tm-renderer-status', `Error: ${err.message}`, 'error');
    }
}

function renderTopicRendererText(text, keywords) {
    const decorations = [];
    const occupied = [];
    for (const keyword of [...keywords].sort((a, b) => (a.start_char ?? 0) - (b.start_char ?? 0))) {
        if (keyword.start_char === null || keyword.end_char === null) continue;
        const trimmed = tmTrimRange(text, keyword.start_char, keyword.end_char);
        if (!trimmed || tmRangeOverlapsAny(trimmed.start, trimmed.end, occupied)) continue;
        occupied.push([trimmed.start, trimmed.end]);
        decorations.push({ keyword, start: trimmed.start, end: trimmed.end });
    }
    let cursor = 0;
    let html = '';
    for (const deco of decorations) {
        if (deco.start > cursor) html += tmTextSpan(text.slice(cursor, deco.start), cursor);
        html += `<span class="topic-keyterm-box" data-start="${deco.start}" data-end="${deco.end}" data-keyword-id="${escapeAttr(deco.keyword.id)}">${escapeHtml(text.slice(deco.start, deco.end))}</span>`;
        cursor = deco.end;
    }
    if (cursor < text.length) html += tmTextSpan(text.slice(cursor), cursor);
    return html || '<p style="color: var(--text-muted);">This article has no text.</p>';
}

function bindTopicRendererInteractions() {
    const textEl = document.getElementById('tm-rendered-text');
    if (!textEl) return;
    textEl.querySelectorAll('.topic-keyterm-box').forEach(box => {
        box.addEventListener('click', (event) => {
            event.stopPropagation();
            showTopicKeywordFocus(box.dataset.keywordId, box);
        });
    });
    textEl.addEventListener('mouseup', () => window.setTimeout(showTopicSelectionPrompt, 0));
}

function showTopicSelectionPrompt() {
    const container = document.getElementById('tm-rendered-text');
    const selection = window.getSelection();
    if (!container || !selection || selection.isCollapsed || !container.contains(selection.anchorNode)) return;
    const range = tmSelectionCharRange(selection, container);
    if (!range) return;
    _tmSelectionRange = range;
    removeTopicSelectionPrompt();
    const rect = selection.getRangeAt(0).getBoundingClientRect();
    const prompt = document.createElement('div');
    prompt.id = 'topic-selection-prompt';
    prompt.className = 'document-selection-prompt';
    prompt.style.left = `${Math.min(window.innerWidth - 170, Math.max(12, rect.left + window.scrollX))}px`;
    prompt.style.top = `${rect.bottom + window.scrollY + 8}px`;
    prompt.innerHTML = '<button class="btn btn-sm btn-primary" onclick="addKeywordFromTopicSelection()">Add Key Term</button>';
    document.body.appendChild(prompt);
}

function removeTopicSelectionPrompt() {
    document.getElementById('topic-selection-prompt')?.remove();
}

async function addKeywordFromTopicSelection() {
    if (!_tmRendererArticle || !_tmSelectionRange) return;
    try {
        await api(`/topic-manager/articles/${_tmRendererArticle.id}/keywords/manual`, {
            method: 'POST',
            body: JSON.stringify({
                surface_form: _tmSelectionRange.text,
                start_char: _tmSelectionRange.start_char,
                end_char: _tmSelectionRange.end_char,
            }),
        });
        removeTopicSelectionPrompt();
        window.getSelection()?.removeAllRanges();
        await loadTopicRenderer(_tmRendererArticle.id);
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

function showTopicKeywordFocus(keywordId, anchorEl = null) {
    const keyword = _tmRendererKeywords.find(item => item.id === keywordId);
    const focus = document.getElementById('tm-keyterm-focus');
    const title = document.getElementById('tm-keyterm-focus-title');
    const content = document.getElementById('tm-keyterm-focus-content');
    if (!keyword || !focus || !title || !content) return;
    focus.classList.remove('hidden');
    title.textContent = keyword.surface_form;
    content.innerHTML = `
        <div class="detail-section">
            <h3>Info</h3>
            <div class="detail-row"><span class="detail-label">Method</span><span class="detail-value">${escapeHtml(keyword.extraction_method || '')}</span></div>
            <div class="detail-row"><span class="detail-label">Review</span><span class="detail-value">${escapeHtml(keyword.review_status || '')}</span></div>
            <div class="detail-row"><span class="detail-label">Range</span><span class="detail-value">${keyword.start_char}-${keyword.end_char}</span></div>
        </div>
        <button class="btn btn-sm btn-danger" onclick="openDeleteTopicKeywordModal('${escapeAttr(keyword.id)}')">Delete Annotation</button>
    `;
    positionTopicFocusPanel(focus, anchorEl);
}

function positionTopicFocusPanel(focusEl, anchorEl) {
    if (!focusEl || !anchorEl) return;
    focusEl.classList.add('anchored-focus-panel');
    const container = document.getElementById('view-tm-keyterm-renderer');
    const containerRect = container?.getBoundingClientRect();
    const anchorRect = anchorEl.getBoundingClientRect();
    if (containerRect && window.matchMedia('(min-width: 900px)').matches) {
        focusEl.style.alignSelf = 'start';
        focusEl.style.marginTop = `${Math.max(0, anchorRect.top - containerRect.top)}px`;
        return;
    }
    focusEl.style.alignSelf = '';
    focusEl.style.marginTop = '1rem';
}

function openDeleteTopicKeywordModal(keywordId) {
    const keyword = _tmRendererKeywords.find(item => item.id === keywordId);
    if (!keyword) return;
    openModal(`
        <h2 style="margin-bottom: 1rem;">Delete Key Term</h2>
        <p style="color: var(--text-muted); margin-bottom: 1rem;">Remove "${escapeHtml(keyword.surface_form)}" from this article. FAST subject cache remains.</p>
        <div style="display: flex; gap: 0.5rem;">
            <button class="btn btn-danger" onclick="deleteTopicKeyword('${escapeAttr(keyword.id)}')">Delete</button>
            <button class="btn" onclick="closeModal()">Cancel</button>
        </div>
    `);
}

async function deleteTopicKeyword(keywordId) {
    if (!_tmRendererArticle) return;
    try {
        await api(`/topic-manager/keywords/${keywordId}`, { method: 'DELETE' });
        closeModal();
        await loadTopicRenderer(_tmRendererArticle.id);
        await loadTopicKeywords(_tmRendererArticle.id);
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

function tmTrimRange(text, start, end) {
    let nextStart = Math.max(0, start);
    let nextEnd = Math.min(text.length, end);
    while (nextStart < nextEnd && /\s/.test(text[nextStart])) nextStart += 1;
    while (nextEnd > nextStart && /\s/.test(text[nextEnd - 1])) nextEnd -= 1;
    if (nextEnd <= nextStart) return null;
    return { start: nextStart, end: nextEnd };
}

function tmTextSpan(text, start) {
    return `<span data-start="${start}" data-end="${start + text.length}">${escapeHtml(text)}</span>`;
}

function tmRangeOverlapsAny(start, end, ranges) {
    return ranges.some(([a, b]) => start < b && end > a);
}

function tmSelectionCharRange(selection, container) {
    const range = selection.getRangeAt(0);
    const start = tmCharOffsetFromNode(range.startContainer, range.startOffset, container);
    const end = tmCharOffsetFromNode(range.endContainer, range.endOffset, container);
    if (start === null || end === null || start === end) return null;
    return {
        start_char: Math.min(start, end),
        end_char: Math.max(start, end),
        text: selection.toString().trim(),
    };
}

function tmCharOffsetFromNode(node, offset, container) {
    const element = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
    const carrier = element?.closest?.('[data-start][data-end]');
    if (!carrier || !container.contains(carrier)) return null;
    const start = parseInt(carrier.dataset.start, 10);
    const end = parseInt(carrier.dataset.end, 10);
    const textLength = node.textContent?.length || 1;
    const ratio = Math.min(1, Math.max(0, offset / textLength));
    return Math.round(start + ((end - start) * ratio));
}

document.addEventListener('mousedown', (event) => {
    const prompt = document.getElementById('topic-selection-prompt');
    if (prompt && !prompt.contains(event.target)) removeTopicSelectionPrompt();
});

function renderTopicKeywords(container, keywords, options = {}) {
    if (!keywords.length) {
        container.innerHTML = '<p style="color: var(--text-muted);">No keywords yet. Run extraction for this article.</p>';
        return;
    }
    container.innerHTML = keywords.map(keyword => {
        const assignment = keyword.assignment?.fast_subject?.authorized_heading;
        return `
            <div class="list-item" onclick="${options.review ? `openFastReview('${keyword.id}')` : ''}">
                <div class="list-item-main">
                    <span class="list-item-title">${escapeHtml(keyword.surface_form)}</span>
                    <span class="list-item-subtitle">
                        score ${(keyword.score || 0).toFixed(2)} · ${escapeHtml(keyword.extraction_method || '')}
                        ${assignment ? ` · FAST: ${escapeHtml(assignment)}` : ' · unassigned'}
                    </span>
                </div>
                <div class="list-item-actions">
                    ${options.review ? `<button class="btn btn-sm" onclick="event.stopPropagation(); openFastReview('${keyword.id}')">Review</button>` : ''}
                </div>
            </div>
        `;
    }).join('');
}

function openFastReview(keywordId) {
    _tmSelectedKeyword = _tmKeywords.find(keyword => keyword.id === keywordId);
    renderFastReviewDetail();
}

function renderFastReviewDetail() {
    const detail = document.getElementById('tm-fast-review-detail');
    if (!detail || !_tmSelectedKeyword) return;
    const keyword = _tmSelectedKeyword;
    detail.innerHTML = `
        <div class="detail-section">
            <h3>${escapeHtml(keyword.surface_form)}</h3>
            <p class="settings-summary">${escapeHtml(keyword.context_snippet || '')}</p>
        </div>
        <div class="search-bar">
            <input type="text" id="tm-fast-query" value="${escapeAttr(keyword.surface_form)}" placeholder="FAST query">
            <select id="tm-fast-facet">
                <option value="all">All facets</option>
                <option value="topical">Topical</option>
                <option value="geographic">Geographic</option>
                <option value="personal">Personal</option>
                <option value="corporate">Corporate</option>
                <option value="event">Event</option>
                <option value="form">Form/Genre</option>
            </select>
            <button class="btn btn-primary" onclick="suggestFastCandidates()">Suggest</button>
            <button class="btn btn-danger" onclick="rejectCurrentKeyword()">Reject Keyword</button>
        </div>
        <div id="tm-fast-candidates" class="item-list">
            ${renderFastCandidates(keyword.candidates || [])}
        </div>
    `;
}

function renderFastCandidates(candidates) {
    if (!candidates.length) {
        return '<p style="color: var(--text-muted);">No candidates yet. Type a query and suggest FAST concepts.</p>';
    }
    return candidates.map(candidate => {
        const subject = candidate.fast_subject || {};
        return `
            <div class="candidate-card">
                <div class="candidate-source">FAST ${escapeHtml(subject.fast_id || '')} · ${escapeHtml(subject.facet || '')} · score ${((candidate.combined_score || 0) * 100).toFixed(0)}</div>
                <div class="candidate-label">${escapeHtml(subject.authorized_heading || '')}</div>
                <div class="candidate-desc">${escapeHtml(subject.uri || '')}</div>
                <div style="margin-top: 0.5rem;">
                    <button class="btn btn-sm btn-primary" onclick="acceptFastCandidate('${candidate.id}')">Accept</button>
                    <button class="btn btn-sm btn-danger" onclick="rejectFastCandidate('${candidate.id}')">Reject</button>
                </div>
            </div>
        `;
    }).join('');
}

async function suggestFastCandidates() {
    if (!_tmSelectedKeyword) return;
    const query = document.getElementById('tm-fast-query')?.value.trim();
    const facet = document.getElementById('tm-fast-facet')?.value || 'all';
    const container = document.getElementById('tm-fast-candidates');
    if (container) container.innerHTML = '<div class="spinner"></div> Searching FAST...';
    try {
        const data = await api(`/topic-manager/keywords/${_tmSelectedKeyword.id}/fast/suggest`, {
            method: 'POST',
            body: JSON.stringify({ query, facet, rows: 10 }),
        });
        _tmSelectedKeyword.candidates = data.candidates || [];
        if (container) container.innerHTML = renderFastCandidates(_tmSelectedKeyword.candidates);
    } catch (err) {
        if (container) container.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}

async function acceptFastCandidate(candidateId) {
    if (!_tmSelectedKeyword) return;
    try {
        await api(`/topic-manager/keywords/${_tmSelectedKeyword.id}/fast-assignment`, {
            method: 'PATCH',
            body: JSON.stringify({
                status: 'accepted',
                candidate_id: candidateId,
                query_text: document.getElementById('tm-fast-query')?.value.trim() || _tmSelectedKeyword.surface_form,
            }),
        });
        await reloadCurrentTopicReview();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

async function rejectFastCandidate(candidateId) {
    if (!_tmSelectedKeyword) return;
    try {
        await api(`/topic-manager/keywords/${_tmSelectedKeyword.id}/fast-assignment`, {
            method: 'PATCH',
            body: JSON.stringify({ status: 'rejected', candidate_id: candidateId }),
        });
        await reloadCurrentTopicReview();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

async function rejectCurrentKeyword() {
    if (!_tmSelectedKeyword) return;
    try {
        await api(`/topic-manager/keywords/${_tmSelectedKeyword.id}/fast-assignment`, {
            method: 'PATCH',
            body: JSON.stringify({ status: 'rejected', note: 'Rejected in FAST review queue' }),
        });
        await reloadCurrentTopicReview();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}

async function reloadCurrentTopicReview() {
    const articleId = document.getElementById('tm-review-article-select')?.value;
    if (!articleId) return;
    const selectedId = _tmSelectedKeyword?.id;
    await loadTopicReviewKeywords(articleId);
    if (selectedId) {
        _tmSelectedKeyword = _tmKeywords.find(keyword => keyword.id === selectedId) || null;
        renderFastReviewDetail();
    }
}

document.getElementById('tm-schema-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const label = document.getElementById('tm-schema-label')?.value.trim();
    const schemaType = document.getElementById('tm-schema-type')?.value || 'topic';
    if (!label) return;
    try {
        await api('/topic-manager/schemas', {
            method: 'POST',
            body: JSON.stringify({ label, schema_type: schemaType }),
        });
        document.getElementById('tm-schema-label').value = '';
        showStatus('tm-schema-status', 'Schema created.', 'success');
        await loadTopicSchemas();
    } catch (err) {
        showStatus('tm-schema-status', `Error: ${err.message}`, 'error');
    }
});

async function loadTopicSchemas() {
    const container = document.getElementById('tm-schema-list');
    if (!container) return;
    try {
        const schemas = await api('/topic-manager/schemas');
        if (!schemas.length) {
            container.innerHTML = '<p style="color: var(--text-muted);">No schemas yet.</p>';
            return;
        }
        container.innerHTML = schemas.map(schema => `
            <div class="list-item">
                <div class="list-item-main">
                    <span class="list-item-title">${escapeHtml(schema.label)}</span>
                    <span class="list-item-subtitle">${escapeHtml(schema.schema_type)} · ${(schema.members || []).length} FAST concept${(schema.members || []).length === 1 ? '' : 's'}</span>
                </div>
            </div>
        `).join('');
    } catch (err) {
        container.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}
