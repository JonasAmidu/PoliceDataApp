document.addEventListener('DOMContentLoaded', async () => {
    const V = PoliceViews;
    const container = document.getElementById('forces-container');
    const badge = document.getElementById('forcesCountBadge');
    const search = document.getElementById('forceSearchInput');
    const modal = new bootstrap.Modal(document.getElementById('forceModal'));
    const title = document.getElementById('modalForceName');
    const body = document.getElementById('modalForceBody');
    let forces = [], controller;
    function render() {
        const term = search.value.trim().toLowerCase();
        const visible = forces.filter(force => `${force.name} ${force.id}`.toLowerCase().includes(term));
        badge.textContent = `${visible.length} police forces`;
        container.replaceChildren();
        if (!visible.length) return V.message(container, 'No matching police forces found.');
        visible.forEach(force => {
            const card = document.createElement('div');
            card.className = 'col-md-6 col-lg-4 mb-4';
            card.innerHTML = `<div class="card h-100 shadow-sm border-0 force-card"><div class="card-body d-flex flex-column"><span class="text-muted small">${V.escape(force.id)}</span><h2 class="h5 my-3">${V.escape(force.name)}</h2><p class="text-muted small flex-grow-1">Explore contact details and local neighbourhood policing.</p><div class="d-flex gap-2"><button type="button" class="btn btn-primary btn-sm force-details">Force details</button><a class="btn btn-outline-primary btn-sm" href="/neighbourhoods?force=${encodeURIComponent(force.id)}">Neighbourhoods</a></div></div></div>`;
            card.querySelector('button').addEventListener('click', () => showForce(force.id));
            container.append(card);
        });
    }
    async function showForce(id) {
        controller?.abort(); controller = new AbortController(); const current = controller;
        title.textContent = 'Loading force…';
        document.getElementById('modalNeighbourhoodsBtn').href = `/neighbourhoods?force=${encodeURIComponent(id)}`;
        V.busy(body, 'Loading force details…'); modal.show();
        try {
            const force = await V.json(`/api/force/${encodeURIComponent(id)}`, {signal: current.signal});
            if (current.signal.aborted) return;
            title.textContent = force.name || id;
            const channels = Array.isArray(force.engagement_methods) ? force.engagement_methods : [];
            body.innerHTML = `<div class="row g-3 mb-4"><div class="col-md-6"><h2 class="h6 text-primary">Contact phone</h2><p>${V.escape(force.telephone || 'No phone number published')}</p></div><div class="col-md-6"><h2 class="h6 text-primary">Official website</h2><p class="text-break">${V.link(force.url, force.url || 'Not published')}</p></div></div><h2 class="h6">About the force</h2><p class="text-secondary" style="white-space:pre-line">${V.text(force.description) || 'No description published.'}</p>${channels.length ? `<h2 class="h6 mt-4">Engagement channels</h2><ul>${channels.map(channel => `<li>${V.link(channel.url, channel.title || channel.type || 'Website')}</li>`).join('')}</ul>` : ''}`;
        } catch (error) {
            if (!current.signal.aborted) { title.textContent = 'Force details'; V.message(body, error.message, 'danger'); }
        }
    }
    document.getElementById('forceModal').addEventListener('hidden.bs.modal', () => controller?.abort());
    search.addEventListener('input', render);
    document.getElementById('clearSearchBtn').addEventListener('click', () => { search.value = ''; render(); });
    try {
        const data = await V.json('/api/forces');
        if (!Array.isArray(data)) throw new Error('Unexpected force directory response.');
        forces = data; render();
    } catch (error) { badge.textContent = 'Forces unavailable'; V.message(container, error.message, 'danger'); }
});
