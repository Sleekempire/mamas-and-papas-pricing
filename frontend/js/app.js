/**
 * app.js — SPA orchestration: navigation, page init, upload/train/optimise handlers.
 */

const PAGE_TITLES = {
    overview: { title: 'Overview', subtitle: 'Portfolio KPIs & summary charts' },
    recommendations: { title: 'Recommendations', subtitle: 'Price recommendations per SKU' },
    simulator: { title: 'Scenario Simulator', subtitle: 'Explore price adjustment scenarios' },
    'sku-detail': { title: 'SKU Detail', subtitle: 'Deep-dive analysis and explanation' },
    upload: { title: 'Upload Data', subtitle: 'Ingest CSV sales data' },
    train: { title: 'Train Model', subtitle: 'Demand model training' },
    optimise: { title: 'Run Optimisation', subtitle: 'Generate price recommendations' },
};

function navigateTo(pageId) {
    document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));

    const page = document.getElementById(`page-${pageId}`);
    if (page) page.classList.add('active');

    const nav = document.getElementById(`nav-${pageId}`);
    if (nav) nav.classList.add('active');

    const meta = PAGE_TITLES[pageId] || { title: pageId, subtitle: '' };
    document.getElementById('page-title').textContent = meta.title;

    // Check if subtitle exists before setting it to prevent crash
    const subtitleEl = document.getElementById('page-subtitle');
    if (subtitleEl) subtitleEl.textContent = meta.subtitle;

    document.getElementById('page-date').textContent = new Date().toLocaleDateString('en-GB', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });
}

function showAlert(containerId, type, message) {
    const el = document.getElementById(containerId);
    if (!el) return;
    el.innerHTML = `<div class="alert alert-${type}">${message}</div>`;
}

