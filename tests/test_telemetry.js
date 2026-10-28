const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');

function fixture(options = {}) {
    let now = 100000;
    const events = {};
    const calls = [];
    const storage = new Map();
    const navigator = {onLine: true, ...options.navigator};
    const document = {visibilityState: 'visible', addEventListener: (name, fn) => { events[name] = fn; }};
    let tick;
    const context = vm.createContext({
        navigator, document, crypto: webcrypto, Uint8Array, AbortController,
        location: {pathname: '/crimes', search: '?q=secret-postcode'},
        Date: {now: () => now},
        sessionStorage: {
            getItem: key => { if (options.blockStorage) throw new Error('blocked'); return storage.get(key); },
            setItem: (key, value) => storage.set(key, value)
        },
        window: {addEventListener: (name, fn) => { events[name] = fn; }},
        setInterval: (fn, ms) => { assert.equal(ms, 60000); tick = fn; },
        setTimeout: () => 1, clearTimeout() {},
        fetch: (url, config) => { calls.push({url, config}); return options.failure ? Promise.reject(new Error('offline')) : Promise.resolve({status: 204}); }
    });
    vm.runInContext(fs.readFileSync('static/js/telemetry.js', 'utf8'), context);
    return {events, calls, navigator, document, storage, tick: () => tick?.(), advance: amount => { now += amount; }};
}

test('waits for load, sends a small first-party payload without cookies or queries, and limits frequency', () => {
    const f = fixture();
    assert.equal(f.calls.length, 0);
    f.events.load();
    assert.equal(f.calls.length, 1);
    assert.equal(f.calls[0].url, '/api/telemetry/presence');
    assert.equal(f.calls[0].config.credentials, 'omit');
    const body = JSON.parse(f.calls[0].config.body);
    assert.deepEqual(Object.keys(body).sort(), ['page', 'session']);
    assert.equal(body.page, '/crimes');
    assert.match(body.session, /^[a-f0-9]{32}$/);
    assert.ok(f.calls[0].config.body.length < 128);
    f.events.visibilitychange();
    f.tick();
    assert.equal(f.calls.length, 1);
    f.advance(60000);
    f.tick();
    assert.equal(f.calls.length, 2);
});

test('hidden tabs and offline browsers send no heartbeats', () => {
    const f = fixture();
    f.document.visibilityState = 'hidden';
    f.events.load();
    assert.equal(f.calls.length, 0);
    f.document.visibilityState = 'visible';
    f.navigator.onLine = false;
    f.tick();
    assert.equal(f.calls.length, 0);
    f.navigator.onLine = true;
    f.events.visibilitychange();
    assert.equal(f.calls.length, 1);
});

test('privacy preferences and blocked session storage disable presence', () => {
    for (const options of [{navigator: {doNotTrack: '1'}}, {navigator: {globalPrivacyControl: true}}, {blockStorage: true}]) {
        const f = fixture(options);
        assert.equal(f.events.load, undefined);
        assert.equal(f.calls.length, 0);
    }
});

test('network failures are swallowed without affecting app scripts', async () => {
    const f = fixture({failure: true});
    assert.doesNotThrow(() => f.events.load());
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(f.calls.length, 1);
});
