/* ========================================
   Extraction Profiles — manage NER type filters used at upload time
   ======================================== */

let _knownNerTypes = [];
let _editingProfileId = null;


async function loadKnownNerTypes() {
    if (_knownNerTypes.length) return _knownNerTypes;
    try {
        const data = await api('/profiles/types');
        _knownNerTypes = data.types || [];
    } catch {
        _knownNerTypes = [...ENTITY_TYPES];
    }
    return _knownNerTypes;
}


async function loadProfilesView() {
    await loadKnownNerTypes();
    renderTypeCheckboxes(new Set());
    resetProfileForm();
    await renderProfileList();
}


async function renderProfileList() {
    const container = document.getElementById('profile-list');
    if (!container) return;

    try {
        const profiles = await api('/profiles');
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
                    <span class="list-item-subtitle">
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
        <label class="type-checkbox">
            <input type="checkbox" value="${t}" ${selectedSet.has(t) ? 'checked' : ''}>
            <span>${entityTypeTag(t)}</span>
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
    document.getElementById('view-profiles')?.scrollIntoView({ behavior: 'smooth' });
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
        await loadProfilesIntoUploadSelect();
    } catch (err) {
        showStatus('profile-status', `Error: ${err.message}`, 'error');
    }
});


document.getElementById('profile-reset-btn')?.addEventListener('click', resetProfileForm);


async function deleteProfile(profileId) {
    if (!confirm('Delete this extraction profile?')) return;
    try {
        await api(`/profiles/${profileId}`, { method: 'DELETE' });
        if (_editingProfileId === profileId) resetProfileForm();
        await renderProfileList();
        await loadProfilesIntoUploadSelect();
    } catch (err) {
        alert('Error: ' + err.message);
    }
}


/**
 * Populate the profile dropdown on the document upload form.
 * Selects whichever profile is_default.
 */
async function loadProfilesIntoUploadSelect() {
    const select = document.getElementById('upload-profile-select');
    if (!select) return;
    try {
        const profiles = await api('/profiles');
        const previous = select.value;
        select.innerHTML = profiles.map(p =>
            `<option value="${p.id}" ${p.is_default ? 'selected' : ''}>${escapeHtml(p.name)}${p.is_default ? ' (default)' : ''}</option>`
        ).join('');
        // Preserve user's selection if it still exists
        if (previous && profiles.some(p => p.id === previous)) {
            select.value = previous;
        }
    } catch {
        select.innerHTML = '<option value="">All Types</option>';
    }
}
