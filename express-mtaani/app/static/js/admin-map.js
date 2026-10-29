/* Admin dashboard: shops and live rider positions. */
(function () {
  if (!EM.hasMaps()) return;
  var data = EM.data();
  var map = EM.newMap(document.getElementById('map'), data.center, 12);
  var countEl = document.getElementById('rider-count');
  var markers = {};
  var fitted = false;

  data.shops.forEach(function (s) {
    L.marker([s.lat, s.lng], { icon: EM.icon('shop', s.name) }).addTo(map);
  });

  async function refresh() {
    try {
      var res = await fetch(data.riders_url, { credentials: 'same-origin', cache: 'no-store' });
      if (!res.ok) return;
      var json = await res.json();
      var seen = {};
      json.riders.forEach(function (r) {
        var ll = [r.lat, r.lng];
        if (markers[r.id]) markers[r.id].setLatLng(ll);
        else markers[r.id] = L.marker(ll, { icon: EM.icon('rider', r.name.split(' ')[0]), zIndexOffset: 1000 }).addTo(map);
        seen[r.id] = true;
      });
      Object.keys(markers).forEach(function (id) {
        if (!seen[id]) { map.removeLayer(markers[id]); delete markers[id]; }
      });
      countEl.textContent = json.riders.length + ' rider' + (json.riders.length === 1 ? '' : 's') + ' online';
      if (!fitted && json.riders.length) {
        fitted = true;
        EM.bounds(json.riders.concat(data.shops), map);
      }
    } catch (e) { /* try again next tick */ }
  }

  refresh();
  setInterval(refresh, 10000);
})();
