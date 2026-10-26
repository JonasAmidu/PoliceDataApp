(() => {
    'use strict';
    const form = document.getElementById('crime-search');
    const results = document.getElementById('crime-results');
    const month = document.getElementById('date');
    let requestId = 0;
    let monthEdited = false;
    month.addEventListener('input', () => { monthEdited = true; });

    async function json(url) {
        const response = await fetch(url);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Unable to load crime data. Please try again.');
        return data;
    }

    json('/api/crimes/last-updated').then(data => {
        if (typeof data.date === 'string' && /^\d{4}-\d{2}/.test(data.date)) {
            month.max = data.date.slice(0, 7);
            if (!monthEdited) month.value = month.max;
        }
    }).catch(() => { /* A blank month lets the upstream API select its latest data. */ });

    function message(text, kind) {
        const alert = document.createElement('div');
        alert.className = `alert alert-${kind}`;
        alert.textContent = text;
        results.replaceChildren(alert);
    }

    form.addEventListener('submit', async event => {
        event.preventDefault();
        const current = ++requestId;
        const query = new URLSearchParams({
            lat: document.getElementById('lat').value,
            lng: document.getElementById('lng').value
        });
        if (month.value) query.set('date', month.value);
        message('Loading crimes…', 'info');
        results.setAttribute('aria-busy', 'true');
        try {
            const crimes = await json(`/api/crimes/street?${query}`);
            if (current !== requestId) return;
            if (!Array.isArray(crimes)) throw new Error('The crime service returned an unexpected response.');
            if (!crimes.length) {
                message('No crimes recorded for this location and month.', 'warning');
                return;
            }
            const visible = crimes.slice(0, 100);
            message(`Found ${crimes.length.toLocaleString()} crimes. Showing ${visible.length.toLocaleString()}.`, 'success');
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
            if (current === requestId) message(error.message, 'danger');
        } finally {
            if (current === requestId) results.removeAttribute('aria-busy');
        }
    });
})();