function initApp() {
    initAuth();

    // ── Navigation ───────────────────────────────────────────────────────────
    document.querySelectorAll('.nav-item[data-page]').forEach(item => {
        item.addEventListener('click', () => {
            const pageId = item.dataset.page;
            navigateTo(pageId);
            if (pageId === 'overview') loadDashboard();
            if (pageId === 'recommendations') loadRecommendations();
            if (pageId === 'simulator') initSimulator();
            if (pageId === 'sku-detail') initSKUDetailPage();
        });
    });

    // ── Set date display ─────────────────────────────────────────────────────
    document.getElementById('page-date').textContent = new Date().toLocaleDateString('en-GB', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' });

    // Set default date on optimise panel
    const optDate = document.getElementById('opt-date');
    if (optDate) optDate.value = new Date().toISOString().slice(0, 10);

    // ── Upload handler ───────────────────────────────────────────────────────
    const uploadZone = document.getElementById('upload-zone');
    const fileInput = document.getElementById('file-input');

    if (uploadZone && fileInput) {
        uploadZone.addEventListener('click', () => fileInput.click());
        uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('drag-over'); });
        uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
        uploadZone.addEventListener('drop', async (e) => {
            e.preventDefault();
            uploadZone.classList.remove('drag-over');
            const file = e.dataTransfer.files[0];
            if (file) await handleUpload(file);
        });
        fileInput.addEventListener('change', async (e) => {
            if (e.target.files[0]) await handleUpload(e.target.files[0]);
        });
    }

    // Sample CSV download — fetch from backend so it always matches the current schema
    const sampleBtn = document.getElementById('download-sample-btn');
    if (sampleBtn) {
        sampleBtn.addEventListener('click', async () => {
            try {
                const token = sessionStorage.getItem('access_token');
                const res = await fetch(`${API_BASE}/upload-data/sample-csv`, {
                    headers: token ? { 'Authorization': `Bearer ${token}` } : {},
                });
                if (!res.ok) throw new Error('Failed to download sample CSV');
                const blob = await res.blob();
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url; a.download = 'mamas_papas_sample_data.csv';
                a.click(); URL.revokeObjectURL(url);
            } catch (err) {
                showAlert('upload-alerts', 'error', `Download failed: ${err.message}`);
            }
        });
    }

    // ── Train handler ────────────────────────────────────────────────────────
    const trainBtn = document.getElementById('train-btn');
    if (trainBtn) {
        trainBtn.addEventListener('click', async () => {
            const txt = document.getElementById('train-btn-text');
            const spin = document.getElementById('train-spinner');
            trainBtn.disabled = true; txt.textContent = 'Training…'; spin.classList.remove('hidden');
            document.getElementById('train-alerts').innerHTML = '';
            try {
                const result = await API.trainModel();
                document.getElementById('train-result').innerHTML = `
          <div class="alert alert-success">
            ✅ Model trained successfully!<br>
            <strong>Algorithm:</strong> ${result.algorithm} &nbsp;|&nbsp;
            <strong>Val R²:</strong> ${result.val_r2} &nbsp;|&nbsp;
            <strong>RMSE:</strong> ${result.rmse}<br>
            <details style="margin-top:0.5rem;font-size:0.8rem;"><summary>All models</summary>
              <pre style="color:var(--text-secondary);margin-top:0.4rem;">${JSON.stringify(result.all_models, null, 2)}</pre>
            </details>
          </div>`;
                document.getElementById('train-result').classList.remove('hidden');
            } catch (err) {
                showAlert('train-alerts', 'error', `Training failed: ${err.message}`);
            } finally {
                trainBtn.disabled = false; txt.textContent = '🚀 Start Training'; spin.classList.add('hidden');
            }
        });
    }

    // ── Optimise handler ─────────────────────────────────────────────────────
    const optBtn = document.getElementById('opt-btn');
    if (optBtn) {
        optBtn.addEventListener('click', async () => {
            const txt = document.getElementById('opt-btn-text');
            const spin = document.getElementById('opt-spinner');
            optBtn.disabled = true; txt.textContent = 'Running…'; spin.classList.remove('hidden');
            document.getElementById('opt-alerts').innerHTML = '';
            try {
                const date = document.getElementById('opt-date').value;
                const cat = document.getElementById('opt-category').value.trim();
                const result = await API.runOptimisation(date || null, cat || null);
                document.getElementById('opt-result').innerHTML = `
          <div class="alert alert-success">
            ⚡ Optimisation complete!<br>
            <strong>${result.sku_count}</strong> recommendations generated for <strong>${result.target_date}</strong>.<br>
            Navigate to <strong>Recommendations</strong> to view results.
          </div>`;
                document.getElementById('opt-result').classList.remove('hidden');
                document.getElementById('rec-count').textContent = result.sku_count;
            } catch (err) {
                showAlert('opt-alerts', 'error', `Optimisation failed: ${err.message}`);
            } finally {
                optBtn.disabled = false; txt.textContent = '⚡ Generate Recommendations'; spin.classList.add('hidden');
            }
        });
    }

    // ── SKU detail load button ───────────────────────────────────────────────
    const detailBtn = document.getElementById('detail-load-btn');
    if (detailBtn) {
        detailBtn.addEventListener('click', () => {
            const sku = document.getElementById('detail-sku-select').value;
            if (sku) loadSKUDetail(sku);
        });
    }

    // ── Initial load ─────────────────────────────────────────────────────────
    loadDashboard();
    initTableControls();
    navigateTo('overview');
}

async function handleUpload(file) {
    const progress = document.getElementById('upload-progress');
    const fill = document.getElementById('progress-fill');
    const pct = document.getElementById('progress-pct');
    const result = document.getElementById('upload-result');
    const alerts = document.getElementById('upload-alerts');

    alerts.innerHTML = '';
    result.classList.add('hidden');
    progress.classList.remove('hidden');

    // Animate progress bar (simulated — actual upload is synchronous)
    let p = 0;
    const tick = setInterval(() => {
        p = Math.min(p + Math.random() * 15, 85);
        fill.style.width = `${p}%`;
        pct.textContent = `${Math.round(p)}%`;
    }, 300);

    try {
        const resp = await API.uploadCSV(file);
        clearInterval(tick);
        fill.style.width = '100%'; pct.textContent = '100%';
        progress.classList.add('hidden');

        result.innerHTML = `
      <div class="alert alert-success">
        ✅ Upload complete! <strong>${resp.cleaned_row_count}</strong> rows ingested.
        ${resp.quarantine_count > 0 ? `<br>⚠️ ${resp.quarantine_count} rows quarantined as outliers.` : ''}
        ${resp.warnings?.length ? `<br><details><summary>${resp.warnings.length} warning(s)</summary><ul style="margin-top:0.3rem;font-size:0.8rem;">${resp.warnings.map(w => `<li>${w}</li>`).join('')}</ul></details>` : ''}
      </div>`;
        result.classList.remove('hidden');
    } catch (err) {
        clearInterval(tick);
        progress.classList.add('hidden');
        showAlert('upload-alerts', 'error', `Upload failed: ${err.message}`);
    }
}

// ── Bootstrap ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', initApp);
