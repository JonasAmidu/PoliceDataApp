document.addEventListener('DOMContentLoaded', async () => {
    const V = PoliceViews;
    const select = document.getElementById('forceSelect');
    const list = document.getElementById('neighbourhoodsList');
    const detail = document.getElementById('neighbourhoodDetail');
    const filter = document.getElementById('neighbourhoodFilter');
    const count = document.getElementById('neighbourhoodsCount');
    const status = document.getElementById('selectionStatus');
    let items = [], selected = '', listRequest = 0, detailRequest = 0;

    function renderList() {
        const term = filter.value.trim().toLowerCase();
        const visible = items.filter(n => `${n.name} ${n.id}`.toLowerCase().includes(term));
        list.replaceChildren();
        if (!visible.length) return V.message(list, 'No matching neighbourhoods found.');
        visible.forEach(n => {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = `list-group-item list-group-item-action neighbourhood-item${n.id === selected ? ' active' : ''}`;
            button.textContent = n.name || n.id;
            button.setAttribute('aria-pressed', String(n.id === selected));
            button.addEventListener('click', () => loadDetail(select.value, n.id));
            list.append(button);
        });
    }

    async function loadDetail(force, id) {
        const requestId = ++detailRequest;
        selected = id;
        renderList();
        V.busy(detail, 'Loading neighbourhood profile, team, priorities and events…');
        try {
            const data = await V.json(`/api/neighbourhood/${encodeURIComponent(force)}/${encodeURIComponent(id)}`);
            if (requestId !== detailRequest) return;
            const d = data.details || {};
            const team = Array.isArray(data.team) ? data.team : [];
            const priorities = Array.isArray(data.priorities) ? data.priorities : [];
            const events = Array.isArray(data.events) ? data.events : [];
            const contacts = d.contact_details || {};
            const sections = [
                ['Overview', `<p class="text-secondary" style="white-space: pre-line">${V.text(d.description) || 'No neighbourhood overview published.'}</p>
                    <div class="mb-3">${V.link(d.url_force || contacts.website, 'Force webpage')}</div>
                    ${contacts.telephone ? `<p>Telephone: ${V.escape(contacts.telephone)}</p>` : ''}
                    ${contacts.email ? `<p>Email: ${V.escape(contacts.email)}</p>` : ''}
                    ${(d.locations || []).map(loc => `<div class="border rounded p-3 mb-2"><strong>${V.escape(loc.name || 'Contact point')}</strong><p class="mb-0">${V.escape(loc.address)} ${V.escape(loc.postcode)}</p></div>`).join('')}`],
                [`Policing team (${team.length})`, team.length ? team.map(member => `<article class="border rounded p-3 mb-2"><h3 class="h6">${V.escape(member.name || 'Officer')} <span class="badge bg-secondary">${V.escape(member.rank)}</span></h3><p class="mb-0">${V.text(member.bio)}</p></article>`).join('') : '<p class="text-muted">No team members published.</p>'],
                [`Priorities (${priorities.length})`, priorities.length ? priorities.map(p => `<article class="border rounded p-3 mb-2"><h3 class="h6">Community priority</h3><p>${V.text(p.issue)}</p>${p.action ? `<p class="mb-0"><strong>Action:</strong> ${V.text(p.action)}</p>` : ''}</article>`).join('') : '<p class="text-muted">No community priorities published.</p>'],
                [`Events (${events.length})`, events.length ? events.map(event => `<article class="border rounded p-3 mb-2"><h3 class="h6">${V.escape(event.title || 'Community event')}</h3><p>${V.escape(event.start_date || '')} ${V.escape(event.address || '')}</p><p class="mb-0">${V.text(event.description)}</p></article>`).join('') : '<p class="text-muted">No events published.</p>']
            ];
            detail.innerHTML = `<h2 class="h3">${V.escape(d.name || id)}</h2><p class="text-muted">${V.escape(select.selectedOptions[0]?.textContent)}</p>
                ${Array.isArray(data.warnings) && data.warnings.length ? `<div class="alert alert-warning">Some neighbourhood information could not be loaded: ${V.escape(data.warnings.join(', '))}</div>` : ''}
                <ul class="nav nav-pills flex-wrap gap-2 mb-4" role="tablist">${sections.map(([name], i) => `<li class="nav-item" role="presentation"><button class="nav-link ${i ? '' : 'active'}" id="neighbourhood-tab-${i}" data-bs-toggle="pill" data-bs-target="#neighbourhood-panel-${i}" type="button" role="tab" aria-controls="neighbourhood-panel-${i}" aria-selected="${!i}">${V.escape(name)}</button></li>`).join('')}</ul>
                <div class="tab-content">${sections.map(([, html], i) => `<section class="tab-pane fade ${i ? '' : 'show active'}" id="neighbourhood-panel-${i}" role="tabpanel" aria-labelledby="neighbourhood-tab-${i}">${html}</section>`).join('')}</div>`;
        } catch (error) {
            if (requestId === detailRequest) V.message(detail, error.message, 'danger');
        }
    }

    async function loadList() {
        const requestId = ++listRequest;
        ++detailRequest;
        items = []; selected = ''; filter.value = ''; filter.disabled = true; count.textContent = '…';
        V.busy(list, 'Loading neighbourhoods…');
        V.message(detail, 'Select a neighbourhood to view local policing information.');
        status.textContent = 'Loading neighbourhoods…';
        try {
            const data = await V.json(`/api/neighbourhoods/${encodeURIComponent(select.value)}`);
            if (requestId !== listRequest) return;
            if (!Array.isArray(data)) throw new Error('Unexpected neighbourhood response.');
            items = data; count.textContent = items.length; filter.disabled = false;
            status.textContent = `${items.length} neighbourhoods for ${select.selectedOptions[0]?.textContent}`;
            renderList();
            const preselected = new URLSearchParams(location.search).get('neighbourhood');
            const initial = items.find(n => n.id === preselected) || items[0];
            if (initial) loadDetail(select.value, initial.id);
            else V.message(detail, 'No neighbourhood data published for this force.');
        } catch (error) {
            if (requestId !== listRequest) return;
            count.textContent = '0'; status.textContent = 'Neighbourhoods could not be loaded.';
            V.message(list, error.message, 'danger');
        }
    }
    filter.addEventListener('input', renderList);
    select.addEventListener('change', loadList);
    try {
        const forces = await V.forces(select);
        const force = new URLSearchParams(location.search).get('force');
        if (forces.some(f => f.id === force)) { select.value = force; loadList(); }
    } catch (error) {
        select.replaceChildren(new Option('Unable to load forces', '')); V.message(detail, error.message, 'danger');
    }
});
