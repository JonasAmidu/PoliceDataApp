/* First-party presence only. No cookies, fingerprints, locations or third-party calls. */
(() => {
    'use strict';
    if (navigator.doNotTrack === '1' || navigator.globalPrivacyControl) return;
    let session;
    try {
        session = sessionStorage.getItem('police_telemetry_session');
        if (!/^[0-9a-f]{32}$/.test(session || '')) {
            session = Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, '0')).join('');
            sessionStorage.setItem('police_telemetry_session', session);
        }
    } catch (_) { return; }
    let previous = 0;
    function ping() {
        if (document.visibilityState !== 'visible' || navigator.onLine === false || Date.now() - previous < 60000) return;
        previous = Date.now();
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 2000);
        fetch('/api/telemetry/presence', {
            method: 'POST', credentials: 'omit', signal: controller.signal,
            referrerPolicy: 'no-referrer', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({session, page: location.pathname})
        }).catch(() => {}).finally(() => clearTimeout(timer));
    }
    window.addEventListener('load', ping, {once: true});
    setInterval(ping, 60000);
    document.addEventListener('visibilitychange', ping);
})();
