/* ========================================
   DocumentManager — Ingestion, metadata, renderer, annotations
   ======================================== */

let _dmArticles = [];

document.getElementById('document-manager-upload-form')?.addEventListener('submit', async (event) => {
    event.preventDefault();
    const fileInput = document.getElementById('dm-file-input');
    if (!fileInput?.files?.length) return;

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    const language = document.getElementById('dm-language-input')?.value.trim();
    const publicationDate = document.getElementById('dm-publication-date-input')?.value.trim();
    const canonicalUri = document.getElementById('dm-canonical-uri-input')?.value.trim();
    const metadata = document.getElementById('dm-metadata-input')?.value.trim();
    if (language) formData.append('language', language);
    if (publicationDate) formData.append('publication_date', publicationDate);
    if (canonicalUri) formData.append('canonical_uri', canonicalUri);
    if (metadata) formData.append('metadata_json', metadata);

    showStatus('dm-upload-status', 'Uploading article...', '');
    try {
        const article = await apiUpload('/document-manager/articles/upload', formData);
        showStatus('dm-upload-status', `Uploaded ${article.filename}. NLP pipelines are pending until run from their app pages.`, 'success');
        fileInput.value = '';
        await loadDocumentManagerArticles();
        await loadDocumentManagerArticleOptions('dm-renderer-select', article.id);
    } catch (err) {
        showStatus('dm-upload-status', `Error: ${err.message}`, 'error');
    }
});

async function loadDocumentManagerArticles() {
    const container = document.getElementById('dm-article-list');
    try {
        _dmArticles = await api('/document-manager/articles');
        if (container) renderDocumentManagerArticles(container, _dmArticles);
        return _dmArticles;
    } catch (err) {
        if (container) container.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
        return [];
    }
}

function renderDocumentManagerArticles(container, articles) {
    if (!articles.length) {
        container.innerHTML = '<p style="color: var(--text-muted);">No articles have been ingested.</p>';
        return;
    }
    container.innerHTML = articles.map(article => `
        <div class="list-item article-status-row" onclick="openDocumentManagerRenderer('${article.id}')">
            <div class="list-item-main">
                <span class="list-item-title">${escapeHtml(article.filename)}</span>
                <span class="list-item-subtitle">
                    ${(article.filetype || '').toUpperCase()} · ${article.text_length.toLocaleString()} chars
                </span>
            </div>
            ${renderPipelineStatusDots(article.pipeline_status)}
            <div class="list-item-actions">
                <button class="btn btn-sm" onclick="event.stopPropagation(); openDocumentManagerRenderer('${article.id}')">Render</button>
            </div>
        </div>
    `).join('');
}

function pipelineSummary(statuses) {
    const entries = Object.entries(statuses || {});
    if (!entries.length) return 'No pipeline runs';
    return entries.map(([slug, status]) => `${slug}: ${status.status || 'pending'}`).join(' · ');
}

function renderPipelineStatusDots(statuses) {
    const items = [
        ['entity_manager', 'EntityManager'],
        ['topic_manager', 'TopicManager'],
    ];
    return `
        <div class="pipeline-dot-grid" aria-label="Processing status">
            ${items.map(([slug, label]) => {
                const complete = statuses?.[slug]?.status === 'completed';
                return `
                    <span class="pipeline-dot-cell" title="${label}: ${complete ? 'processed' : 'not processed'}">
                        <span class="pipeline-dot ${complete ? 'processed' : 'pending'}"></span>
                        <span class="pipeline-dot-label">${label}</span>
                    </span>
                `;
            }).join('')}
        </div>
    `;
}

async function loadDocumentManagerArticleOptions(selectId, selectedId = '') {
    const select = document.getElementById(selectId);
    if (!select) return [];
    const articles = _dmArticles.length ? _dmArticles : await loadDocumentManagerArticles();
    const current = selectedId || select.value;
    select.innerHTML = '<option value="">Select an article</option>' +
        articles.map(article => `<option value="${article.id}">${escapeHtml(article.filename)}</option>`).join('');
    if (current && articles.some(article => article.id === current)) {
        select.value = current;
    }
    return articles;
}

async function openDocumentManagerRenderer(articleId) {
    switchView('dm-renderer');
    await loadDocumentManagerArticleOptions('dm-renderer-select', articleId);
    await loadDocumentManagerRenderer(articleId);
}

document.getElementById('dm-renderer-select')?.addEventListener('change', (event) => {
    if (event.target.value) loadDocumentManagerRenderer(event.target.value);
});

