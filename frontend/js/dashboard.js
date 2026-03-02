/**
 * dashboard.js — Overview KPI cards and summary charts.
 */

let overviewChart = null;
let elasticityDonut = null;

async function loadDashboard() {
    try {
        const data = await API.getRecommendations({ limit: 500 });
        const recs = data.results || [];

        if (recs.length === 0) {
            setKPI('kpi-revenue', '—', '');
            setKPI('kpi-margin', '—', '');
            setKPI('kpi-skus', '0', '');
            setKPI('kpi-elasticity', '—', '');
            document.getElementById('rec-count').textContent = '0';
            renderSystemStatus(null);
            return;
        }

        document.getElementById('rec-count').textContent = recs.length;

        // KPI calculations
        let totalRevenue = 0, totalMargin = 0, baseRevenue = 0;
        let skusUp = 0, skusDown = 0;

        recs.forEach(r => {
            totalRevenue += r.expected_revenue || 0;
            totalMargin += r.expected_margin || 0;
            const currentPrice = r.current_price || 0;
            const demand = r.expected_demand || 0;
            baseRevenue += (currentPrice * demand);

            const pctChg = r.price_change_pct || 0;
            if (pctChg > 0.001) skusUp++;
            else if (pctChg < -0.001) skusDown++;
        });

        const upliftPct = baseRevenue > 0 ? ((totalRevenue - baseRevenue) / baseRevenue) * 100 : 0;

        setKPI('kpi-total-revenue', fmtGBP(totalRevenue), `${skusUp + skusDown} SKUs with price changes`);
        setKPI('kpi-total-margin', fmtGBP(totalMargin), 'Gross margin across portfolio');
        setKPI('kpi-uplift', `${upliftPct >= 0 ? '+' : ''}${upliftPct.toFixed(1)}%`, 'vs. current baseline prices', upliftPct >= 0 ? 'price-up' : 'price-down');
        setKPI('kpi-sku-up', skusUp.toString(), '↑ Price Up', 'price-up');
        setKPI('kpi-sku-down', skusDown.toString(), '↓ Price Down', 'price-down');

        renderOverviewChart(recs);
        renderElasticityDonut(recs);
        renderSystemStatus(recs);
    } catch (err) {
        console.warn('Dashboard load error:', err.message);
    }
}

function setKPI(id, value, subtitle, changeClass = '') {
    const el = document.getElementById(id);
    if (el) { el.textContent = value; animateCounter(el); }
    const changeId = id + '-change';
    const changeEl = document.getElementById(changeId);
    if (changeEl) {
        changeEl.textContent = subtitle;
        changeEl.className = 'kpi-change ' + changeClass;
    }
}

function animateCounter(el) {
    el.style.opacity = '0';
    el.style.transform = 'translateY(10px)';
    setTimeout(() => {
        el.style.transition = 'opacity 0.4s ease, transform 0.4s ease';
        el.style.opacity = '1';
        el.style.transform = 'translateY(0)';
    }, 50);
}

function renderOverviewChart(recs) {
    const ctx = document.getElementById('overview-chart');
    if (!ctx) return;
    if (overviewChart) overviewChart.destroy();

    // Aggregate by category
    const byCategory = {};
    recs.forEach(r => {
        const cat = r.analyst_category || 'Other';
        if (!byCategory[cat]) byCategory[cat] = { revenue: 0, margin: 0 };
        byCategory[cat].revenue += r.expected_revenue || 0;
        byCategory[cat].margin += r.expected_margin || 0;
    });

    const labels = Object.keys(byCategory);
    const revenues = labels.map(l => Math.round(byCategory[l].revenue));
    const margins = labels.map(l => Math.round(byCategory[l].margin));

    overviewChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels,
            datasets: [
                { label: 'Revenue (£)', data: revenues, backgroundColor: '#3b5998', borderRadius: 4 },
                { label: 'Margin (£)', data: margins, backgroundColor: '#10b981', borderRadius: 4 },
            ],
        },
        options: chartDefaults({ indexAxis: 'y', aspectRatio: false }),
    });
}

function renderElasticityDonut(recs) {
    const ctx = document.getElementById('elasticity-donut');
    if (!ctx) return;
    if (elasticityDonut) elasticityDonut.destroy();

    const counts = { Elastic: 0, Inelastic: 0, Neutral: 0 };
    recs.forEach(r => { if (r.elasticity_class) counts[r.elasticity_class] = (counts[r.elasticity_class] || 0) + 1; });

    elasticityDonut = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: Object.keys(counts),
            datasets: [{
                data: Object.values(counts),
                backgroundColor: ['#ef4444', '#10b981', '#f59e0b'],
                borderColor: '#ffffff',
                borderWidth: 2,
            }],
        },
        options: { ...chartDefaults(), cutout: '65%', plugins: { legend: { position: 'bottom' } } },
    });
}

function renderSystemStatus(recs) {
    const grid = document.getElementById('system-status-grid');
    if (!grid) return;
    const modelText = document.getElementById('model-status-text');

    const items = [
        { label: 'API Status', value: 'Online', dot: 'green' },
        { label: 'Active Model', value: recs ? 'Loaded' : 'None', dot: recs ? 'green' : 'red' },
        { label: 'Recommendations', value: recs ? `${recs.length} SKUs` : '—', dot: recs ? 'green' : 'amber' },
        { label: 'Last Updated', value: new Date().toLocaleTimeString('en-GB'), dot: 'green' },
    ];

    if (modelText) modelText.textContent = recs ? `${recs.length} recommendations loaded` : 'No data';

    grid.innerHTML = items.map(i => `
    <div style="display:flex;align-items:center;gap:0.75rem;padding:0.75rem;background:var(--bg-surface);border-radius:var(--radius-sm);border:1px solid var(--border-subtle);">
      <span class="status-dot ${i.dot}"></span>
      <div>
        <div style="font-size:0.7rem;color:var(--text-muted);font-weight:600;text-transform:uppercase;">${i.label}</div>
        <div style="font-size:0.875rem;font-weight:600;">${i.value}</div>
      </div>
    </div>
  `).join('');
}

function chartDefaults(extra = {}) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        ...extra,
        plugins: {
            ...(extra.plugins || {}),
            legend: { labels: { color: '#94a3b8', font: { size: 11 } }, ...(extra.plugins?.legend || {}) },
            tooltip: { backgroundColor: '#1e293b', titleColor: '#f0f4ff', bodyColor: '#94a3b8', borderColor: '#374151', borderWidth: 1 },
        },
        scales: extra.type === 'doughnut' ? undefined : {
            x: { grid: { color: 'rgba(148,163,184,0.08)' }, ticks: { color: '#94a3b8', font: { size: 10 } } },
            y: { grid: { color: 'rgba(148,163,184,0.08)' }, ticks: { color: '#94a3b8', font: { size: 10 } } },
        },
    };
}
