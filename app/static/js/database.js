/* ========================================
   Database — read-only table browser
   ======================================== */

let _databaseTables = [];
let _databaseSelectedTable = '';
let _databaseOffset = 0;
const DATABASE_PAGE_SIZE = 50;

async function loadDatabaseTables() {
    const list = document.getElementById('database-table-list');
    if (!list) return;
    list.innerHTML = '<div class="spinner"></div> Loading...';
    try {
        _databaseTables = await api('/database/tables');
        renderDatabaseTableList();
        if (!_databaseSelectedTable && _databaseTables.length) {
            await openDatabaseTable(_databaseTables[0].name, 0);
        } else if (_databaseSelectedTable) {
            await openDatabaseTable(_databaseSelectedTable, _databaseOffset);
        }
    } catch (err) {
        list.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}

function renderDatabaseTableList() {
    const list = document.getElementById('database-table-list');
    if (!list) return;
    list.innerHTML = _databaseTables.map(table => `
        <div class="list-item ${table.name === _databaseSelectedTable ? 'selected' : ''}" onclick="openDatabaseTable('${escapeAttr(table.name)}', 0)">
            <div class="list-item-main">
                <span class="list-item-title">${escapeHtml(table.name)}</span>
                <span class="list-item-subtitle">${table.row_count.toLocaleString()} rows · ${table.columns.length} columns</span>
            </div>
        </div>
    `).join('') || '<p style="color: var(--text-muted);">No tables registered.</p>';
}

async function openDatabaseTable(tableName, offset = 0) {
    _databaseSelectedTable = tableName;
    _databaseOffset = Math.max(0, offset);
    renderDatabaseTableList();

    const title = document.getElementById('database-table-title');
    const meta = document.getElementById('database-table-meta');
    const content = document.getElementById('database-table-content');
    if (!content) return;
    if (title) title.textContent = tableName;
    if (meta) meta.textContent = '';
    content.innerHTML = '<div class="spinner"></div> Loading...';
    try {
        const data = await api(`/database/tables/${encodeURIComponent(tableName)}?limit=${DATABASE_PAGE_SIZE}&offset=${_databaseOffset}`);
        if (meta) {
            const shownEnd = Math.min(data.row_count, data.offset + data.rows.length);
            meta.textContent = `${data.row_count.toLocaleString()} rows · showing ${data.offset + 1}-${shownEnd || 0}`;
        }
        renderDatabaseRows(data);
        updateDatabasePagination(data);
    } catch (err) {
        content.innerHTML = `<p class="status-msg error">Error: ${err.message}</p>`;
    }
}

function renderDatabaseRows(data) {
    const content = document.getElementById('database-table-content');
    if (!content) return;
    if (!data.rows.length) {
        content.innerHTML = '<p style="color: var(--text-muted);">No rows.</p>';
        return;
    }
    content.innerHTML = `
        <table class="database-table">
            <thead>
                <tr>${data.columns.map(column => `<th>${escapeHtml(column)}</th>`).join('')}</tr>
            </thead>
            <tbody>
                ${data.rows.map(row => `
                    <tr>
                        ${data.columns.map(column => `<td>${formatDatabaseCell(row[column])}</td>`).join('')}
                    </tr>
                `).join('')}
            </tbody>
        </table>
    `;
}

function formatDatabaseCell(value) {
    if (value === null || value === undefined) return '<span class="muted-cell">NULL</span>';
    if (typeof value === 'object') return `<pre>${escapeHtml(JSON.stringify(value, null, 2))}</pre>`;
    const text = String(value);
    if ((text.startsWith('{') && text.endsWith('}')) || (text.startsWith('[') && text.endsWith(']'))) {
        try {
            return `<pre>${escapeHtml(JSON.stringify(JSON.parse(text), null, 2))}</pre>`;
        } catch {
            return escapeHtml(text);
        }
    }
    return escapeHtml(text);
}

function updateDatabasePagination(data) {
    const prev = document.getElementById('database-prev-btn');
    const next = document.getElementById('database-next-btn');
    if (prev) prev.disabled = data.offset <= 0;
    if (next) next.disabled = data.offset + data.limit >= data.row_count;
}

document.getElementById('database-prev-btn')?.addEventListener('click', () => {
    if (!_databaseSelectedTable) return;
    openDatabaseTable(_databaseSelectedTable, Math.max(0, _databaseOffset - DATABASE_PAGE_SIZE));
});

document.getElementById('database-next-btn')?.addEventListener('click', () => {
    if (!_databaseSelectedTable) return;
    openDatabaseTable(_databaseSelectedTable, _databaseOffset + DATABASE_PAGE_SIZE);
});
