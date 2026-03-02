/**
 * sku-detail.js — SKU detail page with demand curve, margin, and feature importance.
 */

let demandCurveChart = null;
let marginCurveChart = null;

// Populate the product dropdown from the API — called each time SKU Detail page is visited
async function initSKUDetailPage() {
    const sel = document.getElementById('detail-sku-select');
    if (!sel) return;
    if (sel.options.length > 1) return; // already populated
    try {
        const data = await API.getRecommendations({ limit: 500 });
        const recs = data.results || [];
        if (recs.length === 0) return;

        const uniqueRecs = [];
        const seen = new Set();
        recs.forEach(r => {
            if (r.description && !seen.has(r.description)) {
                seen.add(r.description);
                uniqueRecs.push(r);
            }
        });

        const sorted = uniqueRecs.sort((a, b) => a.description.localeCompare(b.description));
        sel.innerHTML = '<option value="">— Choose SKU —</option>' + sorted.map(r => {
            const truncated = r.description.length > 50 ? r.description.substring(0, 47) + '...' : r.description;
            return `<option value="${r.description.replace(/"/g, '&quot;')}">${truncated} – ${r.analyst_category || ''}</option>`;
        }).join('');
    } catch (e) {
        // Silently fail
    }
}

async function loadSKUDetail(sku, date) {
    if (!sku) return;
    document.getElementById('detail-sku-badge').textContent = sku;
    document.getElementById('detail-placeholder').classList.add('hidden');
    document.getElementById('detail-content').style.display = 'grid';

    try {
        const [recData, explData] = await Promise.all([
            API.getRecommendations({ sku, date, limit: 1 }),
            API.getExplanation(sku, date),
        ]);

        const rec = recData.results?.[0];
        if (rec) {
            document.getElementById('detail-sku-category').textContent = rec.analyst_category || rec.product_category || 'Unknown Category';
            renderSKUSummary(rec);
            renderDemandCurve(rec, explData);
            renderMarginCurve(explData);
        }

        if (explData) {
            document.getElementById('sku-narrative').textContent = explData.narrative || '—';
            renderFeatureBars(explData.top_demand_drivers || []);
        }
    } catch (err) {
        document.getElementById('sku-narrative').textContent = `Error loading explanation: ${err.message}`;
    }
}

function renderSKUSummary(rec) {
    const grid = document.getElementById('sku-summary-grid');
    if (!grid) return;
    const items = [
        { label: 'Current Price', value: `£${(rec.current_price || 0).toFixed(2)}` },
        { label: 'Rec. Price', value: `£${(rec.recommended_price || 0).toFixed(2)}`, highlight: true },
        { label: 'Expected Demand', value: Math.round(rec.expected_demand || 0).toLocaleString() },
        { label: 'Expected Revenue', value: `£${Math.round(rec.expected_revenue || 0).toLocaleString('en-GB')}` },
        { label: 'Margin', value: `£${Math.round(rec.expected_margin || 0).toLocaleString('en-GB')}` },
        { label: 'Confidence', value: `${((rec.confidence_score || 0) * 100).toFixed(0)}%` },
        { label: 'Elasticity', value: (rec.elasticity || 0).toFixed(3) },
        { label: 'Class', value: rec.elasticity_class || 'Neutral' },
    ];
    grid.innerHTML = items.map(i => `
    <div style="background:var(--bg-surface);border:1px solid var(--border-subtle);border-radius:var(--radius-sm);padding:0.6rem 0.75rem;${i.highlight ? 'border-color:var(--border-mid);' : ''}">
      <div style="font-size:0.65rem;text-transform:uppercase;letter-spacing:0.05em;color:var(--text-muted);font-weight:600;">${i.label}</div>
      <div style="font-size:1rem;font-weight:700;margin-top:0.15rem;${i.highlight ? 'color:var(--brand-primary);' : ''}">${i.value}</div>
    </div>
  `).join('');
}

