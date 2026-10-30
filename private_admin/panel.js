(() => {
    'use strict';
    const base = document.body.dataset.base;
    const number = new Intl.NumberFormat();
    const clock = new Intl.DateTimeFormat(undefined, {hour: '2-digit', minute: '2-digit', second: '2-digit', timeZone: 'UTC'});
    let running = false;
    let chartData = null;
    const $ = id => document.getElementById(id);
    const text = (id, value) => { $(id).textContent = value; };
    const ms = value => `${Math.round(value).toLocaleString()} ms`;

    function element(tag, content, className) {
        const node = document.createElement(tag);
        if (content !== undefined) node.textContent = content;
        if (className) node.className = className;
        return node;
    }

    function table(id, rows, columns, empty) {
        const fragment = document.createDocumentFragment();
        if (!rows.length) {
            const tr = element('tr');
            const td = element('td', empty, 'empty');
            td.colSpan = columns.length;
            tr.append(td);
            fragment.append(tr);
        }
        for (const row of rows) {
            const tr = element('tr');
            for (const column of columns) {
                const value = column(row);
                const td = element('td');
                td.append(value instanceof Node ? value : document.createTextNode(String(value)));
                tr.append(td);
            }
            fragment.append(tr);
        }
        $(id).replaceChildren(fragment);
    }

    function breakdown(id, rows) {
        const total = rows.reduce((sum, row) => sum + row.count, 0);
        const fragment = document.createDocumentFragment();
        for (const row of rows) {
            const percent = total ? Math.round(row.count / total * 100) : 0;
            const wrapper = element('div', undefined, 'breakdown-row');
            const heading = element('div', undefined, 'breakdown-heading');
            const count = element('span', number.format(row.count));
            count.append(element('small', `${percent}%`));
            heading.append(element('span', row.name), count);
            const meter = element('meter');
            meter.min = 0;
            meter.max = total || 1;
            meter.value = row.count;
            meter.setAttribute('aria-label', `${row.name}: ${row.count} sessions, ${percent}%`);
            wrapper.append(heading, meter);
            fragment.append(wrapper);
        }
        if (!rows.length) fragment.append(element('p', 'No browser sessions in this period.', 'empty'));
        $(id).replaceChildren(fragment);
    }

    function chart(data) {
        chartData = data;
        const svgNS = 'http://www.w3.org/2000/svg';
        function svgNode(tag, attributes, content) {
            const node = document.createElementNS(svgNS, tag);
            for (const [key, value] of Object.entries(attributes)) node.setAttribute(key, String(value));
            if (content !== undefined) node.textContent = content;
            return node;
        }
        const width = Math.max(320, $('chart').clientWidth - 36);
        const svg = svgNode('svg', {viewBox: `0 0 ${width} 230`, role: 'img', 'aria-label': 'Hourly request counts, with errors highlighted'});
        const start = Math.floor((data.generated_at - data.hours * 3600) / 3600) * 3600;
        const end = Math.floor(data.generated_at / 3600) * 3600;
        const series = new Map(data.series.map(row => [row.at, row]));
        const bars = [];
        for (let at = start; at <= end; at += 3600) bars.push(series.get(at) || {at, requests: 0, errors: 0});
        const max = Math.max(4, ...bars.map(row => row.requests));
        const top = Math.ceil(max / 4) * 4;
        for (let i = 0; i <= 4; i++) {
            const y = 18 + i * 43;
            svg.append(svgNode('line', {x1: 42, x2: width - 13, y1: y, y2: y, class: 'chart-grid'}));
            svg.append(svgNode('text', {x: 30, y: y + 4, 'text-anchor': 'end', class: 'chart-label'}, number.format(top * (4 - i) / 4)));
        }
        const step = (width - 60) / bars.length;
        bars.forEach((row, index) => {
            const x = 44 + index * step;
            const height = row.requests / top * 172;
            const rect = svgNode('rect', {x, y: 190 - height, width: Math.max(1, step * .66), height, class: 'chart-bar'});
            rect.append(svgNode('title', {}, `${new Date(row.at * 1000).toISOString().slice(0, 16)} UTC: ${row.requests} requests, ${row.errors} errors`));
            svg.append(rect);
            if (row.errors) {
                const errorHeight = row.errors / top * 172;
                const errors = svgNode('rect', {x, y: 190 - errorHeight, width: Math.max(1, step * .66), height: errorHeight, class: 'chart-error'});
                errors.append(svgNode('title', {}, `${row.errors} errors in ${row.requests} requests`));
                svg.append(errors);
            }
            if (index === 0 || index === bars.length - 1 || index % Math.ceil(bars.length / 5) === 0) {
                const date = new Date(row.at * 1000);
                const label = data.hours > 24 ? date.toISOString().slice(5, 10) : date.toISOString().slice(11, 16);
                svg.append(svgNode('text', {x: Math.min(width - 25, x + step / 3), y: 217, 'text-anchor': 'middle', class: 'chart-label'}, label));
            }
        });
        $('chart').replaceChildren(svg);
        text('chart-period', `${number.format(data.totals.requests)} request${data.totals.requests === 1 ? '' : 's'} in this period`);
    }

    function render(data) {
        const t = data.totals;
        text('source-badge', data.source === 'production' ? 'PRODUCTION' : 'LOCAL');
        text('active-count', number.format(t.active));
        text('visitor-count', number.format(t.visitors));
        text('request-count', number.format(t.requests));
        text('pageview-count', number.format(t.pageviews));
        text('latency-count', ms(t.avg_ms));
        text('p95-count', ms(t.p95_ms));
        text('session-badge', number.format(t.active));
        text('errors-badge', number.format(t.errors));
        text('error-rate', `${t.requests ? (100 * t.errors / t.requests).toFixed(1) : '0.0'}%`);
        text('server-errors', number.format(t.server_errors));
        const minutes = Math.floor(data.uptime_seconds / 60);
        text('uptime', minutes > 59 ? `${Math.floor(minutes / 60)}h ${minutes % 60}m` : `${minutes}m`);
        text('storage', `${(data.storage_bytes / 1024 / 1024).toFixed(2)} MB`);
        text('health-title', !t.requests ? 'Ready for activity' : t.server_errors ? 'Errors recorded' : 'No server errors');
        text('health-description', !t.requests ? 'No requests in this period' : t.server_errors ? 'Review the error log below' : 'Based on requests in this period');
        text('health-ring', t.server_errors ? '!' : '✓');
        $('health-ring').classList.toggle('warning', Boolean(t.server_errors));
        table('sessions-body', data.active, [
            row => element('span', row.visitor, 'mono'),
            row => element('span', row.page, 'mono'),
            row => row.browser, row => row.system, row => row.device,
            row => `${Math.max(0, Math.floor(data.generated_at - row.last_seen))}s ago`
        ], 'No active sessions. Open the app in another tab to see activity here.');
        for (const field of ['browser', 'system', 'device']) breakdown(`${field}-breakdown`, data.breakdowns[field]);
        table('routes-body', data.routes, [
            row => element('span', row.route, 'mono'), row => number.format(row.requests),
            row => ms(row.avg_ms), row => number.format(row.errors)
        ], 'No requests recorded in this period.');
        table('errors-body', data.errors, [
            row => element('span', row.status, `status-badge${row.status >= 500 ? ' server' : ''}`),
            row => element('span', row.route, 'mono'), row => clock.format(new Date(row.at * 1000))
        ], 'All clear. No request errors in this period.');
        chart(data);
        text('last-updated', `Updated ${clock.format(new Date(data.generated_at * 1000))} UTC`);
        $('live-status').replaceChildren(element('i'), document.createTextNode(data.source === 'production' ? 'Production telemetry' : 'Local telemetry'));
        $('live-status').classList.remove('stale');
        $('load-error').hidden = true;
    }

    async function refresh() {
        if (running || document.visibilityState === 'hidden') return;
        running = true;
        try {
            const response = await fetch(`${base}/data?hours=${encodeURIComponent($('range').value)}`, {
                credentials: 'same-origin', cache: 'no-store', signal: AbortSignal.timeout(10000)
            });
            if (response.status === 401) {
                window.location.assign(`${base}/login`);
                return;
            }
            if (!response.ok) throw new Error('Telemetry is temporarily unavailable. Retrying automatically.');
            render(await response.json());
        } catch (error) {
            text('load-error', error.name === 'TimeoutError' ? 'Telemetry request timed out. Retrying automatically.' : 'Telemetry is temporarily unavailable. Retrying automatically.');
            $('load-error').hidden = false;
            $('live-status').replaceChildren(element('i'), document.createTextNode('Update delayed'));
            $('live-status').classList.add('stale');
        } finally { running = false; }
    }

    $('range').addEventListener('change', refresh);
    document.addEventListener('visibilitychange', refresh);
    window.addEventListener('resize', () => { if (chartData) chart(chartData); });
    document.querySelectorAll('.sidebar nav a').forEach(link => {
        link.addEventListener('click', () => {
            document.querySelectorAll('.sidebar nav a').forEach(item => item.classList.toggle('selected', item === link));
        });
    });
    refresh();
    setInterval(refresh, 15000);
})();
