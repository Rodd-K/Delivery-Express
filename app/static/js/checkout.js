/* Checkout: search an address or drop a pin, see the delivery fee, then place the order. */
(function () {
  var data = EM.data();
  var latEl = document.getElementById('dest_lat');
  var lngEl = document.getElementById('dest_lng');
  var addrEl = document.getElementById('dest_address');
  var statusEl = document.getElementById('pin-status');
  var form = document.getElementById('order-form');
  var addrTouched = !!addrEl.value;
  var feeEl = document.getElementById('fee-estimate');
  var totalEl = document.getElementById('total-estimate');
  var subtotal = JSON.parse(document.getElementById('em-subtotal').textContent);

  function money(n) { return 'KES ' + n.toLocaleString('en-KE'); }
  function updateFee(ll) {
    var km = EM.haversine(data.shop, ll);
    var fee = Math.ceil((data.fee_base + Math.ceil(km) * data.fee_per_km) / 10) * 10;
    feeEl.textContent = money(fee);
    totalEl.textContent = money(subtotal + fee);
  }

  addrEl.addEventListener('input', function () { addrTouched = true; });

  form.addEventListener('submit', function (ev) {
    if (!latEl.value || !lngEl.value) {
      ev.preventDefault();
      statusEl.textContent = 'Search for your address or tap the map to drop a pin first.';
      statusEl.classList.add('hint--error');
    }
  });

  if (!EM.hasMaps()) return; // no API key: the page explains it

  var map = EM.newMap(document.getElementById('map'), data.center, 13);
  L.marker([data.shop.lat, data.shop.lng], { icon: EM.icon('shop', 'Shop') }).addTo(map);
  var marker = null;

  function setPin(ll, reverse) {
    if (!marker) {
      marker = L.marker([ll.lat, ll.lng], { draggable: true, icon: EM.icon('home', 'Deliver here') }).addTo(map);
      marker.on('dragend', function () {
        var p = marker.getLatLng();
        setPin({ lat: p.lat, lng: p.lng }, true);
      });
    } else {
      marker.setLatLng([ll.lat, ll.lng]);
    }
    latEl.value = ll.lat.toFixed(6);
    lngEl.value = ll.lng.toFixed(6);
    statusEl.classList.remove('hint--error');
    statusEl.textContent = 'Pin set. Drag it to adjust.';
    updateFee(ll);
    if (reverse) {
      EM.reverse(ll).then(function (text) {
        if (text && !addrTouched) addrEl.value = text.slice(0, 255);
      }).catch(function () { /* the customer can still type an address */ });
    }
  }

  map.on('click', function (ev) { setPin({ lat: ev.latlng.lat, lng: ev.latlng.lng }, true); });

  /* ---------- Address search (combobox) ---------- */
  var input = document.getElementById('place-search');
  var list = document.getElementById('place-results');
  var results = [];
  var active = -1;
  var timer = null;
  var controller = null;

  function closeList() {
    list.hidden = true;
    list.innerHTML = '';
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
    results = [];
    active = -1;
  }

  function highlight(i) {
    active = i;
    Array.prototype.forEach.call(list.children, function (li, idx) {
      li.setAttribute('aria-selected', idx === i ? 'true' : 'false');
      if (idx === i) input.setAttribute('aria-activedescendant', li.id);
    });
  }

  function choose(i) {
    var r = results[i];
    if (!r) return;
    input.value = r.label;
    if (!addrTouched) addrEl.value = r.label.slice(0, 255);
    map.setView([r.lat, r.lng], 17);
    setPin({ lat: r.lat, lng: r.lng }, false);
    closeList();
  }

  function showResults(items) {
    results = items;
    list.innerHTML = '';
    if (!items.length) { closeList(); return; }
    items.forEach(function (r, i) {
      var li = document.createElement('li');
      li.id = 'place-opt-' + i;
      li.setAttribute('role', 'option');
      li.textContent = r.label;
      li.addEventListener('mousedown', function (e) { e.preventDefault(); choose(i); });
      list.appendChild(li);
    });
    list.hidden = false;
    input.setAttribute('aria-expanded', 'true');
    highlight(-1);
  }

  input.addEventListener('input', function () {
    clearTimeout(timer);
    var text = input.value.trim();
    if (text.length < 3) { closeList(); return; }
    timer = setTimeout(async function () {
      if (controller) controller.abort();
      controller = new AbortController();
      try {
        var center = map.getCenter();
        showResults(await EM.autocomplete(text, { lat: center.lat, lng: center.lng }, controller.signal));
      } catch (e) {
        if (e.name !== 'AbortError') statusEl.textContent = 'Address search is not working right now. Tap the map to drop a pin instead.';
      }
    }, 350);
  });

  input.addEventListener('keydown', function (e) {
    if (list.hidden) return;
    if (e.key === 'ArrowDown') { e.preventDefault(); highlight((active + 1) % results.length); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); highlight((active - 1 + results.length) % results.length); }
    else if (e.key === 'Enter' && active >= 0) { e.preventDefault(); choose(active); }
    else if (e.key === 'Escape') { closeList(); }
  });
  input.addEventListener('blur', function () { setTimeout(closeList, 150); });

  document.getElementById('use-location').addEventListener('click', function () {
    if (!navigator.geolocation) {
      statusEl.textContent = 'Your browser cannot share your location. Tap the map instead.';
      return;
    }
    statusEl.textContent = 'Finding you…';
    navigator.geolocation.getCurrentPosition(function (pos) {
      var ll = { lat: pos.coords.latitude, lng: pos.coords.longitude };
      map.setView([ll.lat, ll.lng], 17);
      setPin(ll, true);
    }, function () {
      statusEl.textContent = 'We could not get your location. Allow location access or tap the map.';
    }, { enableHighAccuracy: true, timeout: 15000 });
  });

  // Re-render after a validation error: restore the pin.
  if (latEl.value && lngEl.value) {
    var saved = { lat: parseFloat(latEl.value), lng: parseFloat(lngEl.value) };
    if (isFinite(saved.lat) && isFinite(saved.lng)) {
      map.setView([saved.lat, saved.lng], 16);
      setPin(saved, false);
    }
  }
})();
