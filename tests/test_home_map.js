// Run with: node --test tests/test_home_map.js
// Restricted environments can add --experimental-test-isolation=none (Node 22).
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

class Element {
    constructor(attributes = {}) {
        this.attributes = attributes;
        this.value = '';
        this.innerHTML = '';
        this.textContent = '';
        this.innerText = '';
        this.validity = { valid: true };
        this.listeners = {};
        this.classes = new Set();
        this.classList = {
            add: name => this.classes.add(name),
            remove: name => this.classes.delete(name),
            toggle: (name, force) => force ? this.classes.add(name) : this.classes.delete(name)
        };
    }
    addEventListener(name, fn) { this.listeners[name] = fn; }
    getAttribute(name) { return this.attributes[name]; }
    querySelectorAll(selector) {
        const className = selector.replace('.', '');
        const matches = [...this.innerHTML.matchAll(/<(?:button|div)\b([^>]*)>/g)];
        return matches.filter(match => new RegExp(`class="[^"]*\\b${className}\\b`).test(match[1])).map(match => {
            const attributes = Object.fromEntries([...match[1].matchAll(/([\w-]+)="([^"]*)"/g)].map(item => [item[1], item[2]]));
            return new Element(attributes);
        });
    }
}

function fixture(handler) {
    const ids = ['location-search-form', 'location-search-input', 'date-select', 'btn-my-location', 'map-loader',
        'map-loader-text', 'map-feedback', 'results-status', 'inspector-body', 'category-filter-container',
        'stat-total-crimes', 'stat-top-category', 'stat-area-name', 'stat-date-period', 'preset-forces-select',
        'reset-inspector-btn', 'zoom-to-crime-btn'];
    const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
    const calls = [];
    const map = { handlers: {}, addLayer() {}, on(name, fn) { this.handlers[name] = fn; }, flyTo() {}, getZoom: () => 14 };
    const group = { layers: [], clearLayers() { this.layers = []; }, addLayers(layers) { this.layers.push(...layers); } };
    let clusterOptions;
    let boot;
    const layer = () => ({ addTo() { return this; } });
    const context = vm.createContext({
        console, URLSearchParams, AbortController, Date, navigator: {},
        document: {
            getElementById: id => elements[id] || null,
            querySelectorAll: () => [],
            addEventListener(name, fn) { if (name === 'DOMContentLoaded') boot = fn; }
        },
        fetch: async (url, options = {}) => {
            calls.push({ url, options });
            return handler(url, options);
        },
        L: {
            map: () => map, tileLayer: layer,
            control: { layers: layer, scale: layer },
            markerClusterGroup: options => { clusterOptions = options; return group; },
            point: (x, y) => [x, y], divIcon: options => options,
            marker: (coords, options) => ({
                coords, options, handlers: {}, addTo() { return this; },
                setLatLng() {}, bindTooltip(html) { this.tooltip = html; },
                bindPopup(html) { this.popup = html; }, on(name, fn) { this.handlers[name] = fn; }, openPopup() {}
            })
        }
    });
    vm.runInContext(fs.readFileSync('static/js/home_map.js', 'utf8'), context);
    return {
        elements, calls, group, map, get clusterOptions() { return clusterOptions; }, boot: () => boot(),
        submit: query => {
            elements['location-search-input'].value = query;
            return elements['location-search-form'].listeners.submit({ preventDefault() {} });
        },
        changeDate: date => {
            elements['date-select'].value = date;
            return elements['date-select'].listeners.change({ target: elements['date-select'] });
        }
    };
}
const response = (data, status = 200) => ({ ok: status >= 200 && status < 300, status, json: async () => data });
const crime = (category = 'burglary', extra = {}) => ({
    id: null, month: '2026-08', category,
    location: { latitude: '51.5', longitude: '0', street: { name: 'On or near High Street' } }, ...extra
});
const baseHandler = (url) => response(url === '/api/crimes/last-updated' ? { date: '2026-08-01' } : [crime()]);

test('initialization uses the latest published month and preserves overlapping-marker clustering', async () => {
    const app = fixture(baseHandler);
    await app.boot();
    assert.equal(app.elements['date-select'].value, '2026-08');
    assert.equal(app.elements['date-select'].max, '2026-08');
    assert.match(app.calls[1].url, /date=2026-08/);
    assert.equal(app.group.layers.length, 1, 'zero longitude must remain mappable');
    assert.equal(app.clusterOptions.disableClusteringAtZoom, undefined);
    assert.equal(app.clusterOptions.spiderfyOnMaxZoom, true);
});

test('postcode form reads the backend result envelope and uses only the cached API', async () => {
    const app = fixture(url => {
        if (url.startsWith('/api/geocode/postcode')) return response({ success: true, result: { lat: 53.48, lng: -2.24, postcode: 'M1 1AE', admin_district: 'Manchester' } });
        return baseHandler(url);
    });
    await app.boot();
    await app.submit('M1 1AE');
    assert.match(app.calls.at(-1).url, /lat=53.48&lng=-2.24/);
    assert.equal(app.elements['location-search-input'].value, 'M1 1AE (Manchester)');
    assert.equal(app.calls.filter(call => call.url.startsWith('http')).length, 0);
});

test('place results and incident fields cannot inject HTML into the inspector or popup', async () => {
    const payload = '<img src=x onerror="alert(1)">';
    const app = fixture(url => {
        if (url.startsWith('/api/geocode/search')) return response([{ lat: 51.5, lng: 0, display_name: payload }]);
        if (url === '/api/crimes/last-updated') return response({ date: '2026-08-01' });
        return response([crime('burglary', { persistent_id: payload, outcome_status: { category: payload }, location: { latitude: 51.5, longitude: 0, street: { name: payload } } })]);
    });
    await app.boot();
    await app.submit('Test town');
    assert.equal(app.elements['inspector-body'].innerHTML.includes(payload), false);
    assert.match(app.elements['inspector-body'].innerHTML, /&lt;img/);
    assert.equal(app.group.layers[0].popup.includes(payload), false);
    app.group.layers[0].handlers.click();
    assert.equal(app.elements['inspector-body'].innerHTML.includes(payload), false);
    assert.match(app.elements['inspector-body'].innerHTML, /&quot;/);
});

test('a superseded response cannot replace the most recent area or hide its loading indicator', async () => {
    let resolveOld;
    const app = fixture(url => {
        if (url.includes('date=2026-06')) return new Promise(resolve => { resolveOld = resolve; });
        if (url.includes('date=2026-07')) return response([crime('shoplifting')]);
        return baseHandler(url);
    });
    await app.boot();
    const old = app.changeDate('2026-06');
    await app.changeDate('2026-07');
    resolveOld(response([crime('robbery')]));
    await old;
    assert.match(app.group.layers[0].popup, /Shoplifting/);
    assert.equal(app.elements['stat-date-period'].innerText, '2026-07');
});

test('upstream failures remove previous markers and show an accessible error', async () => {
    const app = fixture(url => url.includes('date=2026-06') ? response({ error: 'Police data temporarily unavailable' }, 502) : baseHandler(url));
    await app.boot();
    assert.equal(app.group.layers.length, 1);
    await app.changeDate('2026-06');
    assert.equal(app.group.layers.length, 0);
    assert.match(app.elements['map-feedback'].textContent, /Police data temporarily unavailable/);
    assert.match(app.elements['map-feedback'].textContent, /Please try again shortly/);
    assert.doesNotMatch(app.elements['map-feedback'].textContent, /another area|another.*month/);
    assert.equal(app.elements['stat-total-crimes'].textContent, 'Unavailable');
});

test('missing metadata omits the date so the upstream latest default applies', async () => {
    const app = fixture(url => url === '/api/crimes/last-updated' ? response({}, 502) : response([]));
    await app.boot();
    assert.equal(app.calls[1].url.includes('date='), false);
    assert.equal(app.elements['stat-date-period'].innerText, 'Latest available');
});

test('clicking the map queries its coordinates without a reverse-geocoder request', async () => {
    const app = fixture(baseHandler);
    await app.boot();
    await app.map.handlers.click({ latlng: { lat: 52.5, lng: -1.5 } });
    // Leaflet event callbacks do not await their async handlers.
    await new Promise(resolve => setImmediate(resolve));
    assert.match(app.calls.at(-1).url, /lat=52.5&lng=-1.5/);
    assert.equal(app.calls.some(call => call.url.includes('reverse')), false);
    assert.match(app.elements['location-search-input'].value, /52.5000, -1.5000/);
});


test('non-JSON upstream errors retain an HTTP fallback and retry advice', async () => {
    const app = fixture(url => {
        if (url.includes('date=2026-06')) return { ok: false, status: 503, json: async () => { throw new SyntaxError('Unexpected token <'); } };
        return baseHandler(url);
    });
    await app.boot();
    await app.changeDate('2026-06');
    assert.match(app.elements['map-feedback'].textContent, /HTTP 503/);
    assert.match(app.elements['map-feedback'].textContent, /Please try again shortly/);
    assert.equal(app.group.layers.length, 0);
});
