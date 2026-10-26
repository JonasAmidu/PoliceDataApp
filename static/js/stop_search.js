document.addEventListener('DOMContentLoaded', () => {
    const V = PoliceViews;
    const status = document.getElementById('resultsStatus');
    const results = document.getElementById('stopResults');
    const filter = document.getElementById('stopFilter');
    let records = [], page = 0, controller;
    const pageSize = 50;
    const reason = record => record.object_of_search || 'Not recorded';
    function renderRows() {
        const filtered = records.filter(record => !filter.value || reason(record) === filter.value);
        const pages = Math.max(1, Math.ceil(filtered.length / pageSize));
        page = Math.min(page, pages - 1);
        document.getElementById('stopRows').innerHTML = filtered.slice(page * pageSize, (page + 1) * pageSize).map(record => {
            const date = new Date(record.datetime);
            const dateLabel = Number.isNaN(date.getTime()) ? 'Not recorded' : date.toLocaleDateString('en-GB');
            const outcome = record.outcome || record.outcome_object?.name || 'Not recorded';
            return `<tr><td>${V.escape(dateLabel)}</td><td>${V.escape(record.location?.street?.name || 'Location not published')}</td><td>${V.escape(reason(record))}</td><td>${V.escape(outcome)}</td><td>${V.escape(record.type || 'Not recorded')}</td></tr>`;
        }).join('') || '<tr><td colspan="5" class="text-muted">No records match this filter.</td></tr>';
        document.getElementById('pageStatus').textContent = `${filtered.length.toLocaleString()} records · Page ${page + 1} of ${pages}`;
        document.getElementById('previousPage').disabled = page === 0;
        document.getElementById('nextPage').disabled = page >= pages - 1;
    }
    filter.addEventListener('change', () => { page = 0; renderRows(); });
    document.getElementById('previousPage').addEventListener('click', () => { page--; renderRows(); });
    document.getElementById('nextPage').addEventListener('click', () => { page++; renderRows(); });
    V.queryForm(async (params, label) => {
        controller?.abort(); controller = new AbortController(); const current = controller;
        results.hidden = true; V.busy(status, 'Loading stop and search records…');
        try {
            const data = await V.json(`/api/stop-search/street?${params}`, {signal: current.signal});
            if (current.signal.aborted) return;
            if (!Array.isArray(data)) throw new Error('Unexpected stop and search response.');
            records = data; page = 0;
            V.message(status, `${label} · ${records.length.toLocaleString()} published records.`, records.length ? 'success' : 'info');
            if (!records.length) return;
            const withLocation = records.filter(r => r.location).length;
            const linked = records.filter(r => r.outcome_linked_to_object_of_search === true).length;
            const stats = [['Published searches', records.length], ['With a location', withLocation], ['Outcome linked to search object', linked]];
            document.getElementById('stopStatistics').innerHTML = stats.map(([name, value]) => `<div class="col-md-4"><div class="card h-100 border-0 bg-light"><div class="card-body"><div class="h3">${value.toLocaleString()}</div><p class="mb-0">${V.escape(name)}</p></div></div></div>`).join('');
            const counts = new Map(); records.forEach(r => counts.set(reason(r), (counts.get(reason(r)) || 0) + 1));
            const reasons = [...counts].sort((a, b) => b[1] - a[1]);
            filter.replaceChildren(new Option('All objects of search', '')); reasons.forEach(([name]) => filter.add(new Option(name, name)));
            document.getElementById('stopReasons').innerHTML = reasons.map(([name, value]) => `<div class="mb-3"><div class="d-flex justify-content-between gap-3 small mb-1"><span>${V.escape(name)}</span><span>${value.toLocaleString()} (${(100 * value / records.length).toFixed(1)}%)</span></div><div class="progress" style="height:8px"><div class="progress-bar" role="progressbar" aria-label="${V.escape(name)}" aria-valuenow="${value}" aria-valuemin="0" aria-valuemax="${records.length}" style="width:${100 * value / records.length}%"></div></div></div>`).join('');
            renderRows(); results.hidden = false;
        } catch (error) { if (!current.signal.aborted) V.message(status, error.message, 'danger'); }
    });
});
