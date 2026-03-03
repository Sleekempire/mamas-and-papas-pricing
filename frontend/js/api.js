/**
 * api.js — Centralised API client with JWT auth headers.
 * All fetch calls go through this module.
 */

// Base path for all requests
const API_BASE = window.location.protocol === 'file:' ? 'http://localhost:8000/api/v1' : '/api/v1';

// Track consecutive 401s — only force logout after 3 in a row
let _consecutive401s = 0;
const MAX_401S_BEFORE_LOGOUT = 3;

function getToken() {
    return sessionStorage.getItem('access_token');
}

function _showBackendBanner(message) {
    const existing = document.getElementById('_backend-banner');
    if (existing) return; // don't stack banners
    const banner = document.createElement('div');
    banner.id = '_backend-banner';
    banner.style.cssText = [
        'position:fixed', 'top:0', 'left:0', 'right:0', 'z-index:99999',
        'background:#f97316', 'color:#fff', 'padding:10px 20px',
        'font:600 14px/1.4 system-ui,sans-serif',
        'display:flex', 'align-items:center', 'gap:12px',
        'box-shadow:0 2px 8px rgba(0,0,0,.3)'
    ].join(';');
    banner.innerHTML = `<span>⚠️ ${message}</span>
        <button onclick="document.getElementById('_backend-banner')?.remove(); window.location.reload();"
            style="margin-left:auto;padding:4px 12px;border:2px solid #fff;border-radius:6px;
                   background:transparent;color:#fff;cursor:pointer;font-weight:700;">Retry</button>
        <button onclick="document.getElementById('_backend-banner')?.remove();"
            style="padding:4px 10px;border:none;border-radius:6px;background:rgba(0,0,0,.2);
                   color:#fff;cursor:pointer;">✕</button>`;
    document.body.prepend(banner);
    // Auto-dismiss after 8 seconds
    setTimeout(() => banner?.remove(), 8000);
}

async function apiFetch(path, options = {}) {
    const token = getToken();
    const headers = {
        'Content-Type': 'application/json',
        ...(token ? { 'Authorization': `Bearer ${token}` } : {}),
        ...(options.headers || {}),
    };

    // Remove Content-Type for FormData/multipart
    if (options.body instanceof FormData) {
        delete headers['Content-Type'];
    }

    let res;
    try {
        res = await fetch(`${API_BASE}${path}`, { ...options, headers });
    } catch (networkErr) {
        // Backend is down — show banner instead of crashing
        _showBackendBanner('Backend server is unreachable. Is it running on port 8000?');
        throw new Error('Backend unreachable. Please check that the server is running.');
    }

    if (res.status === 401) {
        _consecutive401s++;
        if (_consecutive401s >= MAX_401S_BEFORE_LOGOUT) {
            // Genuine session expiry after multiple failures — log out cleanly
            _consecutive401s = 0;
            sessionStorage.clear();
            _showBackendBanner('Your session has expired. Please refresh and log in again.');
            throw new Error('Session expired — please refresh the page.');
        }
        // First/second 401 — may be transient, surface as a regular error
        throw new Error('Authentication error (401). The server may have restarted — try again.');
    } else {
        _consecutive401s = 0; // Reset on success
    }

    if (res.status === 403) {
        throw new Error('Access denied: insufficient permissions');
    }
    if (res.status === 429) {
        throw new Error('Rate limit exceeded. Please wait before retrying.');
    }

    const text = await res.text();
    let data;
    try { data = JSON.parse(text); } catch { data = { detail: text }; }

    if (!res.ok) {
        // FastAPI returns detail as string OR array of validation error objects
        let detail = data.detail;
        if (Array.isArray(detail)) {
            detail = detail.map(e => e.msg || JSON.stringify(e)).join('; ');
        } else if (typeof detail === 'object') {
            detail = JSON.stringify(detail);
        }
        throw new Error(detail || `${res.status} ${res.statusText}`);
    }
    return data;
}

const API = {
    // Auth
    getMe: () => apiFetch('/auth/me'),

    // Data
    uploadCSV: (file) => {
        const fd = new FormData();
        fd.append('file', file);
        return apiFetch('/upload-data', { method: 'POST', body: fd, headers: {} });
    },

    // Training
    trainModel: () => apiFetch('/train', { method: 'POST' }),

    // Optimisation
    runOptimisation: (targetDate, category) => {
        const params = new URLSearchParams();
        if (targetDate) params.set('target_date', targetDate);
        if (category) params.set('category', category);
        return apiFetch(`/run-optimisation?${params}`, { method: 'POST' });
    },

    // Recommendations
    getRecommendations: (filters = {}) => {
        const params = new URLSearchParams();
        if (filters.sku || filters.description) params.set('description', filters.description || filters.sku);
        if (filters.category) params.set('category', filters.category);
        if (filters.date) params.set('target_date', filters.date);
        if (filters.limit) params.set('limit', filters.limit);
        return apiFetch(`/recommendations?${params}`);
    },

    getExplanation: (description, date) => {
        const params = new URLSearchParams();
        if (date) params.set('target_date', date);
        return apiFetch(`/recommendations/explanation/${encodeURIComponent(description)}?${params}`);
    },
};

// Format helpers
function fmt(n, prefix = '', suffix = '', decimals = 0) {
    if (n == null || isNaN(n)) return '—';
    return `${prefix}${Number(n).toLocaleString('en-GB', { minimumFractionDigits: decimals, maximumFractionDigits: decimals })}${suffix}`;
}
function fmtPct(n, decimals = 1) { return fmt(n * 100, '', '%', decimals); }
function fmtGBP(n) { return fmt(n, '£', '', 2); }
function fmtDelta(n, suffix = '%') {
    if (n == null) return '';
    const sign = n >= 0 ? '▲' : '▼';
    return `${sign} ${Math.abs(n).toFixed(2)}${suffix}`;
}
