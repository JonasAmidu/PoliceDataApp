document.addEventListener('DOMContentLoaded', () => {
    const V = PoliceViews;
    const status = document.getElementById('resultsStatus');
    const results = document.getElementById('analyticsResults');
    const palette = ['#2563eb','#0891b2','#16a34a','#ca8a04','#ea580c','#dc2626','#9333ea','#db2777','#4f46e5','#0d9488','#65a30d','#a16207','#475569','#7c3aed'];
    let categoryChart, outcomeChart, controller;
    V.queryForm(async (params, label) => {
        controller?.abort(); controller = new AbortController(); const current = controller;
        results.hidden = true; V.busy(status, 'Loading crime summary…');
        try {
            const data = await V.json(`/api/analytics/summary?${params}`, {signal: current.signal});
            if (current.signal.aborted) return;
            if (!Array.isArray(data.category_breakdown) || !Array.isArray(data.outcome_breakdown)) throw new Error('Unexpected analytics response.');
            categoryChart?.destroy(); outcomeChart?.destroy(); categoryChart = null; outcomeChart = null;
            const categories = data.category_breakdown, outcomes = data.outcome_breakdown;
            const total = data.total_crimes ?? data.total;
            V.message(status, `${label} · ${Number(total).toLocaleString()} crimes.`, total ? 'success' : 'info');
            if (!total) return;
            const stats = [['Crimes recorded', Number(total).toLocaleString()], ['Categories', categories.length], ['Most common category', categories[0]?.name || 'None']];
            document.getElementById('analyticsStatistics').innerHTML = stats.map(([name, value]) => `<div class="col-md-4"><div class="card h-100 border-0 bg-light"><div class="card-body"><div class="h4">${V.escape(value)}</div><p class="mb-0">${V.escape(name)}</p></div></div></div>`).join('');
            const rows = (items, key) => items.map(item => `<tr><td>${V.escape(item[key])}</td><td>${Number(item.count).toLocaleString()}</td><td>${Number(item.percentage).toFixed(1)}%</td></tr>`).join('');
            document.getElementById('categoryRows').innerHTML = rows(categories, 'name');
            document.getElementById('outcomeRows').innerHTML = rows(outcomes, 'status');
            results.hidden = false;
            document.getElementById('chartNotice').hidden = typeof Chart !== 'undefined';
            if (typeof Chart === 'undefined') return;
            categoryChart = new Chart(document.getElementById('categoryChart'), {
                type: 'bar', data: {labels: categories.map(c => c.name), datasets: [{label: 'Crimes', data: categories.map(c => c.count), backgroundColor: palette}]},
                options: {responsive: true, maintainAspectRatio: false, indexAxis: 'y', plugins: {legend: {display: false}}, scales: {x: {beginAtZero: true, ticks: {precision: 0}}}}
            });
            outcomeChart = new Chart(document.getElementById('outcomeChart'), {
                type: 'doughnut', data: {labels: outcomes.map(o => o.status), datasets: [{data: outcomes.map(o => o.count), backgroundColor: palette}]},
                options: {responsive: true, maintainAspectRatio: false, plugins: {legend: {position: 'bottom', labels: {boxWidth: 12, font: {size: 11}}}}}
            });
        } catch (error) { if (!current.signal.aborted) V.message(status, error.message, 'danger'); }
    });
});
