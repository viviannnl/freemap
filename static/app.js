/* FreeMap frontend: a live, animated treasure map of free stuff.
 *
 * The server is stateless - it just returns the current set of free postings.
 * All the liveliness is computed here by diffing successive polls:
 *   - an id we've never seen        -> loot-drop (bounce in) + toast, first_seen=now
 *   - an id that dropped out of the crawl -> shatter, then remove ("gone")
 *   - freshness colour              -> age since first_seen (fresh/warm/cool)
 * first_seen lives in localStorage so freshness survives reloads. It's when THIS
 * browser first saw a posting, not the true Craigslist post time - so the UI says
 * "spotted", not "posted".
 */

const POLL_MS = 20000;
const FRESH_MS = 30 * 60 * 1000;   // < 30 min -> just dropped (gold, pulsing)
const WARM_MS = 3 * 60 * 60 * 1000; // < 3 h -> a few hours old (amber); older -> cool
const SEEN_TTL_MS = 24 * 60 * 60 * 1000; // forget postings unseen this long

const storage = FreeMapSearch.getStorage(window);
const savedSearch = FreeMapSearch.loadSettings(storage);
const searches = new FreeMapSearch.LatestSearch();
const state = {
  markers: new Map(),   // id -> {marker, find}
  finds: new Map(),     // id -> find (lookup cache for card/stash)
  lastLive: [],         // most recent crawl result (drives reflow on filter change)
  crawlIds: new Set(),  // ids present in the most recent crawl (present vs vanished)
  cat: 'all',
  radiusKm: savedSearch.radiusKm,
  center: { lat: savedSearch.lat, lon: savedSearch.lon },
  observedIds: new Set(), // only postings observed in the current search scope
  selectingCenter: false,
  loadingSelection: null,
  first: true,
  firstDone: false,
  stash: loadStash(),
  ring: null,
};

/* ---- first-seen store (localStorage) ---- */
function loadSeen() { try { return JSON.parse(storage.getItem('freemap.seen') || '{}'); } catch { return {}; } }
function saveSeen() { try { storage?.setItem('freemap.seen', JSON.stringify(seen)); } catch { /* Storage is optional. */ } }
let seen = loadSeen();
function ageMs(id, now) { return now - (seen[id] || now); }
function statusOf(id, now) {
  const a = ageMs(id, now);
  return a < FRESH_MS ? 'fresh' : a < WARM_MS ? 'warm' : 'cool';
}
function ageText(f) {
  if (f.status === 'gone') return '💨 likely gone';
  const m = f.age_min;
  if (m < 5) return '🔥 just spotted';
  if (m < 60) return `🔥 spotted ${m} min ago`;
  return `spotted ${Math.round(m / 60)}h ago`;
}

/* ---- map ---- */
const map = L.map('map', { zoomControl: false }).setView([state.center.lat, state.center.lon], 12);
L.control.zoom({ position: 'bottomright' }).addTo(map);
// Key-free OpenStreetMap tiles; CSS inverts them to a dark "treasure map".
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap', maxZoom: 19,
}).addTo(map);

