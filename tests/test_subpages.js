const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

const source = name => fs.readFileSync(path.join(__dirname, '../static/js', name), 'utf8');
function helpers(overrides = {}) {
    const context = {URL, URLSearchParams, window: {}, ...overrides};
    vm.runInNewContext(source('subpage_common.js'), context);
    return context.window.PoliceViews;
}

// Exercise the same helpers used for every upstream-sourced link and string.
test('upstream strings remain text and external links reject executable schemes', () => {
    const V = helpers();
    assert.equal(V.escape('<img src=x onerror="run()">\'&'), '&lt;img src=x onerror=&quot;run()&quot;&gt;&#39;&amp;');
    for (const value of ['javascript:alert(1)', 'data:text/html,<script>bad()</script>', '//example.com', '/relative', 'mailto:a@example.com']) {
        assert.equal(V.webURL(value), '', value);
        assert.equal(V.link(value, '<unsafe>'), '&lt;unsafe&gt;');
    }
    assert.equal(V.webURL('https://police.example/info?a=1&b=2'), 'https://police.example/info?a=1&amp;b=2');
    assert.match(V.link('https://police.example', 'Official site'), /rel="noopener noreferrer"/);
});

test('cancellation during response parsing remains an abort instead of a visible error', async () => {
    const aborted = Object.assign(new Error('Request cancelled'), {name: 'AbortError'});
    const V = helpers({fetch: async () => ({ok: true, json: async () => { throw aborted; }})});
    await assert.rejects(V.json('/api/forces'), error => error === aborted);
    const malformed = helpers({fetch: async () => ({ok: true, json: async () => { throw new SyntaxError('Invalid JSON'); }})});
    await assert.rejects(malformed.json('/api/forces'), /unreadable response/);
});

function deferred() {
    let resolve;
    const promise = new Promise(done => { resolve = done; });
    return {promise, resolve};
}
class Element {
    constructor() { this.value = ''; this.children = []; this.innerHTML = ''; this.textContent = ''; this.events = {}; this.attributes = {}; }
    addEventListener(event, handler) { this.events[event] = handler; }
    replaceChildren(...children) { this.children = children; this.innerHTML = ''; }
    append(child) { this.children.push(child); }
    setAttribute(key, value) { this.attributes[key] = value; }
}

test('changing forces and neighbourhoods ignores stale list and detail responses', async () => {
    const ids = ['forceSelect', 'neighbourhoodsList', 'neighbourhoodDetail', 'neighbourhoodFilter', 'neighbourhoodsCount', 'selectionStatus'];
    const elements = Object.fromEntries(ids.map(id => [id, new Element()]));
    const requests = new Map();
    let ready;
    const V = helpers();
    V.forces = async () => [{id: 'alpha'}, {id: 'beta'}];
    // Rich-text parsing belongs to the browser; this case isolates request ordering.
    V.text = V.escape;
    V.json = url => { const pending = deferred(); requests.set(url, pending); return pending.promise; };
    V.busy = (element, text) => { element.innerHTML = text; };
    V.message = (element, text) => { element.innerHTML = text; };
    const context = {
        PoliceViews: V, URLSearchParams, location: {search: ''},
        document: {getElementById: id => elements[id], createElement: () => new Element(), addEventListener: (_, handler) => { ready = handler; }}
    };
    vm.runInNewContext(source('neighbourhoods.js'), context);
    await ready();
    elements.forceSelect.value = 'alpha';
    elements.forceSelect.selectedOptions = [{textContent: 'Alpha Police'}];
    const alpha = elements.forceSelect.events.change();
    elements.forceSelect.value = 'beta';
    elements.forceSelect.selectedOptions = [{textContent: 'Beta Police'}];
    const beta = elements.forceSelect.events.change();
    requests.get('/api/neighbourhoods/beta').resolve([{id: 'b1', name: 'Beta One'}, {id: 'b2', name: 'Beta Two'}]);
    await beta;
    requests.get('/api/neighbourhoods/alpha').resolve([{id: 'a1', name: 'Wrong force'}]);
    await alpha;
    assert.equal(elements.neighbourhoodsCount.textContent, 2);
    assert.deepEqual(elements.neighbourhoodsList.children.map(n => n.textContent), ['Beta One', 'Beta Two']);
    assert.equal(requests.has('/api/neighbourhood/alpha/a1'), false);

    const second = elements.neighbourhoodsList.children[1].events.click();
    requests.get('/api/neighbourhood/beta/b2').resolve({details: {name: 'Selected neighbourhood'}, team: [], events: [], priorities: [], warnings: ['Team service unavailable']});
    await second;
    assert.match(elements.neighbourhoodDetail.innerHTML, /Selected neighbourhood/);
    assert.match(elements.neighbourhoodDetail.innerHTML, /Team service unavailable/);
    const selectedMarkup = elements.neighbourhoodDetail.innerHTML;
    requests.get('/api/neighbourhood/beta/b1').resolve({details: {name: 'Stale neighbourhood'}, team: [], events: []});
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(elements.neighbourhoodDetail.innerHTML, selectedMarkup);
});