async function loadDocumentManagerRenderer(articleId) {
    const textEl = document.getElementById('dm-rendered-text');
    const metaEl = document.getElementById('dm-renderer-metadata');
    if (!textEl || !metaEl) return;
    showStatus('dm-renderer-status', 'Loading article...', '');
    textEl.innerHTML = '<div class="spinner"></div> Loading...';
    metaEl.innerHTML = '';
    try {
        const article = await api(`/document-manager/articles/${articleId}`);
        textEl.textContent = article.content_text || '';
        metaEl.innerHTML = renderMetadataPanel(article);
        showStatus('dm-renderer-status', `${article.filename} · ${article.text_length.toLocaleString()} chars`, 'success');
    } catch (err) {
        textEl.innerHTML = '';
        showStatus('dm-renderer-status', `Error: ${err.message}`, 'error');
    }
}

function renderMetadataPanel(article) {
    const metadataRows = Object.entries(article.metadata || {});
    return `
        <div class="detail-section">
            <h3>Article</h3>
            <div class="detail-row"><span class="detail-label">ID</span><span class="detail-value">${escapeHtml(article.id)}</span></div>
            <div class="detail-row"><span class="detail-label">Language</span><span class="detail-value">${escapeHtml(article.language || '')}</span></div>
            <div class="detail-row"><span class="detail-label">Published</span><span class="detail-value">${escapeHtml(article.publication_date || '')}</span></div>
            <div class="detail-row"><span class="detail-label">Current text</span><span class="detail-value">${escapeHtml(article.current_text_version_id || '')}</span></div>
        </div>
        <div class="detail-section">
            <h3>Metadata</h3>
            ${metadataRows.length ? metadataRows.map(([key, value]) => `
                <div class="detail-row"><span class="detail-label">${escapeHtml(key)}</span><span class="detail-value">${escapeHtml(typeof value === 'string' ? value : JSON.stringify(value))}</span></div>
            `).join('') : '<p style="color: var(--text-muted);">No metadata records.</p>'}
        </div>
        <div class="detail-section">
            <h3>Source Files</h3>
            ${(article.source_files || []).map(source => `
                <div class="detail-row"><span class="detail-label">${escapeHtml(source.source_type || 'source')}</span><span class="detail-value">${escapeHtml(source.original_filename || '')} · ${(source.file_size_bytes || 0).toLocaleString()} bytes</span></div>
            `).join('') || '<p style="color: var(--text-muted);">No source file records.</p>'}
        </div>
        <div class="detail-section">
            <h3>Pipeline</h3>
            ${renderPipelineStatusPills(article.pipeline_status)}
        </div>
    `;
}

function renderPipelineStatusPills(statuses) {
    return Object.entries(statuses || {}).map(([slug, status]) => {
        const ok = status.status === 'completed';
        return `<div class="runtime-pill ${ok ? 'ok' : ''}">${escapeHtml(slug)}: ${escapeHtml(status.status || 'pending')}</div>`;
    }).join('') || '<p style="color: var(--text-muted);">No pipeline status.</p>';
}

document.getElementById('dm-annotations-load-btn')?.addEventListener('click', loadDocumentManagerAnnotations);
document.getElementById('dm-annotations-article-select')?.addEventListener('change', loadDocumentManagerAnnotations);

async function loadDocumentManagerAnnotations() {
    const articleId = document.getElementById('dm-annotations-article-select')?.value;
    const container = document.getElementById('dm-annotations-list');
    if (!articleId || !container) return;
    const params = new URLSearchParams();
    const component = document.getElementById('dm-annotations-component')?.value.trim();
    const type = document.getElementById('dm-annotations-type')?.value.trim();
    if (component) params.set('component_slug', component);
    if (type) params.set('annotation_type', type);
    container.innerHTML = '<div class="spinner"></div> Loading...';
    try {
        const data = await api(`/document-manager/articles/${articleId}/annotations?${params}`);
        const annotations = data.annotations || [];
        if (!annotations.length) {
            container.innerHTML = '<p style="color: var(--text-muted);">No annotations match these filters.</p>';
            return;
        }
        container.innerHTML = annotations.map(annotation => `
            <div class="list-item">
                <div class="list-item-main">
                    <span class="list-item-title">${escapeHtml(annotation.exact_text)}</span>
                    <span class="list-item-subtitle">
                        ${escapeHtml(annotation.component_slug || 'unknown')} · ${escapeHtml(annotation.annotation_type)} · ${annotation.start_char}-${annotation.end_char}
                    </span>
                </div>
            </div>
        `).join('');
    } catch (err) {
        container.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}

async function loadDocumentManagerPipeline() {
    const container = document.getElementById('dm-pipeline-list');
    if (!container) return;
    const articles = _dmArticles.length ? _dmArticles : await loadDocumentManagerArticles();
    if (!articles.length) {
        container.innerHTML = '<p style="color: var(--text-muted);">No articles have been ingested.</p>';
        return;
    }
    container.innerHTML = articles.map(article => `
        <div class="list-item">
            <div class="list-item-main">
                <span class="list-item-title">${escapeHtml(article.filename)}</span>
                <span class="list-item-subtitle">${renderPipelineStatusPills(article.pipeline_status)}</span>
            </div>
        </div>
    `).join('');
}