/* ---- geometry ---- */
function distKm(f) { return FreeMapSearch.distanceKm(state.center, f); }
function eligible(f) {
  if (state.cat !== 'all' && f.category !== state.cat) return false;
  return FreeMapSearch.withinRadius(selection(), f);
}
// Craigslist geocodes many free posts to the same neighbourhood centroid, so pins
// stack. Fan them out by a small deterministic per-id offset (~<90 m), display only.
function jittered(f) {
  let h = 0;
  for (const ch of f.id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const ang = (h % 360) * Math.PI / 180;
  const rad = 0.0002 + ((h >> 9) % 100) / 100 * 0.0006;
  return [f.lat + rad * Math.cos(ang), f.lon + rad * Math.sin(ang)];
}

/* ---- pin element ---- */
function pinIcon(f) {
  const shortTitle = f.title.length > 22 ? f.title.slice(0, 21) + '…' : f.title;
  const tag = f.age_min < 60 ? `${f.age_min}m` : `${Math.round(f.age_min / 60)}h`;
  return L.divIcon({
    className: '',
    html: `<div class="pin ${f.status}" data-id="${f.id}">
             <div class="ring"></div>
             <div class="dot"><span class="glyph">${f.glyph}</span></div>
             <div class="tag">${shortTitle} · ${tag}</div>
           </div>`,
    iconSize: [44, 62], iconAnchor: [22, 62],
  });
}

/* ---- diff / render ---- */
function render(finds) {
  const now = Date.now();
  state.lastLive = finds;
  state.crawlIds = new Set(finds.map(f => f.id));
  // remember first sight + compute freshness for everything in this crawl
  finds.forEach(f => {
    state.observedIds.add(f.id);
    if (!seen[f.id]) seen[f.id] = now;
    f.age_min = Math.round(ageMs(f.id, now) / 60000);
    f.status = statusOf(f.id, now);
    state.finds.set(f.id, f);
  });
  saveSeen();

  const next = new Map();
  finds.forEach(f => { if (eligible(f)) next.set(f.id, f); });

  // add or update
  next.forEach((f, id) => {
    const existing = state.markers.get(id);
    if (existing && existing.removalTimer) {
      clearTimeout(existing.removalTimer);
      existing.removalTimer = null;
      existing.marker._icon?.querySelector('.pin')?.classList.remove('shattering');
    }
    if (!existing) {
      const marker = L.marker(jittered(f), { icon: pinIcon(f) }).addTo(map);
      marker.on('click', () => openCard(id));
      state.markers.set(id, { marker, find: f });
      const el = marker._icon && marker._icon.querySelector('.pin');
      if (el && !state.first) el.classList.add('dropping');
    } else if (existing.find.status !== f.status) {
      existing.marker.setIcon(pinIcon(f));   // freshness changed -> recolour
      existing.find = f;
      existing.marker.off('click').on('click', () => openCard(id));
    } else {
      existing.find = f;
    }
  });

  // remove markers no longer drawn. If the id vanished from the crawl entirely
  // it was claimed -> shatter; if it's merely filtered out, remove quietly.
  state.markers.forEach((m, id) => {
    if (next.has(id)) return;
    const vanished = !state.crawlIds.has(id);
    const el = m.marker._icon && m.marker._icon.querySelector('.pin');
    if (vanished && el) {
      el.classList.add('shattering');
      m.removalTimer = setTimeout(() => {
        map.removeLayer(m.marker);
        if (state.markers.get(id) === m) state.markers.delete(id);
      }, 600);
    } else {
      map.removeLayer(m.marker);
      state.markers.delete(id);
    }
  });

  document.getElementById('countN').textContent = next.size;
  state.first = false;
  pruneSeen(now);
}

function pruneSeen(now) {
  let changed = false;
  for (const id of Object.keys(seen)) {
    if (!state.crawlIds.has(id) && now - seen[id] > SEEN_TTL_MS) { delete seen[id]; changed = true; }
  }
  if (changed) saveSeen();
}

async function poll() {
  const selected = selection();
  const key = FreeMapSearch.requestUrl(selected);
  if (state.loadingSelection?.key === key) return;
  const pending = { key };
  state.loadingSelection = pending;
  setSearchStatus('Updating finds…', 'loading');
  try {
    const data = await searches.run(selected);
    if (!data) return;
    const prevIds = new Set(state.markers.keys());
    render(data.finds || []);
    const newOnes = [...state.markers.keys()].filter(id => !prevIds.has(id));
    if (!state.firstDone) state.firstDone = true;
    else if (newOnes.length) {
      const f = state.finds.get(newOnes[0]);
      if (f) toast(`${f.glyph} New drop: ${f.title.slice(0, 30)}`);
    }
    renderStash();
    document.getElementById('locationLabel').textContent = `${data.region.name} · free stuff, live`;
    setSearchStatus(state.markers.size ? 'Live · distances from selected center' : 'No finds in this radius · try a wider search', 'live');
  } catch (e) {
    console.warn('poll failed', e);
    setSearchStatus(e.message, 'error');
  } finally {
    if (state.loadingSelection === pending) state.loadingSelection = null;
  }
}

/* ---- selected center ---- */
function selection() { return { ...state.center, radiusKm: state.radiusKm }; }
function setSearchStatus(message, status) {
  if (state.selectingCenter) return;
  document.getElementById('searchStatus').textContent = message;
  const live = document.getElementById('liveStatus');
  live.dataset.status = status;
  document.getElementById('liveLabel').textContent = status === 'error' ? 'Retrying' : status === 'loading' ? 'Updating' : 'Live';
}
const centerButton = document.getElementById('chooseCenter');
const centerMarker = L.circleMarker([state.center.lat, state.center.lon], {
  radius: 7, color: '#FFD166', fillColor: '#0a0f1c', fillOpacity: 1, weight: 3,
  interactive: false,
}).addTo(map);
function showSelectedCenter() {
  centerMarker.setLatLng([state.center.lat, state.center.lon]);
  document.getElementById('centerCoords').textContent = `${state.center.lat.toFixed(4)}, ${state.center.lon.toFixed(4)}`;
  drawRing();
}
function setSelectingCenter(active) {
  state.selectingCenter = active;
  if (active) card.classList.remove('open');
  centerButton.classList.toggle('on', active);
  centerButton.setAttribute('aria-pressed', String(active));
  centerButton.textContent = active ? 'Cancel selection' : 'Choose center';
  document.getElementById('map').classList.toggle('choosing-center', active);
  document.getElementById('searchStatus').textContent = active ? 'Click the map to set center · Esc to cancel' : 'Distances from selected center';
}
function beginSearch() {
  clearTimeout(radiusTimer);
  searches.cancel();
  state.loadingSelection = null;
  state.markers.forEach(m => { clearTimeout(m.removalTimer); map.removeLayer(m.marker); });
  state.markers.clear();
  state.lastLive = [];
  state.crawlIds.clear();
  state.observedIds.clear();
  state.first = true;
  state.firstDone = false;
  document.getElementById('countN').textContent = '0';
  card.classList.remove('open');
  FreeMapSearch.saveSettings(storage, selection());
  showSelectedCenter();
  renderStash();
  poll();
}
centerButton.addEventListener('click', () => setSelectingCenter(!state.selectingCenter));
map.on('click', event => {
  if (!state.selectingCenter) return;
  // Leaflet wraps world copies when users pan; keep longitude in the API range.
  state.center = { lat: event.latlng.lat, lon: ((event.latlng.lng + 180) % 360 + 360) % 360 - 180 };
  document.getElementById('locationLabel').textContent = 'Selected center · free stuff, live';
  setSelectingCenter(false);
  beginSearch();
});
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && state.selectingCenter) setSelectingCenter(false);
});
document.getElementById('resetSearch').addEventListener('click', () => {
  setSelectingCenter(false);
  state.center = { lat: FreeMapSearch.DEFAULTS.lat, lon: FreeMapSearch.DEFAULTS.lon };
  state.radiusKm = FreeMapSearch.DEFAULTS.radiusKm;
  radiusInput.value = state.radiusKm;
  document.getElementById('radiusLabel').textContent = `${state.radiusKm} km`;
  document.getElementById('locationLabel').textContent = 'Vancouver · free stuff, live';
  map.setView([state.center.lat, state.center.lon], 12);
  beginSearch();
});

