#!/usr/bin/env python3
import sys
import os
import re
import json
from pathlib import Path

class FeatureManager:
    def __init__(self, app_file="app.py"):
        self.app_file = app_file
        self.features = {
            "map": {
                "name": "Interactive Crime Map",
                "description": "Adds Leaflet.js map with crime visualization",
                "dependencies": ["leaflet"],
                "status": "not_installed"
            },
            "analytics": {
                "name": "Crime Analytics Dashboard", 
                "description": "Adds charts and statistics for crime data",
                "dependencies": ["chart.js"],
                "status": "not_installed"
            },
            "export": {
                "name": "Data Export",
                "description": "Export crime data to CSV and JSON formats",
                "dependencies": [],
                "status": "not_installed"
            },
            "geolocation": {
                "name": "Geolocation",
                "description": "Auto-detect user location and nearby crimes",
                "dependencies": [],
                "status": "not_installed"
            },
            "mobile": {
                "name": "Mobile Optimization",
                "description": "Responsive design for mobile devices",
                "dependencies": [],
                "status": "not_installed"
            }
        }
        
    def list_features(self):
        """List all available features"""
        print("🎯 AVAILABLE FEATURES:")
        print("=" * 60)
        for feature_id, feature in self.features.items():
            status_icon = "✅" if feature["status"] == "installed" else "⭕"
            print(f"{status_icon} {feature_id:12} - {feature['name']}")
            print(f"    📝 {feature['description']}")
            if feature['dependencies']:
                print(f"    📦 Depends on: {', '.join(feature['dependencies'])}")
            print()
    
    def install_feature(self, feature_name):
        """Install a specific feature"""
        if feature_name not in self.features:
            print(f"❌ Feature '{feature_name}' not found!")
            return False
        
        feature = self.features[feature_name]
        
        # Check dependencies
        for dep in feature['dependencies']:
            if dep not in self.features or self.features[dep]['status'] != 'installed':
                print(f"❌ Missing dependency: {dep}")
                print(f"   Please install {dep} first: python feature_manager.py {dep}")
                return False
        
        print(f"🚀 Installing {feature['name']}...")
        
        # Read current app
        with open(self.app_file, 'r') as f:
            content = f.read()
        
        # Apply feature
        if feature_name == "map":
            content = self._install_map_feature(content)
        elif feature_name == "analytics":
            content = self._install_analytics_feature(content)
        elif feature_name == "export":
            content = self._install_export_feature(content)
        elif feature_name == "geolocation":
            content = self._install_geolocation_feature(content)
        elif feature_name == "mobile":
            content = self._install_mobile_feature(content)
        
        # Write updated app
        with open(self.app_file, 'w') as f:
            f.write(content)
        
        # Update feature status
        self.features[feature_name]['status'] = 'installed'
        self._save_feature_status()
        
        print(f"✅ {feature['name']} installed successfully!")
        return True
    
    def _install_map_feature(self, content):
        """Install map visualization feature"""
        print("   📍 Adding crime map visualization...")
        
        # Add Leaflet CSS
        if 'leaflet.css' not in content:
            content = content.replace(
                '<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">',
                '''<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />'''
            )
        
        # Add Leaflet JS
        if 'leaflet.js' not in content:
            content = content.replace(
                '</body>',
                '''    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
</body>'''
            )
        
        # Replace crime results with map layout
        if 'id="crimeMap"' not in content:
            content = content.replace(
                '<div id="crimeResults" class="mt-3"></div>',
                '''<div class="row">
    <div class="col-md-6">
        <div id="crimeResults" class="mt-3"></div>
    </div>
    <div class="col-md-6">
        <div class="card">
            <div class="card-header bg-success text-white">
                <h6 class="mb-0"><i class="fas fa-map-marked-alt"></i> Crime Map</h6>
            </div>
            <div class="card-body p-2">
                <div id="crimeMap" style="height: 300px; border-radius: 0.25rem;"></div>
            </div>
        </div>
    </div>
</div>'''
            )
        
        # Add map JavaScript
        map_js = '''
// ==================== MAP FEATURE ====================
let map = L.map('crimeMap').setView([51.5074, -0.1278], 13);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© OpenStreetMap contributors'
}).addTo(map);

let crimeMarkers = L.layerGroup().addTo(map);

const crimeColors = {
    'violent-crime': '#dc3545', 'burglary': '#fd7e14', 'theft': '#20c997',
    'vehicle-crime': '#0dcaf0', 'anti-social-behaviour': '#6f42c1', 
    'shoplifting': '#e83e8c', 'robbery': '#ff6b6b', 'drugs': '#8B4513',
    'other-crime': '#6c757d'
};

function updateCrimeMap(crimes, lat, lng) {
    crimeMarkers.clearLayers();
    map.setView([lat, lng], 13);
    
    crimes.forEach(crime => {
        if (crime.location && crime.location.latitude && crime.location.longitude) {
            const marker = L.circleMarker([
                parseFloat(crime.location.latitude),
                parseFloat(crime.location.longitude)
            ], {
                radius: 6,
                fillColor: crimeColors[crime.category] || '#6c757d',
                color: '#fff',
                weight: 1,
                fillOpacity: 0.8
            }).addTo(crimeMarkers);
            
            const crimeDate = new Date(crime.month + '-01').toLocaleDateString('en-GB', { 
                month: 'long', 
                year: 'numeric' 
            });
            
            marker.bindPopup(`
                <div class="small">
                    <strong>${crime.category.replace(/-/g, ' ').toUpperCase()}</strong><br>
                    <i class="fas fa-map-marker-alt"></i> ${crime.location.street.name}<br>
                    <i class="fas fa-calendar"></i> ${crimeDate}<br>
                    ${crime.outcome_status ? `<i class="fas fa-clipboard-check"></i> ${crime.outcome_status.category}` : ''}
                </div>
            `);
        }
    });
}
// ==================== END MAP FEATURE ====================
'''
        
        # Inject map JS before closing script tag
        if 'updateCrimeMap' not in content:
            script_end = content.rfind('</script>')
            if script_end != -1:
                content = content[:script_end] + map_js + content[script_end:]
        
        # Update crime search to use map
        if 'updateCrimeMap(crimes' not in content:
            content = content.replace(
                'const crimes = await response.json();',
                'const crimes = await response.json();\n            if (crimes && crimes.length > 0) { updateCrimeMap(crimes, parseFloat(lat), parseFloat(lng)); }'
            )
        
        return content
    
    def _install_analytics_feature(self, content):
        """Install analytics dashboard feature"""
        print("   📊 Adding crime analytics...")
        
        # Add Chart.js
        if 'chart.js' not in content:
            content = content.replace(
                '</body>',
                '''    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
</body>'''
            )
        
        # Add analytics card after crime results
        analytics_html = '''
<!-- ==================== ANALYTICS FEATURE ==================== -->
<div class="card mt-4" id="analyticsCard" style="display: none;">
    <div class="card-header bg-info text-white">
        <h6 class="mb-0"><i class="fas fa-chart-bar"></i> Crime Analytics</h6>
    </div>
    <div class="card-body">
        <div class="row">
            <div class="col-md-6">
                <canvas id="crimeChart" height="200"></canvas>
            </div>
            <div class="col-md-6">
                <div id="analyticsStats"></div>
            </div>
        </div>
    </div>
</div>
<!-- ==================== END ANALYTICS FEATURE ==================== -->
'''
        
        if 'id="analyticsCard"' not in content:
            # Find a good place to insert analytics (after crime results section)
            insert_point = content.find('</div>', content.find('id="crimeResults"'))
            if insert_point != -1:
                content = content[:insert_point + 6] + analytics_html + content[insert_point + 6:]
        
        # Add analytics JavaScript
        analytics_js = '''
// ==================== ANALYTICS FEATURE ====================
let crimeChart = null;

function updateCrimeAnalytics(crimes) {
    // Show analytics card
    document.getElementById('analyticsCard').style.display = 'block';
    
    // Calculate category counts
    const categories = {};
    crimes.forEach(crime => {
        categories[crime.category] = (categories[crime.category] || 0) + 1;
    });
    
    // Update stats
    const statsHtml = `
        <div class="text-center">
            <h4>${crimes.length}</h4>
            <small class="text-muted">Total Crimes</small>
        </div>
        <div class="mt-3">
            ${Object.entries(categories).slice(0, 5).map(([cat, count]) => `
                <div class="d-flex justify-content-between small mb-1">
                    <span>${cat.replace(/-/g, ' ')}</span>
                    <span class="badge bg-primary">${count}</span>
                </div>
            `).join('')}
        </div>
    `;
    document.getElementById('analyticsStats').innerHTML = statsHtml;
    
    // Update chart
    const ctx = document.getElementById('crimeChart').getContext('2d');
    if (crimeChart) {
        crimeChart.destroy();
    }
    
    const sortedCategories = Object.entries(categories)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 8);
    
    crimeChart = new Chart(ctx, {
        type: 'doughnut',
        data: {
            labels: sortedCategories.map(([cat]) => cat.replace(/-/g, ' ')),
            datasets: [{
                data: sortedCategories.map(([_, count]) => count),
                backgroundColor: [
                    '#dc3545', '#fd7e14', '#ffc107', '#20c997',
                    '#0dcaf0', '#6f42c1', '#e83e8c', '#6c757d'
                ]
            }]
        },
        options: {
            responsive: true,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: {
                        boxWidth: 12,
                        font: {
                            size: 10
                        }
                    }
                }
            }
        }
    });
}
// ==================== END ANALYTICS FEATURE ====================
'''
        
        if 'updateCrimeAnalytics' not in content:
            script_end = content.rfind('</script>')
            if script_end != -1:
                content = content[:script_end] + analytics_js + content[script_end:]
        
        # Update crime search to use analytics
        if 'updateCrimeAnalytics(crimes)' not in content:
            content = content.replace(
                'if (crimes && crimes.length > 0) { updateCrimeMap(crimes, parseFloat(lat), parseFloat(lng)); }',
                'if (crimes && crimes.length > 0) { updateCrimeMap(crimes, parseFloat(lat), parseFloat(lng)); updateCrimeAnalytics(crimes); }'
            )
        
        return content
    
    def _install_export_feature(self, content):
        """Install data export feature"""
        print("   💾 Adding data export functionality...")
        
        # Add export buttons to crime results
        export_html = '''
<!-- ==================== EXPORT FEATURE ==================== -->
<div class="mt-3" id="exportSection" style="display: none;">
    <div class="card">
        <div class="card-header bg-warning text-white">
            <h6 class="mb-0"><i class="fas fa-download"></i> Export Data</h6>
        </div>
        <div class="card-body">
            <button class="btn btn-sm btn-success me-2" onclick="exportToCSV()">
                <i class="fas fa-file-csv"></i> Export CSV
            </button>
            <button class="btn btn-sm btn-info" onclick="exportToJSON()">
                <i class="fas fa-file-code"></i> Export JSON
            </button>
        </div>
    </div>
</div>
<!-- ==================== END EXPORT FEATURE ==================== -->
'''
        
        if 'id="exportSection"' not in content:
            # Insert after crime results
            insert_point = content.find('</div>', content.find('id="crimeResults"'))
            if insert_point != -1:
                content = content[:insert_point + 6] + export_html + content[insert_point + 6:]
        
        # Add export JavaScript
        export_js = '''
// ==================== EXPORT FEATURE ====================
let currentCrimesData = [];

function exportToCSV() {
    if (currentCrimesData.length === 0) return;
    
    const headers = ['Category', 'Street', 'Month', 'Outcome'];
    const csvContent = [
        headers.join(','),
        ...currentCrimesData.map(crime => [
            `"${crime.category}"`,
            `"${crime.location.street.name}"`,
            `"${crime.month}"`,
            `"${crime.outcome_status?.category || 'Unknown'}"`
        ].join(','))
    ].join('\\n');
    
    const blob = new Blob([csvContent], { type: 'text/csv' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `crimes-${new Date().toISOString().split('T')[0]}.csv`;
    a.click();
    window.URL.revokeObjectURL(url);
}

function exportToJSON() {
    if (currentCrimesData.length === 0) return;
    
    const jsonData = {
        timestamp: new Date().toISOString(),
        crimeCount: currentCrimesData.length,
        crimes: currentCrimesData
    };
    
    const blob = new Blob([JSON.stringify(jsonData, null, 2)], { type: 'application/json' });
    const url = window.URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `crimes-${new Date().toISOString().split('T')[0]}.json`;
    a.click();
    window.URL.revokeObjectURL(url);
}
// ==================== END EXPORT FEATURE ====================
'''
        
        if 'exportToCSV' not in content:
            script_end = content.rfind('</script>')
            if script_end != -1:
                content = content[:script_end] + export_js + content[script_end:]
        
        # Update to store current crimes and show export section
        if 'currentCrimesData = crimes;' not in content:
            content = content.replace(
                'const crimes = await response.json();',
                'const crimes = await response.json();\n            currentCrimesData = crimes;'
            )
        
        if 'document.getElementById(\'exportSection\').style.display = \'block\'' not in content:
            content = content.replace(
                'if (crimes && crimes.length > 0) {',
                'if (crimes && crimes.length > 0) { document.getElementById(\'exportSection\').style.display = \'block\';'
            )
        
        return content
    
    def _install_geolocation_feature(self, content):
        """Install geolocation feature"""
        print("   📍 Adding geolocation...")
        
        # Add geolocation button to search form
        if 'getUserLocation()' not in content:
            # Find the latitude input and add location button
            content = content.replace(
                '<input type="text" class="form-control" id="crimeLat"',
                '''<div class="input-group">
                    <input type="text" class="form-control" id="crimeLat"'''
            )
            content = content.replace(
                '<input type="text" class="form-control" id="crimeLng"',
                '''<input type="text" class="form-control" id="crimeLng"
                    <button class="btn btn-outline-secondary" type="button" onclick="getUserLocation()">
                        <i class="fas fa-location-arrow"></i>
                    </button>
                </div>'''
            )
        
        # Add geolocation JavaScript
        geolocation_js = '''
// ==================== GEOLOCATION FEATURE ====================
function getUserLocation() {
    if (navigator.geolocation) {
        navigator.geolocation.getCurrentPosition(
            function(position) {
                const lat = position.coords.latitude;
                const lng = position.coords.longitude;
                document.getElementById('crimeLat').value = lat.toFixed(6);
                document.getElementById('crimeLng').value = lng.toFixed(6);
                
                // Optional: Auto-search for crimes at this location
                // document.getElementById('crimeSearchForm').dispatchEvent(new Event('submit'));
            },
            function(error) {
                alert('Unable to get your location: ' + error.message);
            }
        );
    } else {
        alert('Geolocation is not supported by your browser.');
    }
}
// ==================== END GEOLOCATION FEATURE ====================
'''
        
        if 'getUserLocation' not in content:
            script_end = content.rfind('</script>')
            if script_end != -1:
                content = content[:script_end] + geolocation_js + content[script_end:]
        
        return content
    
    def _install_mobile_feature(self, content):
        """Install mobile optimization feature"""
        print("   📱 Adding mobile optimization...")
        
        # Add responsive meta tag and mobile CSS
        if 'max-width: 768px' not in content:
            # Find existing style tag and add mobile styles
            style_end = content.find('</style>')
            if style_end != -1:
                mobile_css = '''
/* ==================== MOBILE FEATURE ==================== */
@media (max-width: 768px) {
    .container { padding: 0 10px; }
    .card-body { padding: 1rem; }
    .navbar-brand { font-size: 1.1rem; }
    #crimeMap { height: 250px; }
    .btn { padding: 0.5rem 1rem; font-size: 0.9rem; }
    .display-6 { font-size: 1.5rem; }
    .force-card { margin-bottom: 0.5rem; }
}
/* ==================== END MOBILE FEATURE ==================== */
'''
                content = content[:style_end] + mobile_css + content[style_end:]
        
        return content
    
    def _save_feature_status(self):
        """Save feature status to file"""
        status_file = "feature_status.json"
        with open(status_file, 'w') as f:
            json.dump(self.features, f, indent=2)
    
    def _load_feature_status(self):
        """Load feature status from file"""
        status_file = "feature_status.json"
        if os.path.exists(status_file):
            with open(status_file, 'r') as f:
                saved_status = json.load(f)
                for feature_id, status in saved_status.items():
                    if feature_id in self.features:
                        self.features[feature_id]['status'] = status['status']

def main():
    if len(sys.argv) < 2:
        manager = FeatureManager()
        manager.list_features()
        print("\n💡 Usage: python feature_manager.py <feature_name>")
        print("💡 Example: python feature_manager.py map")
        return
    
    feature_name = sys.argv[1]
    manager = FeatureManager()
    manager._load_feature_status()
    
    if feature_name == "all":
        # Install all features
        for feature_id in manager.features.keys():
            manager.install_feature(feature_id)
    else:
        manager.install_feature(feature_name)

if __name__ == "__main__":
    main()
