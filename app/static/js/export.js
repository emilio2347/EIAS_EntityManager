/* ========================================
   Export — Download entity database
   ======================================== */

// Export functionality is handled directly via the download buttons
// in index.html using window.location to trigger file downloads.
function downloadExport(fmt) {
    const params = new URLSearchParams();
    const profileId = getActiveProfileId();
    if (profileId) params.set('profile_id', profileId);
    window.location = `/api/export/${fmt}?${params}`;
}