/* ---- radius ring ---- */
function drawRing() {
  if (state.ring) map.removeLayer(state.ring);
  state.ring = L.circle([state.center.lat, state.center.lon], {
    radius: state.radiusKm * 1000, color: '#FFD166', weight: 1.5, opacity: .35,
    dashArray: '6 8', fillColor: '#FFD166', fillOpacity: .03,
  }).addTo(map);
}

/* ---- filters ---- */
document.getElementById('chips').addEventListener('click', e => {
  const chip = e.target.closest('.chip'); if (!chip) return;
  document.querySelectorAll('#chips .chip').forEach(c => c.classList.toggle('on', c === chip));
  state.cat = chip.dataset.cat;
  render(state.lastLive);
});
const radiusInput = document.getElementById('radius');
let radiusTimer = null;
radiusInput.value = state.radiusKm;
document.getElementById('radiusLabel').textContent = `${state.radiusKm} km`;
radiusInput.addEventListener('input', () => {
  state.radiusKm = +radiusInput.value;
  document.getElementById('radiusLabel').textContent = `${state.radiusKm} km`;
  drawRing(); render(state.lastLive);
  searches.cancel();
  state.loadingSelection = null;
  FreeMapSearch.saveSettings(storage, selection());
  clearTimeout(radiusTimer);
  radiusTimer = setTimeout(beginSearch, 350);
});

/* ---- listing card ---- */
const card = document.getElementById('card');
let cardId = null;
const postedCache = {};   // id -> ISO string (or null); posted time never changes
function fmtPosted(iso) {
  const t = Date.parse(iso); if (isNaN(t)) return null;
  const mins = Math.round((Date.now() - t) / 60000);
  if (mins < 1) return '🔥 posted just now';
  if (mins < 60) return `🔥 posted ${mins} min ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs < 6 ? '🔥 ' : ''}posted ${hrs}h ago`;
  const days = Math.round(hrs / 24);
  return `posted ${days} day${days > 1 ? 's' : ''} ago`;
}
async function loadPosted(id, url) {
  const el = document.getElementById('cardAge');
  if (postedCache[id] !== undefined) {
    const t = fmtPosted(postedCache[id]);
    if (t && cardId === id) el.textContent = t;
    return;
  }
  try {
    const r = await fetch('/api/posted?u=' + encodeURIComponent(url));
    const d = await r.json();
    postedCache[id] = d.posted;
    const t = fmtPosted(d.posted);
    if (t && cardId === id) el.textContent = t;  // guard: user may have opened another card
  } catch { /* keep the "spotted" fallback */ }
}
function openCard(id) {
  const f = state.finds.get(id); if (!f) return;
  cardId = id;
  document.getElementById('cardTitle').textContent = f.title;
  document.getElementById('cardAge').textContent = ageText(f);   // instant fallback
  loadPosted(id, f.url);                                          // then the true posted time
  const hood = f.neighborhood ? `<b>${f.neighborhood}</b> · ` : '';
  document.getElementById('cardLoc').innerHTML = `📍 ${hood}${distKm(f).toFixed(1)} km away`;
  document.getElementById('cardCta').href = f.url;
  const photo = document.getElementById('cardPhoto');
  const glyph = document.getElementById('cardGlyph');
  if (f.thumb) { photo.style.backgroundImage = `url("${f.thumb}")`; glyph.style.display = 'none'; }
  else { photo.style.backgroundImage = ''; glyph.style.display = ''; glyph.textContent = f.glyph; }
  document.getElementById('cardHeart').textContent = inStash(id) ? '❤️' : '🤍';
  card.classList.add('open');
}
document.getElementById('cardClose').onclick = () => card.classList.remove('open');
document.getElementById('cardHeart').onclick = () => { if (cardId) toggleStash(cardId); };