function renderDemandCurve(rec, explData) {
    const ctx = document.getElementById('demand-curve-chart');
    if (!ctx) return;
    if (demandCurveChart) demandCurveChart.destroy();

    const basePrice = rec.current_price || 0;
    const baseDemand = rec.expected_demand || 0;
    const elasticity = rec.elasticity ?? -1.0;

    const prices = Array.from({ length: 21 }, (_, i) => basePrice * (0.8 + i * 0.02));
    const demands = prices.map(p => {
        const pChg = (p - basePrice) / (basePrice || 1);
        return Math.max(0, baseDemand * (1 + elasticity * pChg));
    });

    demandCurveChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: prices.map(p => `£${p.toFixed(2)}`),
            datasets: [{
                label: 'Predicted Demand',
                data: demands.map(d => Math.round(d)),
                borderColor: '#3b5998',
                backgroundColor: 'rgba(59,89,152,0.08)',
                fill: true, tension: 0.4,
                pointRadius: 3, pointBackgroundColor: '#3b5998',
            }],
        },
        options: buildChartOptions('Units', 'Price'),
    });
}

function renderMarginCurve(explData) {
    const ctx = document.getElementById('margin-curve-chart');
    if (!ctx || !explData?.margin_sensitivity?.curve) return;
    if (marginCurveChart) marginCurveChart.destroy();

    const curve = explData.margin_sensitivity.curve;
    marginCurveChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: curve.map(p => `£${p.price}`),
            datasets: [{
                label: 'Margin (£)',
                data: curve.map(p => p.margin),
                borderColor: 'rgba(16,185,129,0.9)',
                backgroundColor: 'rgba(16,185,129,0.08)',
                fill: true, tension: 0.4, pointRadius: 3,
            }],
        },
        options: buildChartOptions('£ Margin', 'Price'),
    });
}

const FEATURE_LABELS = {
    'channel_mix_ratio': 'Channel Mix (Home Shopping)',
    'Lag_1': 'Previous Week Demand',
    'Lag_4': 'Demand 4 Weeks Ago',
    'Rolling_Mean_4': 'Recent Average Demand (4w)',
    'ImpliedPrice': 'Price',
    'Week_cos': 'Seasonality (Cosine)',
    'Week_sin': 'Seasonality (Sine)',
    'PromoFlag': 'On Promotion',
    'fiscal_quarter': 'Fiscal Quarter'
};

function renderFeatureBars(drivers) {
    const container = document.getElementById('feature-bars');
    if (!container) return;
    if (!drivers.length) { container.innerHTML = '<div class="text-muted text-sm">No feature data available</div>'; return; }

    container.innerHTML = drivers.map(d => `
    <div class="feature-bar-row">
      <div class="feature-bar-label" data-tip="${d.direction} correlation">${FEATURE_LABELS[d.feature] || d.feature}</div>
      <div class="feature-bar-track">
        <div class="feature-bar-fill ${d.direction}" style="width:${(d.importance * 100).toFixed(1)}%"></div>
      </div>
      <div class="feature-bar-val">${(d.importance * 100).toFixed(1)}%</div>
    </div>
  `).join('');
}

function buildChartOptions(yLabel, xLabel) {
    return {
        responsive: true, maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: { backgroundColor: '#1e293b', titleColor: '#f0f4ff', bodyColor: '#94a3b8', borderColor: '#374151', borderWidth: 1 },
        },
        scales: {
            x: { grid: { color: 'rgba(148,163,184,0.05)' }, ticks: { color: '#94a3b8', font: { size: 9 }, maxRotation: 45 }, title: { display: true, text: xLabel, color: '#4b5563', font: { size: 10 } } },
            y: { grid: { color: 'rgba(148,163,184,0.05)' }, ticks: { color: '#94a3b8', font: { size: 9 } }, title: { display: true, text: yLabel, color: '#4b5563', font: { size: 10 } } },
        },
    };
}
