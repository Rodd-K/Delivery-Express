/* Shared helpers: Leaflet map + Geoapify tiles, address search and routing. */
(function () {
  var EM = (window.EM = window.EM || {});

  EM.NAIROBI = { lat: -1.286389, lng: 36.817223 };

  EM.hasMaps = function () { return !!(window.L && window.EM_GEO_KEY); };

  EM.data = function () {
    var el = document.getElementById('em-data');
    return el ? JSON.parse(el.textContent) : {};
  };

  EM.csrf = function () {
    var m = document.querySelector('meta[name="csrf-token"]');
    return m ? m.content : '';
  };

  EM.postJSON = function (url, body) {
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': EM.csrf() },
      body: JSON.stringify(body)
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (json) {
        return { ok: res.ok, status: res.status, body: json };
      });
    });
  };

  /* ---------- Map ---------- */
  EM.newMap = function (el, center, zoom) {
    var map = L.map(el, { center: [center.lat, center.lng], zoom: zoom || 12 });
    var tiles = L.tileLayer(
      'https://maps.geoapify.com/v1/tile/osm-bright/{z}/{x}/{y}.png?apiKey=' + encodeURIComponent(window.EM_GEO_KEY),
      {
        maxZoom: 19,
        attribution: 'Powered by <a href="https://www.geoapify.com/" target="_blank" rel="noopener">Geoapify</a> | ' +
          '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors'
      }
    ).addTo(map);

    var warned = false;
    tiles.on('tileerror', function () {
      if (warned) return;
      warned = true;
      var note = document.createElement('p');
      note.className = 'map-banner';
      note.textContent = 'Map tiles did not load. Check GEOAPIFY_API_KEY and the domains allowed for that key.';
      map.getContainer().appendChild(note);
    });
    return map;
  };

  /* A round marker built from DOM nodes (labels are always plain text). */
  EM.icon = function (kind, label) {
    var el = document.createElement('div');
    el.className = 'pin pin--' + kind;
    var dot = document.createElement('span');
    dot.className = 'pin__dot';
    el.appendChild(dot);
    if (label) {
      var text = document.createElement('span');
      text.className = 'pin__label';
      text.textContent = label;
      el.appendChild(text);
    }
    return L.divIcon({ className: 'em-pin-wrap', html: el, iconSize: [0, 0] });
  };

  EM.bounds = function (points, map) {
    map.fitBounds(L.latLngBounds(points.map(function (p) { return [p.lat, p.lng]; })), { padding: [60, 60] });
  };

  /* ---------- Geoapify ---------- */
  function geoUrl(path, params) {
    var q = new URLSearchParams(params);
    q.set('apiKey', window.EM_GEO_KEY);
    return 'https://api.geoapify.com' + path + '?' + q.toString();
  }

  EM.autocomplete = async function (text, bias, signal) {
    var params = { text: text, filter: 'countrycode:ke', limit: 5, format: 'json', lang: 'en' };
    if (bias) params.bias = 'proximity:' + bias.lng + ',' + bias.lat;
    var res = await fetch(geoUrl('/v1/geocode/autocomplete', params), { signal: signal });
    if (!res.ok) throw new Error('Address search failed (' + res.status + ')');
    var json = await res.json();
    return (json.results || [])
      .filter(function (r) { return isFinite(r.lat) && isFinite(r.lon); })
      .map(function (r) { return { label: r.formatted, lat: r.lat, lng: r.lon }; });
  };

  EM.reverse = async function (ll) {
    var res = await fetch(geoUrl('/v1/geocode/reverse', { lat: ll.lat, lon: ll.lng, format: 'json', lang: 'en' }));
    if (!res.ok) return '';
    var json = await res.json();
    return json.results && json.results[0] ? json.results[0].formatted : '';
  };

  EM.route = async function (from, to) {
    var url = geoUrl('/v1/routing', {
      waypoints: from.lat + ',' + from.lng + '|' + to.lat + ',' + to.lng,
      mode: 'drive'
    });
    var res = await fetch(url);
    if (!res.ok) throw new Error('Routing failed (' + res.status + ')');
    var json = await res.json();
    var f = json.features && json.features[0];
    if (!f) throw new Error('No route found');
    var coords = f.geometry.type === 'MultiLineString'
      ? [].concat.apply([], f.geometry.coordinates)
      : f.geometry.coordinates;
    return {
      path: coords.map(function (c) { return [c[1], c[0]]; }),
      seconds: Math.round(f.properties.time),
      meters: Math.round(f.properties.distance)
    };
  };

  EM.haversine = function (a, b) {
    var R = 6371, toRad = Math.PI / 180;
    var dLat = (b.lat - a.lat) * toRad, dLng = (b.lng - a.lng) * toRad;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(a.lat * toRad) * Math.cos(b.lat * toRad) * Math.sin(dLng / 2) * Math.sin(dLng / 2);
    return 2 * R * Math.asin(Math.sqrt(h));
  };

  /* ---------- Formatting ---------- */
  EM.formatEta = function (seconds) {
    var mins = Math.max(1, Math.round(seconds / 60));
    if (mins < 60) return mins + ' min';
    var h = Math.floor(mins / 60), m = mins % 60;
    return h + ' h' + (m ? ' ' + m + ' min' : '');
  };

  EM.formatDistance = function (meters) {
    return meters < 1000 ? Math.round(meters / 10) * 10 + ' m' : (meters / 1000).toFixed(1) + ' km';
  };

  EM.formatAge = function (seconds) {
    if (seconds < 10) return 'just now';
    if (seconds < 60) return seconds + ' seconds ago';
    var mins = Math.round(seconds / 60);
    return mins + (mins === 1 ? ' minute ago' : ' minutes ago');
  };

  /* Turn-by-turn navigation in the rider's own Google Maps app (needs no key, no billing). */
  EM.navUrl = function (lat, lng) {
    return 'https://www.google.com/maps/dir/?api=1&travelmode=driving&destination=' + lat + ',' + lng;
  };
})();
