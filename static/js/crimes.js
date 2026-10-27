document.addEventListener('DOMContentLoaded', () => {
    'use strict';
    const V = PoliceViews;
    const results = document.getElementById('crime-results');
    let controller;

    function message(text, kind) {
        const alert = document.createElement('div');
        alert.className = `alert alert-${kind}`;
        alert.textContent = text;
        results.replaceChildren(alert);
    }

    V.queryForm(async (query, label) => {
        controller?.abort();
        const current = new AbortController();
        controller = current;
        message('Loading crimes…', 'info');
        results.setAttribute('aria-busy', 'true');
        try {
            const crimes = await V.json(`/api/crimes/street?${query}`, {signal: current.signal});
            if (current.signal.aborted) return;
            if (!Array.isArray(crimes)) throw new Error('The crime service returned an unexpected response.');
            if (!crimes.length) {
                message(`No crimes recorded for this location and month. ${label}.`, 'warning');
                return;
            }
            const visible = crimes.slice(0, 100);
            message(`Found ${crimes.length.toLocaleString()} crimes. Showing ${visible.length.toLocaleString()}. ${label}.`, 'success');
            const list = document.createElement('div');
            visible.forEach(crime => {
                const row = document.createElement('div');
                row.className = 'border-start border-primary ps-2 mb-3';
                const category = document.createElement('strong');
                category.textContent = String(crime.category || 'Unknown category').replace(/-/g, ' ');
                const street = document.createElement('div');
                street.textContent = crime.location?.street?.name || 'Street unavailable';
                const outcome = document.createElement('small');
                outcome.className = 'text-muted';
                outcome.textContent = crime.outcome_status?.category || 'No outcome recorded';
                row.append(category, street, outcome);
                list.appendChild(row);
            });
            results.appendChild(list);
        } catch (error) {
            if (!current.signal.aborted) message(error.message, 'danger');
        } finally {
            if (!current.signal.aborted) results.removeAttribute('aria-busy');
        }
    });
});
