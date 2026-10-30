/* Rider: see the route, share GPS with the customer, and move the order through its steps. */
(function () {
  var data = EM.data();
  var state = {
    status: data.status,
    pos: null,
    sharing: false,
    simulating: false,
    watchId: null,
    sendTimer: null,
    simTimer: null,
    wakeLock: null,
    lastRouteAt: 0,
    route: null
  };
  var map = null, riderMarker = null, routeLine = null;

  var el = {
    badge: document.getElementById('status-badge'),
    statusBtn: document.getElementById('status-btn'),
    releaseBtn: document.getElementById('release-btn'),
    shareBtn: document.getElementById('share-btn'),
    simBtn: document.getElementById('sim-btn'),
    navLink: document.getElementById('nav-link'),
    routeInfo: document.getElementById('route-info'),
    msg: document.getElementById('rider-msg')
  };

  var LABELS = {
    placed: 'Order placed', accepted: 'Rider assigned', on_the_way: 'On the way',
    delivered: 'Delivered', cancelled: 'Cancelled'
  };
  var NEXT = {
    accepted: { status: 'on_the_way', label: 'Picked up, start delivery' },
    on_the_way: { status: 'delivered', label: 'Mark as delivered' }
  };

  function say(text) { el.msg.textContent = text || ''; }
  function isLive() { return state.status === 'accepted' || state.status === 'on_the_way'; }
  function isOpen() { return !!NEXT[state.status]; }
  function target() { return state.status === 'on_the_way' ? data.dest : data.pickup; }

  /* ---------- UI ---------- */
  function renderUi() {
    el.badge.textContent = LABELS[state.status] || state.status;
    el.badge.className = 'badge badge--' + state.status;

    var next = NEXT[state.status];
    el.statusBtn.hidden = !next;
    if (next) el.statusBtn.textContent = next.label;
    el.releaseBtn.hidden = state.status !== 'accepted';
    el.shareBtn.hidden = !isLive();
    el.shareBtn.textContent = state.sharing ? 'Stop sharing my location' : 'Share my location';
    el.shareBtn.setAttribute('aria-pressed', state.sharing ? 'true' : 'false');

    var t = target();
    el.navLink.hidden = !isLive();
    el.navLink.href = EM.navUrl(t.lat, t.lng);
    el.navLink.textContent = state.status === 'on_the_way' ? 'Navigate to customer' : 'Navigate to shop';

    if (!isOpen()) {
      el.routeInfo.textContent = state.status === 'delivered' ? 'Delivered. Nice work.' : 'This order was cancelled.';
    }
  }

  /* ---------- Map ---------- */
  function updateRiderMarker() {
    if (!map || !state.pos) return;
    var ll = [state.pos.lat, state.pos.lng];
    if (!riderMarker) {
      riderMarker = L.marker(ll, { icon: EM.icon('rider', 'You'), zIndexOffset: 1000 }).addTo(map);
    } else {
      riderMarker.setLatLng(ll);
    }
  }

  function clearRoute() {
    if (routeLine && map) map.removeLayer(routeLine);
    routeLine = null;
    state.route = null;
  }

  /* Route via Geoapify. Throttled to one request per 30 s to stay inside the free daily allowance. */
  async function updateRoute(force) {
    if (!map || !state.pos || !isOpen()) return;
    var now = Date.now();
    if (!force && now - state.lastRouteAt < 30000) return;
    state.lastRouteAt = now;
    try {
      var t = target();
      var route = await EM.route(state.pos, t);
      clearRoute();
      routeLine = L.polyline(route.path, { color: '#4a9a12', weight: 6, opacity: 0.9 }).addTo(map);
      state.route = { seconds: route.seconds, meters: route.meters };
      var where = state.status === 'on_the_way' ? 'customer' : 'shop';
      el.routeInfo.textContent = EM.formatEta(route.seconds) + ' · ' + EM.formatDistance(route.meters) + ' to the ' + where;
    } catch (e) {
      el.routeInfo.textContent = 'Route unavailable. Use the navigation button instead.';
    }
  }

  function fitAll() {
    if (!map) return;
    var pts = [data.pickup, data.dest];
    if (state.pos) pts.push(state.pos);
    EM.bounds(pts, map);
  }

  /* ---------- Location sharing ---------- */
  function onPosition(p) {
    state.pos = { lat: p.coords.latitude, lng: p.coords.longitude };
    updateRiderMarker();
    updateRoute(false);
  }

  function onGeoError(err) {
    say(err.code === 1
      ? 'Location is blocked. Allow location access for this site, then tap Share my location again.'
      : 'We cannot find your location right now. Check that GPS is on.');
  }

  async function lockScreen() {
    try {
      if ('wakeLock' in navigator) state.wakeLock = await navigator.wakeLock.request('screen');
    } catch (e) { /* not supported or denied: keep the screen on manually */ }
  }

  function unlockScreen() {
    if (state.wakeLock) { state.wakeLock.release().catch(function () {}); state.wakeLock = null; }
  }

  async function sendLocation() {
    if (!state.pos || !isLive()) return;
    var payload = { lat: state.pos.lat, lng: state.pos.lng };
    if (state.status === 'on_the_way' && state.route) {
      payload.eta_seconds = state.route.seconds;
      payload.distance_m = state.route.meters;
    }
    try {
      var r = await EM.postJSON(data.location_url, payload);
      if (r.status === 401 || r.status === 409) {
        stopSharing();
        say(r.body.error || 'Location sharing stopped.');
      }
    } catch (e) { /* offline for a moment: the next tick will retry */ }
  }

  function startSharing() {
    if (state.sharing || !isLive()) return;
    if (!navigator.geolocation) { say('This browser cannot share location.'); return; }
    state.sharing = true;
    say('Sharing your location with the customer. Keep this screen open.');
    state.watchId = navigator.geolocation.watchPosition(onPosition, onGeoError,
      { enableHighAccuracy: true, maximumAge: 2000, timeout: 20000 });
    state.sendTimer = setInterval(sendLocation, 4000);
    lockScreen();
    renderUi();
  }

  function stopSharing() {
    state.sharing = false;
    if (state.watchId !== null) { navigator.geolocation.clearWatch(state.watchId); state.watchId = null; }
    if (state.sendTimer) { clearInterval(state.sendTimer); state.sendTimer = null; }
    stopSimulation();
    unlockScreen();
    renderUi();
  }

  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && state.sharing) lockScreen();
  });

  /* ---------- Test mode: open this page with ?sim=1 to fake a ride on a desktop ---------- */
  function stopSimulation() {
    if (state.simTimer) { clearInterval(state.simTimer); state.simTimer = null; }
    state.simulating = false;
    el.simBtn.textContent = 'Simulate a ride (testing)';
  }

  function startSimulation() {
    if (!isLive()) { say('Accept the order first, then simulate.'); return; }
    state.simulating = true;
    el.simBtn.textContent = 'Stop simulation';
    if (!state.sharing) {
      state.sharing = true;
      state.sendTimer = setInterval(sendLocation, 4000);
      renderUi();
    }
    state.simTimer = setInterval(function () {
      var t = target();
      if (!state.pos) state.pos = { lat: t.lat + 0.008, lng: t.lng - 0.008 };
      var dLat = t.lat - state.pos.lat, dLng = t.lng - state.pos.lng;
      if (Math.abs(dLat) + Math.abs(dLng) > 0.0004) {
        state.pos = { lat: state.pos.lat + dLat * 0.15, lng: state.pos.lng + dLng * 0.15 };
      }
      updateRiderMarker();
      updateRoute(false);
    }, 2500);
  }

  /* ---------- Buttons ---------- */
  async function changeStatus(next) {
    var payload = { status: next };
    if (next === 'delivered' && data.cash) {
      payload.cash_collected = window.confirm('Did you collect KES ' + data.total.toLocaleString('en-KE') + ' in cash from the customer?');
    }
    el.statusBtn.disabled = el.releaseBtn.disabled = true;
    var r = await EM.postJSON(data.status_url, payload);
    el.statusBtn.disabled = el.releaseBtn.disabled = false;
    if (!r.ok) { say(r.body.error || 'Could not update the order. Try again.'); return; }

    say('');
    state.status = r.body.status;
    clearRoute();
    state.lastRouteAt = 0;
    if (!isLive()) stopSharing();
    renderUi();
    if (state.status === 'accepted' && !state.sharing) startSharing();
    updateRoute(true);
    if (state.status === 'delivered') {
      say('Delivered. Taking you back to your deliveries…');
      setTimeout(function () { window.location.href = data.dashboard_url; }, 1500);
    }
  }

  el.statusBtn.addEventListener('click', function () {
    var next = NEXT[state.status];
    if (next) changeStatus(next.status);
  });
  el.releaseBtn.addEventListener('click', async function () {
    if (!window.confirm('Give this order back so another rider can take it?')) return;
    el.releaseBtn.disabled = true;
    var r = await EM.postJSON(data.release_url, {});
    if (r.ok) { stopSharing(); window.location.href = data.dashboard_url; return; }
    el.releaseBtn.disabled = false;
    say(r.body.error || 'Could not release the order.');
  });
  el.shareBtn.addEventListener('click', function () {
    if (state.sharing) { stopSharing(); say('Location sharing stopped.'); } else { startSharing(); }
  });
  el.simBtn.addEventListener('click', function () {
    if (state.simulating) { stopSharing(); say('Simulation stopped.'); } else { startSimulation(); }
  });
  if (new URLSearchParams(location.search).get('sim') === '1') el.simBtn.hidden = false;

  renderUi();
  if (isLive()) startSharing();  // the customer follows you from the moment you accept

  if (!EM.hasMaps()) return;
  map = EM.newMap(document.getElementById('map'), data.dest, 13);
  L.marker([data.pickup.lat, data.pickup.lng], { icon: EM.icon('shop', 'Shop') }).addTo(map);
  L.marker([data.dest.lat, data.dest.lng], { icon: EM.icon('home', 'Customer') }).addTo(map);
  fitAll();
  updateRiderMarker();
  updateRoute(true);
})();
