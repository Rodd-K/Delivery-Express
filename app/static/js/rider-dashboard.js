/* Rider dashboard: go online, see nearby orders (nearest first), accept one. */
(function () {
  var data = EM.data();
  var btn = document.getElementById('online-btn');
  var msg = document.getElementById('online-msg');
  var badge = document.getElementById('online-badge');
  var list = document.getElementById('available');
  var note = document.getElementById('available-note');
  var state = { online: false, pos: null, watchId: null, presenceTimer: null, pollTimer: null, wakeLock: null };

  function say(text) { msg.textContent = text || ''; }

  function setUi(on) {
    badge.textContent = on ? 'Online' : 'Offline';
    badge.className = 'badge' + (on ? ' badge--on_the_way' : '');
    btn.textContent = on ? 'Go offline' : 'Go online';
    btn.className = 'btn btn--block ' + (on ? 'btn--ghost' : 'btn--primary');
  }

  async function lockScreen() {
    try { if ('wakeLock' in navigator) state.wakeLock = await navigator.wakeLock.request('screen'); } catch (e) { /* optional */ }
  }
  function unlockScreen() {
    if (state.wakeLock) { state.wakeLock.release().catch(function () {}); state.wakeLock = null; }
  }
  document.addEventListener('visibilitychange', function () {
    if (document.visibilityState === 'visible' && state.online) lockScreen();
  });

  function text(tag, cls, content) {
    var el = document.createElement(tag);
    if (cls) el.className = cls;
    el.textContent = content;
    return el;
  }

  function render(orders, reason) {
    list.innerHTML = '';
    if (!state.online) { note.textContent = 'Go online to see nearby orders.'; return; }
    if (reason === 'busy') { note.textContent = 'Finish your current delivery to see new orders.'; return; }
    if (!orders.length) { note.textContent = 'No new orders near you right now. This list refreshes automatically.'; return; }
    note.textContent = orders.length + ' order' + (orders.length === 1 ? '' : 's') + ' near you, nearest first.';
    orders.forEach(function (o) {
      var li = document.createElement('li');
      var card = document.createElement('div');
      card.className = 'order-card';
      card.appendChild(text('span', 'order-card__title', o.shop + ' · ' + o.to_shop_km + ' km from you'));
      card.appendChild(text('span', 'order-card__meta', 'Deliver to: ' + o.deliver_to));
      card.appendChild(text('span', 'order-card__meta',
        o.items + ' item' + (o.items === 1 ? '' : 's') + ' · trip ' + o.trip_km + ' km · delivery fee KES ' + o.fee +
        (o.cash ? ' · collect KES ' + o.total + ' cash' : '')));
      var b = text('button', 'btn btn--primary btn--small', 'Accept order #' + o.id);
      b.type = 'button';
      b.addEventListener('click', function () { accept(o.id, b); });
      card.appendChild(b);
      li.appendChild(card);
      list.appendChild(li);
    });
  }

  async function loadAvailable() {
    if (!state.online) return;
    try {
      var res = await fetch(data.available_url, { credentials: 'same-origin', cache: 'no-store' });
      if (!res.ok) return;
      var json = await res.json();
      render(json.orders || [], json.reason);
    } catch (e) { /* try again next tick */ }
  }

  async function accept(id, button) {
    button.disabled = true;
    var r = await EM.postJSON(data.accept_url.replace('/0/', '/' + id + '/'), {});
    if (r.ok) { window.location.href = r.body.next; return; }
    say(r.body.error || 'Could not accept that order.');
    button.disabled = false;
    loadAvailable();
  }

  async function sendPresence() {
    if (!state.pos) return;
    var r = await EM.postJSON(data.presence_url, { online: true, lat: state.pos.lat, lng: state.pos.lng });
    if (r.status === 401 || r.status === 403) { say('You were signed out. Please sign in again.'); stop(false); }
  }

  var firstFix = true;
  function onPosition(p) {
    state.pos = { lat: p.coords.latitude, lng: p.coords.longitude };
    if (firstFix) {
      firstFix = false;
      say('You are online. Keep this page open so riders and customers see you.');
      sendPresence().then(loadAvailable);
    }
  }

  function onError(err) {
    say(err.code === 1
      ? 'Location is blocked. Allow location access for this site, then tap Go online again.'
      : 'We cannot find your location right now. Check that GPS is on.');
    if (err.code === 1) stop(true);
  }

  function start() {
    if (!navigator.geolocation) { say('This browser cannot share location.'); return; }
    state.online = true;
    firstFix = true;
    setUi(true);
    say('Finding your location…');
    state.watchId = navigator.geolocation.watchPosition(onPosition, onError,
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 20000 });
    state.presenceTimer = setInterval(sendPresence, 8000);
    state.pollTimer = setInterval(loadAvailable, 6000);
    lockScreen();
  }

  async function stop(tellServer) {
    state.online = false;
    if (state.watchId !== null) { navigator.geolocation.clearWatch(state.watchId); state.watchId = null; }
    clearInterval(state.presenceTimer);
    clearInterval(state.pollTimer);
    unlockScreen();
    setUi(false);
    render([], null);
    if (tellServer) { try { await EM.postJSON(data.presence_url, { online: false }); } catch (e) { /* ignore */ } }
  }

  btn.addEventListener('click', function () {
    if (state.online) { stop(true); say('You are offline.'); } else { start(); }
  });

  setUi(false);
  render([], null);
  if (data.online) start(); // you were online when you left: pick up where you stopped
})();
