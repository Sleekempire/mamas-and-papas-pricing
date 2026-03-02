/**
 * table.js — Sortable, filterable recommendations table.
 */

let allRecs = [];
let sortCol = 'expected_revenue';
let sortDir = 'desc';
let currentPage = 1;
const PAGE_SIZE = 20;

async function loadRecommendations(filters = {}) {
    try {
        const data = await API.getRecommendations({ ...filters, limit: 500 });
        allRecs = data.results || [];
        currentPage = 1;
        renderTable();
        populateProductDropdown(allRecs);
        document.getElementById('rec-subtitle').textContent = `${allRecs.length} recommendations`;
    } catch (err) {
        showTableError(err.message);
    }
}

function populateProductDropdown(recs) {
    const datalist = document.getElementById('sku-datalist');
    if (!datalist) return;
    const sorted = [...recs].sort((a, b) => (a.description || '').localeCompare(b.description || ''));
    datalist.innerHTML = sorted.map(r => {
        const d = r.description || '';
        return `<option value="${d.replace(/"/g, '&quot;')}"></option>`;
    }).join('');
}

function renderTable() {
    const sorted = sortRecs([...allRecs]);
    const total = sorted.length;
    const start = (currentPage - 1) * PAGE_SIZE;
    const page = sorted.slice(start, start + PAGE_SIZE);

    const tbody = document.getElementById('rec-tbody');
    if (page.length === 0) {
        tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;padding:2rem;color:var(--text-muted);">No recommendations found for current filters.</td></tr>`;
        return;
    }

    tbody.innerHTML = page.map(r => {
        const changeClass = (r.price_change_pct || 0) > 0.001 ? 'price-up' : (r.price_change_pct || 0) < -0.001 ? 'price-down' : 'price-neutral';
        const changePct = ((r.price_change_pct || 0) * 100).toFixed(1);
        const changeSign = r.price_change_pct > 0 ? '+' : '';
        const conf = r.confidence_score || 0;
        const elClass = r.elasticity_class || 'Neutral';
        const desc = r.description || r.sku || '—';
        return `
      <tr data-desc="${desc}" onclick="onRecRowClick('${desc}','${r.target_date}')">
        <td><span class="sku-badge" title="${desc}">${desc.length > 28 ? desc.slice(0, 26) + '…' : desc}</span></td>
        <td style="color:var(--text-secondary);font-size:0.8rem;">${r.analyst_category || r.product_category || '—'}</td>
        <td>£${(r.current_price || 0).toFixed(2)}</td>
        <td style="font-weight:600;">£${(r.recommended_price || 0).toFixed(2)}</td>
        <td class="${changeClass}">${changeSign}${changePct}%</td>
        <td>£${(r.expected_revenue || 0).toLocaleString('en-GB', { maximumFractionDigits: 0 })}</td>
        <td>£${(r.expected_margin || 0).toLocaleString('en-GB', { maximumFractionDigits: 0 })}</td>
        <td><span class="elasticity-badge ${elClass}">${elClass}</span></td>
        <td>
          <div class="confidence-bar">
            <div class="confidence-track"><div class="confidence-fill" style="width:${(conf * 100).toFixed(0)}%"></div></div>
            <span class="confidence-val">${(conf * 100).toFixed(0)}%</span>
          </div>
        </td>
      </tr>`;
    }).join('');

    renderPagination(total);
}

function sortRecs(recs) {
    return recs.sort((a, b) => {
        let av = a[sortCol] ?? '';
        let bv = b[sortCol] ?? '';
        if (typeof av === 'string') av = av.toLowerCase();
        if (typeof bv === 'string') bv = bv.toLowerCase();
        if (av < bv) return sortDir === 'asc' ? -1 : 1;
        if (av > bv) return sortDir === 'asc' ? 1 : -1;
        return 0;
    });
}

function renderPagination(total) {
    const totalPages = Math.ceil(total / PAGE_SIZE);
    document.getElementById('rec-pagination-info').textContent =
        `${Math.min((currentPage - 1) * PAGE_SIZE + 1, total)}–${Math.min(currentPage * PAGE_SIZE, total)} of ${total}`;

    const btns = document.getElementById('rec-pagination-btns');
    btns.innerHTML = '';
    let lastAdded = 0;
    for (let i = 1; i <= totalPages; i++) {
        if (totalPages > 8 && i > 3 && i < totalPages - 2 && Math.abs(i - currentPage) > 1) {
            continue;
        }
        if (lastAdded < i - 1) {
            const span = document.createElement('span');
            span.style.cssText = 'padding:0 4px;color:var(--text-muted);';
            span.textContent = '…';
            btns.appendChild(span);
        }
        const btn = document.createElement('button');
        btn.className = 'page-btn' + (i === currentPage ? ' active' : '');
        btn.textContent = i;
        btn.addEventListener('click', () => { currentPage = i; renderTable(); });
        btns.appendChild(btn);
        lastAdded = i;
    }
}

function showTableError(msg) {
    const tbody = document.getElementById('rec-tbody');
    tbody.innerHTML = `<tr><td colspan="9" style="text-align:center;padding:2rem;color:var(--brand-danger);">Error: ${msg}</td></tr>`;
}

function onRecRowClick(desc, date) {
    navigateTo('sku-detail');
    const input = document.getElementById('detail-sku-select');
    if (input) input.value = desc;
    initSKUDetailPage();
    loadSKUDetail(desc, date);
}

function initTableControls() {
    // Sort headers
    document.querySelectorAll('.data-table th[data-sort]').forEach(th => {
        th.addEventListener('click', () => {
            const col = th.dataset.sort;
            if (sortCol === col) sortDir = sortDir === 'asc' ? 'desc' : 'asc';
            else { sortCol = col; sortDir = 'desc'; }
            document.querySelectorAll('.data-table th').forEach(h => h.classList.remove('sort-asc', 'sort-desc'));
            th.classList.add(`sort-${sortDir}`);
            renderTable();
        });
    });

    // Filters
    document.getElementById('apply-filter-btn').addEventListener('click', () => {
        loadRecommendations({
            sku: document.getElementById('filter-sku').value.trim() || undefined,
            category: document.getElementById('filter-cat').value.trim() || undefined,
            date: document.getElementById('filter-date').value || undefined,
        });
    });

    document.getElementById('clear-filter-btn').addEventListener('click', () => {
        document.getElementById('filter-sku').value = '';
        document.getElementById('filter-cat').value = '';
        document.getElementById('filter-date').value = '';
        loadRecommendations();
    });

    // Export aggregated CSV
    document.getElementById('export-btn').addEventListener('click', () => {
        const headers = ['Product', 'Category', 'CurrentPrice', 'RecommendedPrice', 'Change%', 'ExpectedRevenue', 'ExpectedMargin', 'Elasticity'];
        const rows = allRecs.map(r => [
            r.description || r.sku, r.analyst_category || r.product_category || '',
            r.current_price?.toFixed(2), r.recommended_price?.toFixed(2),
            ((r.price_change_pct || 0) * 100).toFixed(2),
            r.expected_revenue?.toFixed(0), r.expected_margin?.toFixed(0),
            r.elasticity_class || '',
        ]);
        const csv = [headers, ...rows].map(r => r.join(',')).join('\n');
        const blob = new Blob([csv], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a'); a.href = url; a.download = 'pricing_recommendations_summary.csv';
        a.click(); URL.revokeObjectURL(url);
    });
}
