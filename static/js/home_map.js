/**
 * PoliceDataUK - Interactive Crime Map & Location Search
 * Handles Leaflet map, MarkerCluster, category filtering, human-form geocoding, and crime inspection.
 */

(function () {
    'use strict';

    // Popular UK Presets (Forces & Cities)
    const PRESET_LOCATIONS = {
        'london': { name: 'London (Westminster)', lat: 51.4998, lng: -0.1246, zoom: 14 },
        'manchester': { name: 'Manchester City Centre', lat: 53.4808, lng: -2.2426, zoom: 14 },
        'birmingham': { name: 'Birmingham Central', lat: 52.4814, lng: -1.8998, zoom: 14 },
        'leeds': { name: 'Leeds Centre', lat: 53.7997, lng: -1.5492, zoom: 14 },
        'bristol': { name: 'Bristol Harbourside', lat: 51.4545, lng: -2.5879, zoom: 14 },
        'liverpool': { name: 'Liverpool Waterfront', lat: 53.4072, lng: -2.9916, zoom: 14 },
        'newcastle': { name: 'Newcastle City Centre', lat: 54.9783, lng: -1.6178, zoom: 14 },
        'cardiff': { name: 'Cardiff Central', lat: 51.4816, lng: -3.1791, zoom: 14 },
        'sheffield': { name: 'Sheffield Centre', lat: 53.3811, lng: -1.4701, zoom: 14 },
        'nottingham': { name: 'Nottingham Market Square', lat: 52.9548, lng: -1.1581, zoom: 14 },
        'cambridge': { name: 'Cambridge Centre', lat: 52.2053, lng: 0.1218, zoom: 14 },
        'oxford': { name: 'Oxford City Centre', lat: 51.7520, lng: -1.2577, zoom: 14 }
    };

    // Category Metadata for Icons and Colors
    const CATEGORY_META = {
        'all': { name: 'All Categories', color: '#1e293b', icon: 'fa-layer-group' },
        'violent-crime': { name: 'Violent Crime', color: '#ef4444', icon: 'fa-fist-raised' },
        'anti-social-behaviour': { name: 'Anti-Social Behaviour', color: '#f59e0b', icon: 'fa-bullhorn' },
        'other-theft': { name: 'Other Theft', color: '#3b82f6', icon: 'fa-shopping-bag' },
        'theft-from-the-person': { name: 'Theft from Person', color: '#2563eb', icon: 'fa-hand-paper' },
        'shoplifting': { name: 'Shoplifting', color: '#0284c7', icon: 'fa-store' },
        'bicycle-theft': { name: 'Bicycle Theft', color: '#0ea5e9', icon: 'fa-bicycle' },
        'burglary': { name: 'Burglary', color: '#ec4899', icon: 'fa-door-open' },
        'robbery': { name: 'Robbery', color: '#dc2626', icon: 'fa-mask' },
        'criminal-damage-arson': { name: 'Criminal Damage & Arson', color: '#ea580c', icon: 'fa-fire' },
        'vehicle-crime': { name: 'Vehicle Crime', color: '#8b5cf6', icon: 'fa-car-crash' },
        'drugs': { name: 'Drugs', color: '#10b981', icon: 'fa-capsules' },
        'public-order': { name: 'Public Order', color: '#06b6d4', icon: 'fa-users' },
        'possession-of-weapons': { name: 'Weapons Possession', color: '#991b1b', icon: 'fa-gavel' },
        'other-crime': { name: 'Other Crime', color: '#64748b', icon: 'fa-tag' }
    };

    // State Variables
    let map = null;
    let markerClusterGroup = null;
    let searchLocationMarker = null;
    let allLoadedCrimes = [];
    let currentFilter = 'all';
    let currentCoords = { lat: 51.4998, lng: -0.1246 };
    let currentAreaName = 'London (Westminster)';
    let requestVersion = 0;
    let requestController = null;

    function escapeHtml(value) {
        return String(value ?? '').replace(/[&<>"']/g, char => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        })[char]);
    }

    function beginRequest() {
        if (requestController) requestController.abort();
        requestController = new AbortController();
        return ++requestVersion;
    }

    function showError(message) {
        const feedback = document.getElementById('map-feedback');
        if (feedback) {
            feedback.textContent = message;
            feedback.classList.remove('d-none');
        }
    }

    function clearError() {
        document.getElementById('map-feedback')?.classList.add('d-none');
    }

    function validCoords(lat, lng) {
        return lat !== null && lat !== '' && lng !== null && lng !== '' &&
            Number.isFinite(Number(lat)) && Number.isFinite(Number(lng)) &&
            Math.abs(Number(lat)) <= 90 && Math.abs(Number(lng)) <= 180;
    }

    function categoryOf(crime) {
        return typeof crime.category === 'string' && crime.category ? crime.category : 'other-crime';
    }

    function categoryMeta(category) {
        return Object.prototype.hasOwnProperty.call(CATEGORY_META, category) ? CATEGORY_META[category] : null;
    }

    // Format human-readable category name
    function formatCategoryName(cat) {
        if (categoryMeta(cat)) return categoryMeta(cat).name;
        return String(cat || 'other-crime').split('-').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    }

    // Get category color
    function getCategoryColor(cat) {
        return (categoryMeta(cat) && categoryMeta(cat).color) || '#64748b';
    }

    // Get category icon
    function getCategoryIcon(cat) {
        return (categoryMeta(cat) && categoryMeta(cat).icon) || 'fa-exclamation-circle';
    }

    // Format outcome status string
    function formatOutcome(outcome) {
        if (!outcome || !outcome.category) {
            return { text: 'Outcome not recorded', badgeClass: 'badge-outcome-investigating' };
        }
        const text = String(outcome.category);
        const lower = text.toLowerCase();
        if (lower.includes('investigation complete') || lower.includes('no suspect')) {
            return { text: text, badgeClass: 'badge-outcome-closed' };
        }
        if (lower.includes('court') || lower.includes('charged') || lower.includes('prosecut')) {
            return { text: text, badgeClass: 'badge-outcome-court' };
        }
        if (lower.includes('formal action') || lower.includes('resolved') || lower.includes('caution')) {
            return { text: text, badgeClass: 'badge-outcome-resolved' };
        }
        return { text: text, badgeClass: 'badge-outcome-investigating' };
    }

    // Initialize Leaflet Map
    function initMap() {
        if (map) return;

        map = L.map('crime-map', {
            center: [currentCoords.lat, currentCoords.lng],
            zoom: 14,
            zoomControl: true,
            preferCanvas: true
        });

        // Base tile layers
        const cartoVoyager = L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://carto.com/">CARTO</a>',
            maxZoom: 19
        }).addTo(map);

        const osmStandard = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
            maxZoom: 19
        });

        L.control.layers({
            "Light Clean Map": cartoVoyager,
            "Standard OpenStreetMap": osmStandard
        }, null, { position: 'topright' }).addTo(map);

        L.control.scale({ imperial: true, metric: true, position: 'bottomleft' }).addTo(map);

        // MarkerCluster Group with custom cluster icons
        markerClusterGroup = L.markerClusterGroup({
            showCoverageOnHover: false,
            zoomToBoundsOnClick: true,
            spiderfyOnMaxZoom: true,
            maxClusterRadius: 50,
            iconCreateFunction: function (cluster) {
                const count = cluster.getChildCount();
                let sizeClass = 'marker-cluster-small';
                let diameter = 36;
                if (count > 80) {
                    sizeClass = 'marker-cluster-large';
                    diameter = 48;
                } else if (count > 25) {
                    sizeClass = 'marker-cluster-medium';
                    diameter = 42;
                }

                return L.divIcon({
                    html: `<div class="marker-cluster-custom ${sizeClass}" style="width: ${diameter}px; height: ${diameter}px;">${count}</div>`,
                    className: 'custom-cluster-wrapper',
                    iconSize: L.point(diameter, diameter)
                });
            }
        });

        map.addLayer(markerClusterGroup);

        // Drop initial location marker
        updateLocationPin(currentCoords.lat, currentCoords.lng, currentAreaName);

        // Map clicks select a coordinate and load its nearby incidents
        map.on('click', function (e) {
            return handleMapClick(e.latlng.lat, e.latlng.lng);
        });
    }

    // Update location pinpoint marker
    function updateLocationPin(lat, lng, label) {
        if (!searchLocationMarker) {
            const pulseIcon = L.divIcon({
                className: 'search-pin-container',
                html: '<div class="search-center-pin" title="Current Search Location"></div>',
                iconSize: [22, 22],
                iconAnchor: [11, 11]
            });
            searchLocationMarker = L.marker([lat, lng], {
                icon: pulseIcon,
                zIndexOffset: 1000
            }).addTo(map);
        } else {
            searchLocationMarker.setLatLng([lat, lng]);
        }
        if (label) {
            searchLocationMarker.bindTooltip(`<b>Location:</b> ${escapeHtml(label)}`, { direction: 'top', offset: [0, -10] });
        }
    }

    // Set map loading state
    function setLoading(isLoading, message) {
        const overlay = document.getElementById('map-loader');
        const text = document.getElementById('map-loader-text');
        if (overlay) {
            if (isLoading) {
                if (text) text.innerText = message || 'Loading crimes from Police UK...';
                overlay.classList.add('active');
            } else {
                overlay.classList.remove('active');
            }
        }
    }

    // All place queries go through the cached backend, on explicit submission.
    async function resolveLocation(query, version) {
        const cleanQuery = query.trim();
        const lower = cleanQuery.toLowerCase();
        for (const key in PRESET_LOCATIONS) {
            if (lower === key || lower === PRESET_LOCATIONS[key].name.toLowerCase()) {
                return PRESET_LOCATIONS[key];
            }
        }
        const isPostcode = /^(?:GIR\s?0AA|[A-Z]{1,2}[0-9][A-Z0-9]?\s?[0-9][A-Z]{2})$/i.test(cleanQuery);
        const endpoint = isPostcode ? 'postcode' : 'search';
        const response = await fetch(`/api/geocode/${endpoint}?q=${encodeURIComponent(cleanQuery)}`, {
            signal: requestController.signal
        });
        if (version !== requestVersion) return null;
        if (response.status === 404) return null;
        if (!response.ok) throw new Error('Location search is temporarily unavailable. Please try again.');
        const data = await response.json();
        const result = isPostcode ? data.result : (Array.isArray(data) ? data[0] : null);
        if (!result || !validCoords(result.lat, result.lng)) return null;
        return {
            name: isPostcode
                ? `${result.postcode || cleanQuery.toUpperCase()} (${result.admin_district || result.parish || 'UK'})`
                : result.display_name || cleanQuery,
            lat: Number(result.lat), lng: Number(result.lng), zoom: isPostcode ? 15 : 14
        };
    }

    // Map clicks select a coordinate directly without waiting for a second geocoder.
    function handleMapClick(lat, lng) {
        return jumpToLocation({ lat, lng, name: `Selected point (${lat.toFixed(4)}, ${lng.toFixed(4)})`, zoom: map.getZoom() });
    }

    // Fetch crimes from Flask API and render on map
    async function fetchAndRenderCrimes(lat, lng, date, areaName, version = beginRequest()) {
        clearError();
        setLoading(true, `Loading crimes for ${areaName} (${date || 'latest available month'})...`);
        // Clear the previous location's incidents so failed requests cannot show stale data.
        allLoadedCrimes = [];
        markerClusterGroup.clearLayers();
        updateStatsBar([], areaName, date);
        const inspector = document.getElementById('inspector-body');
        if (inspector) inspector.textContent = 'Loading incidents…';
        const filters = document.getElementById('category-filter-container');
        if (filters) filters.textContent = '';
        const status = document.getElementById('results-status');
        if (status) status.textContent = '';
        try {
            const params = new URLSearchParams({ lat, lng });
            if (date) params.set('date', date);
            const response = await fetch(`/api/crimes/street?${params}`, { signal: requestController.signal });
            if (!response.ok) {
                let detail = '';
                try {
                    const payload = await response.json();
                    if (typeof payload?.error === 'string') detail = payload.error.trim();
                } catch (error) {
                    // Proxies can return an HTML error instead of the API's JSON envelope.
                }
                const error = new Error(detail || `Data service returned HTTP ${response.status}`);
                error.status = response.status;
                throw error;
            }
            const crimes = await response.json();
            if (version !== requestVersion) return;
            if (!Array.isArray(crimes)) throw new Error('Data service returned an unexpected response');
            allLoadedCrimes = crimes.filter(crime => crime && typeof crime === 'object');
            const period = date || allLoadedCrimes[0]?.month || '';
            updateStatsBar(allLoadedCrimes, areaName, period);
            renderCategoryFilters(allLoadedCrimes);
            applyCategoryFilter(currentFilter);
            renderInspectorSummary(allLoadedCrimes, areaName, period);
        } catch (error) {
            if (version !== requestVersion || error.name === 'AbortError') return;
            const advice = error.status === 400
                ? 'Check your selected location and reporting month.'
                : 'Please try again shortly.';
            showError(`Unable to load crime data. ${error.message.replace(/[.!?]+$/, '')}. ${advice}`);
            for (const id of ['stat-total-crimes', 'stat-top-category']) {
                const element = document.getElementById(id);
                if (element) element.textContent = 'Unavailable';
            }
            if (inspector) inspector.textContent = 'Crime data could not be loaded for this selection.';
        } finally {
            if (version === requestVersion) setLoading(false);
        }
    }

    // Update Quick Stats Bar
    function updateStatsBar(crimes, areaName, date) {
        const countElem = document.getElementById('stat-total-crimes');
        const topCatElem = document.getElementById('stat-top-category');
        const areaElem = document.getElementById('stat-area-name');
        const dateElem = document.getElementById('stat-date-period');

        const total = crimes.length;
        if (countElem) countElem.innerText = total.toLocaleString();
        if (areaElem) areaElem.innerText = areaName || 'UK Area';
        if (dateElem) dateElem.innerText = date || 'Latest available';

        if (total === 0) {
            if (topCatElem) topCatElem.innerText = 'None';
            return;
        }

        // Calculate top category
        const catCounts = Object.create(null);
        for (const c of crimes) {
            const cat = categoryOf(c);
            catCounts[cat] = (catCounts[cat] || 0) + 1;
        }

        let maxCat = '';
        let maxCount = -1;
        for (const cat in catCounts) {
            if (catCounts[cat] > maxCount) {
                maxCount = catCounts[cat];
                maxCat = cat;
            }
        }

        const pct = Math.round((maxCount / total) * 100);
        if (topCatElem) {
            topCatElem.innerText = `${formatCategoryName(maxCat)} (${pct}%)`;
        }
    }

    // Render Dynamic Category Filter Pills
    function renderCategoryFilters(crimes) {
        const container = document.getElementById('category-filter-container');
        if (!container) return;

        // Count per category
        const counts = Object.assign(Object.create(null), { all: crimes.length });
        for (const c of crimes) {
            const cat = categoryOf(c);
            counts[cat] = (counts[cat] || 0) + 1;
        }

        if (!(currentFilter in counts)) currentFilter = 'all';

        // Sort categories by count descending
        const sortedCats = Object.keys(counts).filter(c => c !== 'all').sort((a, b) => counts[b] - counts[a]);

        let html = `
            <div class="filter-pills-row">
                <button type="button" class="category-filter-btn ${currentFilter === 'all' ? 'active' : ''}" data-cat="all">
                    <i class="fas fa-layer-group"></i> All Crimes
                    <span class="cat-count">${counts['all']}</span>
                </button>
        `;

        for (const cat of sortedCats) {
            const meta = categoryMeta(cat) || { name: formatCategoryName(cat), color: '#64748b', icon: 'fa-tag' };
            const isActive = currentFilter === cat ? 'active' : '';
            html += `
                <button type="button" class="category-filter-btn ${isActive}" data-cat="${escapeHtml(cat)}">
                    <span class="cat-dot" style="background-color: ${meta.color}"></span>
                    <i class="fas ${meta.icon}"></i> ${escapeHtml(meta.name)}
                    <span class="cat-count">${counts[cat]}</span>
                </button>
            `;
        }

        html += `</div>`;
        container.innerHTML = html;

        // Attach click listeners to filter buttons
        container.querySelectorAll('.category-filter-btn').forEach(btn => {
            btn.addEventListener('click', function () {
                const cat = this.getAttribute('data-cat');
                currentFilter = cat;
                container.querySelectorAll('.category-filter-btn').forEach(b => b.classList.remove('active'));
                this.classList.add('active');
                applyCategoryFilter(cat);
            });
        });
    }

    // Apply category filtering without page reload
    function applyCategoryFilter(cat) {
        if (!markerClusterGroup) return;

        markerClusterGroup.clearLayers();

        const filtered = (cat === 'all')
            ? allLoadedCrimes
            : allLoadedCrimes.filter(c => categoryOf(c) === cat);

        const markersToAdd = [];

        for (const crime of filtered) {
            if (!crime.location || !validCoords(crime.location.latitude, crime.location.longitude)) continue;

            const lat = Number(crime.location.latitude);
            const lng = Number(crime.location.longitude);

            const color = getCategoryColor(crime.category);
            const iconClass = getCategoryIcon(crime.category);

            // Custom pin HTML
            const pinHtml = `
                <div class="crime-pin-wrapper">
                    <div class="crime-pin-marker" style="background-color: ${color};" title="${escapeHtml(formatCategoryName(crime.category))}">
                        <i class="fas ${iconClass}"></i>
                    </div>
                </div>
            `;

            const customIcon = L.divIcon({
                className: 'custom-crime-div-icon',
                html: pinHtml,
                iconSize: [26, 26],
                iconAnchor: [13, 26],
                popupAnchor: [0, -26]
            });

            const marker = L.marker([lat, lng], { icon: customIcon });

            // Build popup content
            const outcomeInfo = formatOutcome(crime.outcome_status);
            const streetName = (crime.location && crime.location.street && crime.location.street.name)
                ? crime.location.street.name
                : 'Location not specified';

            const popupContent = `
                <div class="crime-popup-card">
                    <div class="crime-popup-header">
                        <span class="badge" style="background-color: ${color}; color: white; font-size: 0.8rem;">
                            <i class="fas ${iconClass}"></i> ${escapeHtml(formatCategoryName(crime.category))}
                        </span>
                        <small class="text-muted"><i class="far fa-calendar-alt"></i> ${escapeHtml(crime.month || 'N/A')}</small>
                    </div>
                    <h6 class="mb-2" style="font-size: 0.95rem; font-weight: 600;"><i class="fas fa-map-marker-alt text-danger me-1"></i> ${escapeHtml(streetName)}</h6>
                    <div class="mb-3">
                        <small class="text-muted d-block mb-1">Outcome Status:</small>
                        <span class="badge-outcome ${outcomeInfo.badgeClass}">${escapeHtml(outcomeInfo.text)}</span>
                    </div>
                    <button type="button" class="btn btn-sm btn-outline-primary w-100 inspect-pin-btn">
                        <i class="fas fa-search-plus"></i> View in Inspector
                    </button>
                </div>
            `;

            marker.bindPopup(popupContent, { maxWidth: 300 });

            // Pin click handler: Populates side inspector card & opens popup
            marker.on('click', function () {
                displayCrimeInInspector(crime);
            });

            marker.on('popupopen', function (event) {
                const btn = event.popup.getElement()?.querySelector('.inspect-pin-btn');
                if (btn) {
                    btn.addEventListener('click', () => displayCrimeInInspector(crime));
                }
            });

            markersToAdd.push(marker);
        }

        markerClusterGroup.addLayers(markersToAdd);

        // Update results counter text
        const resultsStatus = document.getElementById('results-status');
        if (resultsStatus) {
            if (filtered.length === 0) {
                resultsStatus.innerHTML = `<div class="alert alert-warning py-2 mb-2"><i class="fas fa-info-circle"></i> No crimes found for category "<strong>${escapeHtml(formatCategoryName(cat))}</strong>".</div>`;
            } else {
                resultsStatus.innerHTML = `<small class="text-muted"><i class="fas fa-check-circle text-success"></i> Displaying <strong>${markersToAdd.length.toLocaleString()}</strong> mapped of ${filtered.length.toLocaleString()} selected incidents (${allLoadedCrimes.length.toLocaleString()} total).</small>`;
            }
        }
    }

    // Display single selected crime in the Side Inspector Card
    function displayCrimeInInspector(crime) {
        const inspectorBody = document.getElementById('inspector-body');
        if (!inspectorBody) return;

        const color = getCategoryColor(crime.category);
        const iconClass = getCategoryIcon(crime.category);
        const catName = formatCategoryName(crime.category);
        const outcomeInfo = formatOutcome(crime.outcome_status);
        const street = (crime.location && crime.location.street && crime.location.street.name)
            ? crime.location.street.name
            : 'Street location unavailable';
        const lat = crime.location ? crime.location.latitude : 'N/A';
        const lng = crime.location ? crime.location.longitude : 'N/A';

        inspectorBody.innerHTML = `
            <div class="selected-crime-details animate__animated animate__fadeIn">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <span class="badge p-2" style="background-color: ${color}; color: white; font-size: 0.85rem;">
                        <i class="fas ${iconClass} me-1"></i> ${escapeHtml(catName)}
                    </span>
                    <button class="btn btn-sm btn-link text-decoration-none text-muted p-0" id="reset-inspector-btn" title="Back to area overview">
                        <i class="fas fa-times-circle fs-5"></i>
                    </button>
                </div>

                <div class="card bg-light border-0 mb-3 p-3">
                    <label class="text-muted small fw-bold text-uppercase mb-1"><i class="fas fa-map-pin text-danger"></i> Street / Location</label>
                    <div class="fs-6 fw-bold text-dark">${escapeHtml(street)}</div>
                    <small class="text-muted mt-1">Coordinates: ${escapeHtml(lat)}, ${escapeHtml(lng)}</small>
                </div>

                <div class="mb-3">
                    <label class="text-muted small fw-bold text-uppercase mb-1"><i class="fas fa-balance-scale text-primary"></i> Police Outcome</label>
                    <div class="badge-outcome ${outcomeInfo.badgeClass} d-block p-2 text-wrap">
                        <i class="fas fa-clipboard-check me-1"></i> ${escapeHtml(outcomeInfo.text)}
                    </div>
                </div>

                <div class="row g-2 mb-3">
                    <div class="col-6">
                        <div class="p-2 border rounded bg-white">
                            <span class="text-muted d-block small">Month</span>
                            <strong>${escapeHtml(crime.month || 'N/A')}</strong>
                        </div>
                    </div>
                    <div class="col-6">
                        <div class="p-2 border rounded bg-white">
                            <span class="text-muted d-block small">Crime ID</span>
                            <strong class="small text-truncate d-block" title="${escapeHtml(crime.id)}">${escapeHtml(crime.id || 'N/A')}</strong>
                        </div>
                    </div>
                </div>

                ${crime.persistent_id ? `
                    <div class="mb-3">
                        <label class="text-muted small fw-bold text-uppercase mb-1">Persistent Reference</label>
                        <input type="text" class="form-control form-control-sm bg-white font-monospace" value="${escapeHtml(crime.persistent_id)}" readonly onclick="this.select()">
                    </div>
                ` : ''}

                <div class="d-grid gap-2 mt-4">
                    <button type="button" class="btn btn-sm btn-primary" id="zoom-to-crime-btn">
                        <i class="fas fa-crosshairs me-1"></i> Center & Zoom to Street
                    </button>
                </div>
            </div>
        `;

        // Attach listeners
        const resetBtn = document.getElementById('reset-inspector-btn');
        if (resetBtn) {
            resetBtn.addEventListener('click', () => {
                renderInspectorSummary(allLoadedCrimes, currentAreaName, document.getElementById('date-select')?.value);
            });
        }

        const zoomBtn = document.getElementById('zoom-to-crime-btn');
        if (zoomBtn && validCoords(lat, lng)) {
            zoomBtn.addEventListener('click', () => {
                map.flyTo([parseFloat(lat), parseFloat(lng)], 18, { duration: 1 });
            });
        }
    }

    // Render Area Summary in Inspector when no specific marker is clicked
    function renderInspectorSummary(crimes, areaName, date) {
        const inspectorBody = document.getElementById('inspector-body');
        if (!inspectorBody) return;

        if (!crimes || crimes.length === 0) {
            inspectorBody.innerHTML = `
                <div class="text-center text-muted py-5">
                    <i class="fas fa-shield-alt fa-3x mb-3 text-secondary opacity-50"></i>
                    <h6 class="fw-bold">No Crime Data Recorded</h6>
                    <p class="small text-muted">Try selecting another month or clicking another UK area on the map.</p>
                </div>
            `;
            return;
        }

        // Count top categories
        const catCounts = Object.create(null);
        for (const c of crimes) {
            const cat = categoryOf(c);
            catCounts[cat] = (catCounts[cat] || 0) + 1;
        }

        const sortedCats = Object.keys(catCounts).sort((a, b) => catCounts[b] - catCounts[a]).slice(0, 5);

        let html = `
            <div>
                <div class="d-flex align-items-center justify-content-between mb-3">
                    <h6 class="mb-0 fw-bold"><i class="fas fa-chart-pie text-primary me-2"></i>Area Breakdown</h6>
                    <span class="badge bg-secondary">${crimes.length.toLocaleString()} Total</span>
                </div>
                <p class="small text-muted mb-3">Click any pin on the map to inspect full street-level details and outcomes.</p>

                <div class="mb-4">
                    <label class="text-muted small fw-bold text-uppercase mb-2">Top Categories in ${escapeHtml(areaName)}</label>
        `;

        for (const cat of sortedCats) {
            const count = catCounts[cat];
            const pct = Math.round((count / crimes.length) * 100);
            const color = getCategoryColor(cat);
            const icon = getCategoryIcon(cat);
            html += `
                <div class="mb-2">
                    <div class="d-flex justify-content-between small mb-1">
                        <span><i class="fas ${icon} me-1" style="color: ${color}"></i> ${escapeHtml(formatCategoryName(cat))}</span>
                        <strong>${count} <span class="text-muted fw-normal">(${pct}%)</span></strong>
                    </div>
                    <div class="progress" style="height: 6px;">
                        <div class="progress-bar" role="progressbar" style="width: ${pct}%; background-color: ${color}"></div>
                    </div>
                </div>
            `;
        }

        html += `
                </div>
                <hr class="my-3">
                <div class="d-flex align-items-center justify-content-between mb-2">
                    <label class="text-muted small fw-bold text-uppercase mb-0">Sample Street Incidents</label>
                    <small class="text-muted">Sample of 6</small>
                </div>
                <div class="inspector-crimes-list">
        `;

        const sample = crimes.slice(0, 6);
        for (const [index, c] of sample.entries()) {
            const color = getCategoryColor(c.category);
            const street = (c.location && c.location.street && c.location.street.name) ? c.location.street.name : 'Street Location';
            html += `
                <button type="button" class="inspector-crime-item border-0 w-100 text-start" data-crime-index="${index}">
                    <div class="d-flex justify-content-between align-items-center">
                        <span class="badge" style="background-color: ${color}; color: white; font-size: 0.72rem;">${escapeHtml(formatCategoryName(c.category))}</span>
                        <small class="text-muted"><i class="fas fa-chevron-right"></i></small>
                    </div>
                    <div class="small fw-bold text-dark mt-1 text-truncate">${escapeHtml(street)}</div>
                </button>
            `;
        }

        html += `
                </div>
            </div>
        `;

        inspectorBody.innerHTML = html;

        // Click handler for sample list items
        inspectorBody.querySelectorAll('.inspector-crime-item').forEach(item => {
            item.addEventListener('click', function () {
                const crime = sample[Number(this.getAttribute('data-crime-index'))];
                if (crime) {
                    displayCrimeInInspector(crime);
                    // One map movement is enough: the inspector already displays details.
                    // Cluster zoom callbacks can outlive their marker when a new query clears layers.
                    if (crime.location && validCoords(crime.location.latitude, crime.location.longitude)) {
                        const lat = parseFloat(crime.location.latitude);
                        const lng = parseFloat(crime.location.longitude);
                        map.flyTo([lat, lng], 17, { duration: 0.8 });
                    }
                }
            });
        });
    }

    // Every location/date action supersedes the preceding async operation.
    async function jumpToLocation(location, version = beginRequest()) {
        if (version !== requestVersion || !validCoords(location.lat, location.lng)) return;
        clearError();
        currentCoords = { lat: Number(location.lat), lng: Number(location.lng) };
        currentAreaName = location.name;
        map.flyTo([currentCoords.lat, currentCoords.lng], location.zoom || 14, { duration: 0.5 });
        updateLocationPin(currentCoords.lat, currentCoords.lng, location.name);
        const input = document.getElementById('location-search-input');
        if (input) input.value = location.name;
        document.querySelectorAll('.quick-jump-pill').forEach(pill => {
            pill.classList.toggle('active', PRESET_LOCATIONS[pill.getAttribute('data-preset')]?.name === location.name);
        });
        await fetchAndRenderCrimes(currentCoords.lat, currentCoords.lng, document.getElementById('date-select')?.value || '', location.name, version);
    }

    function setupEventListeners() {
        document.getElementById('location-search-form')?.addEventListener('submit', async event => {
            event.preventDefault();
            const query = document.getElementById('location-search-input').value.trim();
            if (!query) return;
            const version = beginRequest();
            clearError();
            setLoading(true, `Searching for ${query}…`);
            try {
                const location = await resolveLocation(query, version);
                if (version !== requestVersion) return;
                if (location) await jumpToLocation(location, version);
                else showError('Location not found. Enter a UK postcode or place name.');
            } catch (error) {
                if (version === requestVersion && error.name !== 'AbortError') showError(error.message);
            } finally {
                if (version === requestVersion) setLoading(false);
            }
        });
        document.querySelectorAll('.quick-jump-pill').forEach(pill => {
            pill.addEventListener('click', () => jumpToLocation(PRESET_LOCATIONS[pill.getAttribute('data-preset')]));
        });
        document.getElementById('preset-forces-select')?.addEventListener('change', event => {
            if (PRESET_LOCATIONS[event.target.value]) jumpToLocation(PRESET_LOCATIONS[event.target.value]);
        });
        document.getElementById('date-select')?.addEventListener('change', event => {
            if (!event.target.validity.valid) return;
            return fetchAndRenderCrimes(currentCoords.lat, currentCoords.lng, event.target.value, currentAreaName);
        });
        document.getElementById('btn-my-location')?.addEventListener('click', () => {
            const version = beginRequest();
            clearError();
            if (!navigator.geolocation) {
                setLoading(false);
                showError('This browser does not support location access. Enter a postcode or select a point on the map.');
                return;
            }
            setLoading(true, 'Locating your current position…');
            navigator.geolocation.getCurrentPosition(position => {
                if (version !== requestVersion) return;
                const lat = position.coords.latitude;
                const lng = position.coords.longitude;
                jumpToLocation({ lat, lng, name: `Your location (${lat.toFixed(4)}, ${lng.toFixed(4)})`, zoom: 15 }, version);
            }, () => {
                if (version !== requestVersion) return;
                setLoading(false);
                showError('Unable to access your location. Enter a postcode or select a point on the map.');
            }, { timeout: 10000 });
        });
    }

    document.addEventListener('DOMContentLoaded', async function () {
        if (typeof L === 'undefined' || typeof L.markerClusterGroup !== 'function') {
            setLoading(false);
            showError('The map could not load. Please check your connection and refresh the page.');
            return;
        }
        initMap();
        setupEventListeners();
        const version = beginRequest();
        const dateInput = document.getElementById('date-select');
        dateInput.max = new Date().toISOString().slice(0, 7);
        try {
            const response = await fetch('/api/crimes/last-updated', { signal: requestController.signal });
            if (response.ok) {
                const data = await response.json();
                if (version === requestVersion && /^\d{4}-\d{2}-\d{2}$/.test(data.date || '')) {
                    dateInput.value = data.date.slice(0, 7);
                    dateInput.max = dateInput.value;
                }
            }
        } catch (error) {
            // Omitted dates use the latest available month if metadata is unavailable.
        }
        if (version === requestVersion) {
            await fetchAndRenderCrimes(currentCoords.lat, currentCoords.lng, dateInput.value, currentAreaName, version);
        }
    });

})();
