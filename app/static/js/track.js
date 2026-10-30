/* Customer: poll the order every few seconds and move the rider on the map. */
(function () {
  var data = EM.data();
  var state = data.initial;
  var STEPS = ['placed', 'accepted', 'on_the_way', 'delivered'];

  var headlineEl = document.getElementById('track-headline');
  var etaEl = document.getElementById('eta');
  var freshEl = document.getElementById('freshness');
  var stepsEl = document.getElementById('steps');

  var map = null, riderMarker = null, fittedWithRider = false;

  function isFinished(s) { return s.status === 'delivered' || s.status === 'cancelled'; }

  function renderSteps(s) {
    var current = STEPS.indexOf(s.status);
    stepsEl.classList.toggle('is-cancelled', s.status === 'cancelled');
    Array.prototype.forEach.call(stepsEl.children, function (li, i) {
      li.classList.toggle('is-done', current >= 0 && i < current);
      li.classList.toggle('is-current', i === current);
      if (i === current) li.setAttribute('aria-current', 'step'); else li.removeAttribute('aria-current');
    });
  }

  function renderInfo(s) {
    headlineEl.textContent = s.status_label;
    var r = s.rider;
    var eta = '';
    if (s.status === 'placed') eta = 'Waiting for a rider to accept your order.';
    else if (s.status === 'accepted') eta = (s.rider_name || 'Your rider') + ' is heading to the shop to collect your order.';
    else if (s.status === 'on_the_way') {
      eta = r && r.eta_seconds != null
        ? 'Arriving in about ' + EM.formatEta(r.eta_seconds) + (r.distance_m != null ? ' · ' + EM.formatDistance(r.distance_m) + ' away' : '')
        : (s.rider_name || 'Your rider') + ' is on the way.';
    }
    else if (s.status === 'delivered') eta = 'Your order has been delivered.';
    else if (s.status === 'cancelled') eta = 'This order was cancelled.';
    etaEl.textContent = eta;

    if (r && r.updated_at && s.server_time) {
      var age = Math.max(0, Math.round((Date.parse(s.server_time) - Date.parse(r.updated_at)) / 1000));
      freshEl.textContent = age > 45
        ? 'Rider location last updated ' + EM.formatAge(age) + '. They may have a weak signal.'
        : 'Rider location updated ' + EM.formatAge(age) + '.';
    } else {
      freshEl.textContent = '';
    }
  }

  function renderMap(s) {
    if (!map) return;
    if (!s.rider) {
      if (riderMarker) { map.removeLayer(riderMarker); riderMarker = null; }
      return;
    }
    var ll = [s.rider.lat, s.rider.lng];
    if (!riderMarker) {
      riderMarker = L.marker(ll, { icon: EM.icon('rider', 'Rider'), zIndexOffset: 1000 }).addTo(map);
    } else {
      riderMarker.setLatLng(ll);
    }
    if (!fittedWithRider) {
      fittedWithRider = true;
      EM.bounds([{ lat: s.rider.lat, lng: s.rider.lng }, s.pickup, s.dest], map);
    }
  }

  function render(s) { renderSteps(s); renderInfo(s); renderMap(s); }

  async function poll() {
    try {
      var res = await fetch(data.api_url, { cache: 'no-store' });
      if (res.ok) { state = await res.json(); render(state); }
    } catch (e) { /* network blip: try again next round */ }
    if (!isFinished(state)) setTimeout(poll, document.hidden ? 15000 : 4000);
  }

  if (EM.hasMaps()) {
    map = EM.newMap(document.getElementById('map'), state.dest, 14);
    L.marker([state.pickup.lat, state.pickup.lng], { icon: EM.icon('shop', 'Shop') }).addTo(map);
    L.marker([state.dest.lat, state.dest.lng], { icon: EM.icon('home', 'You') }).addTo(map);
    EM.bounds([state.pickup, state.dest], map);
  }

  render(state);
  setTimeout(poll, 4000);
})();