/* ---- stash (localStorage) ---- */
function loadStash() { try { return JSON.parse(storage.getItem('freemap.stash') || '[]'); } catch { return []; } }
function saveStash() { try { storage?.setItem('freemap.stash', JSON.stringify(state.stash)); } catch { /* Saving still works for this session. */ } }
function inStash(id) { return state.stash.some(s => s.id === id); }
function toggleStash(id) {
  const f = state.finds.get(id); if (!f) return;
  if (inStash(id)) state.stash = state.stash.filter(s => s.id !== id);
  else state.stash.unshift({ id: f.id, title: f.title, glyph: f.glyph, thumb: f.thumb, url: f.url });
  saveStash(); renderStash();
  if (cardId === id) document.getElementById('cardHeart').textContent = inStash(id) ? '❤️' : '🤍';
}
function renderStash() {
  const list = document.getElementById('stashList');
  document.getElementById('stashN').textContent = state.stash.length;
  document.getElementById('stashCount').textContent = `${state.stash.length} saved`;
  if (!state.stash.length) {
    list.innerHTML = `<div class="empty">Nothing stashed yet.<br>Tap 🤍 on a find to keep it here.</div>`;
    return;
  }
  list.innerHTML = state.stash.map(s => {
    const live = state.finds.get(s.id);
    const goneNow = state.observedIds.has(s.id) && !state.crawlIds.has(s.id);
    const meta = goneNow ? '<span style="color:#e06a6a">💨 likely gone</span>'
      : (live ? ageText(live) : 'saved');
    const bg = s.thumb ? `style="background-image:url('${s.thumb}')"` : '';
    return `<div class="sitem" data-id="${s.id}">
      <div class="sthumb" ${bg}>${s.thumb ? '' : s.glyph}</div>
      <div><div class="si-t">${s.title}</div><div class="si-m">${meta}</div></div>
      <div class="si-x" data-x="${s.id}">×</div></div>`;
  }).join('');
}
document.getElementById('stashList').addEventListener('click', e => {
  const x = e.target.closest('.si-x');
  if (x) { toggleStash(x.dataset.x); return; }
  const item = e.target.closest('.sitem'); if (!item) return;
  const f = state.finds.get(item.dataset.id);
  if (f) { map.setView([f.lat, f.lon], 15); openCard(item.dataset.id); }
  else { const s = state.stash.find(s => s.id === item.dataset.id); if (s) window.open(s.url, '_blank'); }
});
document.getElementById('stashBtn').onclick = () => document.getElementById('stash').classList.toggle('open');

/* ---- cursor flashlight ---- */
const torch = document.getElementById('flashlight');
let mx = 0, my = 0, torchQueued = false;
const mapEl = document.getElementById('map');
mapEl.addEventListener('mouseenter', () => document.body.classList.add('torch'));
mapEl.addEventListener('mouseleave', () => {
  document.body.classList.remove('torch');
  document.querySelectorAll('.pin.awake').forEach(p => p.classList.remove('awake'));
});
window.addEventListener('mousemove', e => {
  mx = e.clientX; my = e.clientY;
  torch.style.transform = `translate(${mx}px, ${my}px)`;
  if (!torchQueued) { torchQueued = true; requestAnimationFrame(wakePins); }
});
function wakePins() {
  torchQueued = false;
  const R = 150;
  state.markers.forEach(m => {
    const el = m.marker._icon && m.marker._icon.querySelector('.pin');
    if (!el) return;
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
    el.classList.toggle('awake', Math.hypot(cx - mx, cy - my) < R);
  });
}

/* ---- toast ---- */
let toastTimer = null;
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 3500);
}

/* ---- go ---- */
showSelectedCenter();
renderStash();
poll();
setInterval(poll, POLL_MS);
