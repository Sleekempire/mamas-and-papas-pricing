/**
 * simulator.js — Price adjustment slider with real-time revenue/margin simulation.
 */

let simChart = null;
let simRecs = {};        // description → recommendation object
let simCurrentRec = null;
let simulatorInitialized = false;

function initSimulator() {
    if (simulatorInitialized) return;
    simulatorInitialized = true;

    const slider = document.getElementById('price-slider');
    const label = document.getElementById('slider-label');

    // Populate SKU selector
    populateSimSKUSelect();

    document.getElementById('sim-sku-select').addEventListener('change', async (e) => {
        const desc = e.target.value;
        if (!desc) {
            simCurrentRec = null;
            return;
        }
        simCurrentRec = simRecs[desc];
        if (!simCurrentRec) {
            try {
                const data = await API.getRecommendations({ description: desc, limit: 1 });
                simCurrentRec = data.results?.[0];
                if (simCurrentRec) simRecs[desc] = simCurrentRec;
            } catch { }
        }
        if (simCurrentRec) {
            slider.value = 100;
            updateSliderGradient(slider);
            label.textContent = 'Current (0%)';
            updateSimMetrics(100);
            renderSimChart(simCurrentRec);
        }
    });

    slider.addEventListener('input', (e) => {
        const pct = parseInt(e.target.value);
        const sign = pct > 100 ? '+' : pct < 100 ? '' : '';
        label.textContent = pct === 100 ? 'Current (0%)' : `${sign}${pct - 100}% vs current`;
        updateSliderGradient(slider);
        updateSimMetrics(pct);
    });
}

function updateSliderGradient(slider) {
    const val = slider.value;
    const pct = ((val - 80) / 40) * 100;
    slider.style.background = `linear-gradient(to right, var(--brand-primary) 0%, var(--brand-primary) ${pct}%, var(--border-mid) ${pct}%)`;
}

function updateSimMetrics(pct) {
    if (!simCurrentRec) return;
    const rec = simCurrentRec;
    const multiplier = pct / 100;
    const basePrice = rec.current_price || 0;
    const newPrice = basePrice * multiplier;

    // Simple elasticity-based demand estimate
    const elasticity = rec.elasticity ?? -1.0;
    const priceChangePct = (newPrice - basePrice) / (basePrice || 1);
    const demandChangePct = elasticity * priceChangePct;
    const baseDemand = rec.expected_demand || 0;
    const newDemand = Math.max(0, baseDemand * (1 + demandChangePct));
    const newRevenue = newPrice * newDemand;
    const baseRevenue = rec.expected_revenue || 0;
    const baseMargin = rec.expected_margin || 0;

    // Estimate new margin (simplified)
    const unitCostApprox = basePrice - (baseMargin / (baseDemand || 1));
    const newMargin = (newPrice - unitCostApprox) * newDemand;

    setSimMetric('sim-price', `£${newPrice.toFixed(2)}`, fmtDelta((newPrice - basePrice) / basePrice * 100, '%'), newPrice >= basePrice);
    setSimMetric('sim-demand', Math.round(newDemand).toLocaleString(), fmtDelta((newDemand - baseDemand) / (baseDemand || 1) * 100, '%'), newDemand >= baseDemand);
    setSimMetric('sim-revenue', `£${Math.round(newRevenue).toLocaleString('en-GB')}`, fmtDelta((newRevenue - baseRevenue) / (baseRevenue || 1) * 100, '%'), newRevenue >= baseRevenue);
    setSimMetric('sim-margin', `£${Math.round(newMargin).toLocaleString('en-GB')}`, fmtDelta((newMargin - baseMargin) / (baseMargin || 1) * 100, '%'), newMargin >= baseMargin);
}

function setSimMetric(id, value, delta, isUp) {
    const el = document.getElementById(id);
    const deltaEl = document.getElementById(id + '-delta');
    if (el) el.textContent = value;
    if (deltaEl) {
        deltaEl.textContent = delta;
        deltaEl.className = 'sim-metric-delta ' + (isUp ? 'sim-delta-up' : 'sim-delta-down');
    }
}

function renderSimChart(rec) {
    const ctx = document.getElementById('sim-chart');
    if (!ctx) return;
    if (simChart) simChart.destroy();

    const basePrice = rec.current_price || 0;
    const baseDemand = rec.expected_demand || 0;
    const elasticity = rec.elasticity ?? -1.0;

    const prices = Array.from({ length: 21 }, (_, i) => basePrice * (0.8 + i * 0.02));
    const revenues = prices.map(p => {
        const pChg = (p - basePrice) / (basePrice || 1);
        const d = Math.max(0, baseDemand * (1 + elasticity * pChg));
        return Math.round(p * d);
    });

    const labels = prices.map(p => `£${p.toFixed(2)}`);
    const currentIdx = 10; // midpoint = current price

    simChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels,
            datasets: [{
                label: 'Estimated Revenue',
                data: revenues,
                borderColor: '#3b5998',
                backgroundColor: 'rgba(59,89,152,0.1)',
                fill: true,
                tension: 0.4,
                pointRadius: (ctx) => ctx.dataIndex === currentIdx ? 7 : 3,
                pointBackgroundColor: (ctx) => ctx.dataIndex === currentIdx ? '#f59e0b' : '#3b5998',
                pointBorderColor: '#0f172a',
                pointBorderWidth: 2,
            }],
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: '#1e293b', titleColor: '#f0f4ff', bodyColor: '#94a3b8',
                    callbacks: { label: ctx => `Revenue: £${ctx.parsed.y.toLocaleString()}` }
                },
                annotation: {},
            },
            scales: {
                x: { grid: { color: 'rgba(148,163,184,0.05)' }, ticks: { color: '#94a3b8', font: { size: 9 }, maxRotation: 45 } },
                y: { grid: { color: 'rgba(148,163,184,0.05)' }, ticks: { color: '#94a3b8', font: { size: 9 }, callback: v => `£${(v / 1000).toFixed(0)}k` } },
            },
        },
    });
}

async function populateSimSKUSelect() {
    try {
        const data = await API.getRecommendations({ limit: 500 });
        const recs = data.results || [];
        // Deduplicate SKUs
        const uniqueRecs = [];
        const seen = new Set();
        recs.forEach(r => {
            if (r.description && !seen.has(r.description)) {
                seen.add(r.description);
                uniqueRecs.push(r);
                simRecs[r.description] = r;
            }
        });

        const sel = document.getElementById('sim-sku-select');
        sel.innerHTML = '<option value="">— Choose SKU —</option>'; // Clear existing

        // Sort alphabetically
        const sorted = uniqueRecs.sort((a, b) => a.description.localeCompare(b.description));

        sorted.forEach(r => {
            const opt = document.createElement('option');
            opt.value = r.description;
            opt.textContent = `${r.description.length > 50 ? r.description.substring(0, 47) + '...' : r.description} – ${r.analyst_category || ''}`;
            sel.appendChild(opt);
        });
    } catch (e) {
        console.error("Failed to populate simulator SKUs:", e);
    }
}
