/* Admin shop form: click the map or drag the pin to set the pickup location. */
(function () {
  if (!EM.hasMaps()) return;
  var data = EM.data();
  var latEl = document.getElementById('lat');
  var lngEl = document.getElementById('lng');
  var statusEl = document.getElementById('pin-status');
  var saved = { lat: parseFloat(latEl.value), lng: parseFloat(lngEl.value) };
  var hasSaved = isFinite(saved.lat) && isFinite(saved.lng);

  var map = EM.newMap(document.getElementById('map'), hasSaved ? saved : data.center, hasSaved ? 16 : 12);
  var marker = null;

  function setPin(ll) {
    if (!marker) {
      marker = L.marker([ll.lat, ll.lng], { draggable: true, icon: EM.icon('shop', 'Pickup') }).addTo(map);
      marker.on('dragend', function () { var p = marker.getLatLng(); setPin({ lat: p.lat, lng: p.lng }); });
    } else {
      marker.setLatLng([ll.lat, ll.lng]);
    }
    latEl.value = ll.lat.toFixed(6);
    lngEl.value = ll.lng.toFixed(6);
    statusEl.textContent = 'Location set: ' + latEl.value + ', ' + lngEl.value;
  }

  map.on('click', function (ev) { setPin({ lat: ev.latlng.lat, lng: ev.latlng.lng }); });
  if (hasSaved) setPin(saved);
})();
