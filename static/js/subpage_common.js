/* Shared helpers for the police data browser views. */
window.PoliceViews = (() => {
    const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
    const text = value => {
        const doc = new DOMParser().parseFromString(String(value ?? ''), 'text/html');
        doc.querySelectorAll('script,style').forEach(node => node.remove());
        return escape(doc.body.textContent || '');
    };
    const webURL = value => {
        try {
            const url = new URL(value);
            return ['https:', 'http:'].includes(url.protocol) ? escape(url.href) : '';
        } catch (_) { return ''; }
    };
    const link = (url, label) => {
        const safe = webURL(url);
        return safe ? `<a href="${safe}" target="_blank" rel="noopener noreferrer">${escape(label)}</a>` : escape(label);
    };
    async function json(url, options = {}) {
        const response = await fetch(url, options);
        let data;
        try { data = await response.json(); } catch (error) {
            if (error.name === 'AbortError') throw error;
            throw new Error('The service returned an unreadable response. Please try again.');
        }
        if (!response.ok || data?.success === false) throw new Error(data?.error || 'The data service is unavailable. Please try again.');
        return data;
    }
    const message = (element, value, type = 'info') => { element.innerHTML = `<div class="alert alert-${type}" role="status">${escape(value)}</div>`; };
    const busy = (element, label) => { element.innerHTML = `<div class="py-4 text-center" role="status"><span class="spinner-border spinner-border-sm text-primary me-2"></span>${escape(label)}</div>`; };
    async function forces(select) {
        const data = await json('/api/forces');
        if (!Array.isArray(data)) throw new Error('The force directory returned an unexpected response.');
        select.replaceChildren(new Option('Choose a police force', ''));
        data.forEach(force => select.add(new Option(force.name, force.id)));
        return data;
    }
    async function latestMonth(input, status) {
        try {
            const data = await json('/api/crimes/last-updated');
            if (/^\d{4}-\d{2}/.test(data.date || '')) {
                input.max = data.date.slice(0, 7);
                if (!input.value) input.value = input.max;
                if (status) status.textContent = `Latest published month: ${input.max}`;
            }
        } catch (_) { if (status) status.textContent = 'Leave the month blank to use the latest published data.'; }
    }
    async function locate(query, signal) {
        // Try postcode lookup only for postcode-shaped text; place lookup is explicit, never per keystroke.
        if (/^[A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2}$/i.test(query)) {
            const data = await json(`/api/geocode/postcode?q=${encodeURIComponent(query)}`, {signal});
            return [{lat: data.result.lat, lng: data.result.lng, display_name: data.result.postcode || query}];
        }
        const data = await json(`/api/geocode/search?q=${encodeURIComponent(query)}`, {signal});
        if (!Array.isArray(data)) throw new Error('Location search returned an unexpected response.');
        return data.filter(item => Number.isFinite(Number(item.lat)) && Number.isFinite(Number(item.lng)));
    }
    function queryForm(onLoad) {
        const form = document.getElementById('dataQueryForm');
        const mode = document.getElementById('queryMode');
        const force = document.getElementById('queryForce');
        const fields = document.getElementById('locationFields');
        const matches = document.getElementById('locationMatches');
        const searchButton = document.getElementById('findLocation');
        const searchInput = document.getElementById('locationQuery');
        const lat = document.getElementById('queryLat');
        const lng = document.getElementById('queryLng');
        const month = document.getElementById('queryMonth');
        let searchController;
        const switchMode = () => {
            const forceMode = mode?.value === 'force';
            fields.disabled = forceMode;
            if (force) { document.getElementById('forceFields').hidden = !forceMode; force.disabled = !forceMode; force.required = forceMode; }
        };
        mode?.addEventListener('change', switchMode);
        switchMode();
        if (force) forces(force).catch(error => { force.replaceChildren(new Option('Unable to load forces', '')); message(document.getElementById('resultsStatus'), error.message, 'danger'); });
        latestMonth(month, document.getElementById('monthHint'));
        searchInput.addEventListener('input', () => { searchController?.abort(); searchButton.disabled = false; matches.replaceChildren(); });
        async function search() {
            const query = searchInput.value.trim();
            if (!query) return message(matches, 'Enter a postcode or place name.', 'warning');
            searchController?.abort();
            const controller = new AbortController(); searchController = controller;
            searchButton.disabled = true; busy(matches, 'Finding locations…');
            try {
                const places = await locate(query, controller.signal);
                if (controller.signal.aborted) return;
                matches.replaceChildren();
                if (!places.length) return message(matches, 'No UK locations found. Try a nearby town or postcode.', 'warning');
                places.forEach(place => {
                    const button = document.createElement('button');
                    button.type = 'button'; button.className = 'list-group-item list-group-item-action'; button.textContent = place.display_name;
                    button.addEventListener('click', () => {
                        lat.value = place.lat; lng.value = place.lng;
                        document.getElementById('selectedLocation').textContent = place.display_name;
                        matches.replaceChildren();
                    }); matches.append(button);
                });
            } catch (error) { if (!controller.signal.aborted) message(matches, error.message, 'danger'); }
            finally { if (searchController === controller) searchButton.disabled = false; }
        }
        searchButton.addEventListener('click', search);
        searchInput.addEventListener('keydown', event => { if (event.key === 'Enter') { event.preventDefault(); search(); } });
        [lat, lng].forEach(input => input.addEventListener('input', () => { document.getElementById('selectedLocation').textContent = 'Custom coordinates selected.'; }));
        form.addEventListener('submit', event => {
            event.preventDefault();
            const params = new URLSearchParams();
            if (mode?.value === 'force') params.set('force', force.value);
            else { params.set('lat', lat.value); params.set('lng', lng.value); }
            if (month.value) params.set('date', month.value);
            const label = mode?.value === 'force' ? force.selectedOptions[0].textContent : `Near ${Number(lat.value).toFixed(4)}, ${Number(lng.value).toFixed(4)}`;
            onLoad(params, `${label} · ${month.value || 'latest published month'}`);
        });
    }
    return {escape, text, webURL, link, json, message, busy, forces, latestMonth, locate, queryForm};
})();
