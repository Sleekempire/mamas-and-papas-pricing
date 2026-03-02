/**
 * auth.js — Session management and user display helpers.
 */

function initAuth() {
    const email = sessionStorage.getItem('user_email') || '—';
    const role = sessionStorage.getItem('user_role') || '—';

    const emailEl = document.getElementById('user-email-display');
    const roleEl = document.getElementById('user-role-display');
    const avatar = document.getElementById('user-avatar');

    if (emailEl) emailEl.textContent = email.split('@')[0];
    if (roleEl) roleEl.textContent = role;
    if (avatar) avatar.textContent = email.charAt(0).toUpperCase();

    // Hide Operations nav for Viewer role
    if (role === 'Viewer') {
        const ops = document.getElementById('admin-section');
        if (ops) ops.style.display = 'none';
        ['nav-upload', 'nav-train', 'nav-optimise'].forEach(id => {
            const el = document.getElementById(id);
            if (el) el.style.display = 'none';
        });
    }

    document.getElementById('logout-btn')?.addEventListener('click', () => {
        sessionStorage.clear();
        window.location.href = 'login.html';
    });
}
