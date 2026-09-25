/* Shared shell for both maps: the map itself, the pin diff engine, the cursor
 * flashlight, the radius ring, the listing card and the toast.
 *
 * The server is stateless - it just returns the current set of postings. All the
 * liveliness is computed here by diffing successive polls:
 *   - an id we've never seen        -> loot-drop (bounce in) + toast, first_seen=now
 *   - an id that dropped out of the crawl -> shatter, then remove ("gone")
 *   - freshness colour              -> age since first_seen (fresh/warm/cool)
 * first_seen lives in localStorage so freshness survives reloads. It's when THIS
 * browser first saw a posting, not the true Craigslist post time - so the UI says
 * "spotted", not "posted".
 *
 * A mode (see mode-free.js, mode-rentals.js) supplies what differs: where to poll,
 * what a pin looks like, which items pass the current filters, and what to put on
 * the card. Everything else is here, once.
 */

const POLL_MS = 20000;
const FRESH_MS = 30 * 60 * 1000;   // < 30 min -> just spotted (bright, pulsing)
const WARM_MS = 3 * 60 * 60 * 1000; // < 3 h -> a few hours old; older -> cool
const SEEN_TTL_MS = 24 * 60 * 60 * 1000; // forget postings unseen this long

const state = {
  markers: new Map(),   // id -> {marker, item}
  finds: new Map(),     // id -> item (lookup cache for card/list/stash)
  lastLive: [],         // most recent crawl result (drives reflow on filter change)
  crawlIds: new Set(),  // ids present in the most recent crawl (present vs vanished)
  listed: 0,            // how many postings Craigslist says exist in the area
  center: { lat: 49.2606, lon: -123.1140 },
  radiusKm: 10,
  first: true,
  firstDone: false,
  ring: null,
};

let mode = null;   // set by Shell.init
let map = null;

/* ---- first-seen store (localStorage) ----
 * Namespaced per mode: a free sofa and a rental are different things and shouldn't
 * share a freshness clock. Free stuff keeps the original "freemap." keys so anyone
 * with a stash saved from the live site doesn't lose it. */
let seen = {};
function seenKey() { return mode.key + '.seen'; }
function loadSeen() { try { return JSON.parse(localStorage.getItem(seenKey()) || '{}'); } catch { return {}; } }
function saveSeen() { localStorage.setItem(seenKey(), JSON.stringify(seen)); }
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

/* ---- geometry ---- */
function haversineKm(a, b, c, d) {
  const R = 6371, r = Math.PI / 180;
  const dp = (c - a) * r, dl = (d - b) * r;
  const x = Math.sin(dp / 2) ** 2 + Math.cos(a * r) * Math.cos(c * r) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}
// Distance from whatever the mode is measuring against: the city centre for free
// stuff, your dropped anchor pin for rentals.
function distKm(f) {
  const o = mode.origin();
  return haversineKm(o.lat, o.lon, f.lat, f.lon);
}
// Craigslist geocodes many posts to the same neighbourhood centroid, so pins stack.
// Fan them out by a small deterministic per-id offset (~<90 m), display only.
function jittered(f) {
  let h = 0;
  for (const ch of f.id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const ang = (h % 360) * Math.PI / 180;
  const rad = 0.0002 + ((h >> 9) % 100) / 100 * 0.0006;
  return [f.lat + rad * Math.cos(ang), f.lon + rad * Math.sin(ang)];
}

/* ---- diff / render ---- */
function render(items) {
  const now = Date.now();
  state.lastLive = items;
  state.crawlIds = new Set(items.map(f => f.id));
  // remember first sight + compute freshness for everything in this crawl
  items.forEach(f => {
    if (!seen[f.id]) seen[f.id] = now;
    f.age_min = Math.round(ageMs(f.id, now) / 60000);
    f.status = statusOf(f.id, now);
    state.finds.set(f.id, f);
  });
  saveSeen();

  const next = new Map();
  items.forEach(f => { if (mode.eligible(f)) next.set(f.id, f); });

  // add or update
  next.forEach((f, id) => {
    const existing = state.markers.get(id);
    if (!existing) {
      const marker = L.marker(jittered(f), { icon: mode.pinIcon(f) }).addTo(map);
      marker.on('click', () => openCard(id));
      state.markers.set(id, { marker, item: f });
      const el = marker._icon && marker._icon.querySelector('.pin');
      if (el && !state.first) el.classList.add('dropping');
    } else if (mode.pinChanged(existing.item, f)) {
      existing.marker.setIcon(mode.pinIcon(f));
      existing.item = f;
      existing.marker.off('click').on('click', () => openCard(id));
    } else {
      existing.item = f;
    }
  });

  // remove markers no longer drawn. If the id vanished from the crawl entirely it
  // was claimed or taken down -> shatter; if it's merely filtered out, go quietly.
  state.markers.forEach((m, id) => {
    if (next.has(id)) return;
    const vanished = !state.crawlIds.has(id);
    const el = m.marker._icon && m.marker._icon.querySelector('.pin');
    if (vanished && el) {
      el.classList.add('shattering');
      setTimeout(() => { map.removeLayer(m.marker); state.markers.delete(id); }, 600);
    } else {
      map.removeLayer(m.marker);
      state.markers.delete(id);
    }
  });

  state.first = false;
  pruneSeen(now);
  mode.afterRender([...next.values()]);
}

function pruneSeen(now) {
  let changed = false;
  for (const id of Object.keys(seen)) {
    if (!state.crawlIds.has(id) && now - seen[id] > SEEN_TTL_MS) { delete seen[id]; changed = true; }
  }
  if (changed) saveSeen();
}

async function poll() {
  try {
    const r = await fetch(mode.endpoint);
    const data = await r.json();
    if (data.center) state.center = data.center;
    if (data.listed) state.listed = data.listed;
    if (mode.onData) mode.onData(data);
    const prevIds = new Set(state.markers.keys());
    render(data[mode.itemsKey] || []);
    const newOnes = [...state.markers.keys()].filter(id => !prevIds.has(id));
    if (!state.firstDone) state.firstDone = true;
    else if (newOnes.length) {
      const f = state.finds.get(newOnes[0]);
      if (f) toast(mode.newToast(f));
    }
    if (mode.afterPoll) mode.afterPoll();
  } catch (e) { console.warn('poll failed', e); }
}

/* ---- radius ring ----
 * Same component for both maps: centred on the city for free stuff, on your anchor
 * for rentals, with the radius coming from whichever slider the mode owns. */
function drawRing() {
  if (state.ring) map.removeLayer(state.ring);
  const o = mode.origin();
  state.ring = L.circle([o.lat, o.lon], {
    radius: state.radiusKm * 1000, color: mode.accent, weight: 1.5, opacity: .35,
    dashArray: '6 8', fillColor: mode.accent, fillOpacity: .03,
  }).addTo(map);
}

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
  else { photo.style.backgroundImage = ''; glyph.style.display = ''; glyph.textContent = mode.cardGlyph(f); }
  document.getElementById('cardHeart').textContent = inStash(id) ? '❤️' : '🤍';
  mode.card(f);                       // the rows that differ: price/beds, or FREE
  card.classList.add('open');
  if (mode.onCardOpen) mode.onCardOpen(f);
}
document.getElementById('cardClose').onclick = () => card.classList.remove('open');
document.getElementById('cardHeart').onclick = () => { if (cardId) toggleStash(cardId); };

/* ---- stash (localStorage) ----
 * Both modes save things for later; only the dock that shows them differs. */
let stash = [];
function stashKey() { return mode.key + '.stash'; }
function loadStash() { try { return JSON.parse(localStorage.getItem(stashKey()) || '[]'); } catch { return []; } }
function saveStash() { localStorage.setItem(stashKey(), JSON.stringify(stash)); }
function inStash(id) { return stash.some(s => s.id === id); }
function toggleStash(id) {
  const f = state.finds.get(id); if (!f) return;
  if (inStash(id)) stash = stash.filter(s => s.id !== id);
  else stash.unshift(mode.stashEntry(f));
  saveStash();
  if (mode.renderStash) mode.renderStash();
  if (cardId === id) document.getElementById('cardHeart').textContent = inStash(id) ? '❤️' : '🤍';
}

/* ---- cursor flashlight ---- */
function initTorch() {
  const torch = document.getElementById('flashlight');
  const mapEl = document.getElementById('map');
  let mx = 0, my = 0, torchQueued = false;
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
}

/* ---- toast ---- */
let toastTimer = null;
function toast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.remove('show'), 3500);
}

/* ---- boot ---- */
function initShell(m) {
  mode = m;
  state.radiusKm = m.defaultRadiusKm;
  seen = loadSeen();
  stash = loadStash();

  map = L.map('map', { zoomControl: false })
    .setView([state.center.lat, state.center.lon], m.defaultZoom);
  L.control.zoom({ position: 'bottomright' }).addTo(map);
  // Key-free OpenStreetMap tiles; CSS inverts them to a dark "treasure map".
  L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '&copy; OpenStreetMap', maxZoom: 19,
  }).addTo(map);

  initTorch();
  if (m.init) m.init();
  drawRing();
  if (m.renderStash) m.renderStash();
  poll();
  setInterval(poll, POLL_MS);
}

// Exposed for the mode modules and for tests/verify_*.py, which drive render() and
// inspect state directly - pixel-clicking stacked markers is unreliable.
window.state = state;
window.render = render;
window.Shell = {
  init: initShell, map: () => map, drawRing, openCard, toast, ageText, distKm,
  toggleStash, inStash, stash: () => stash, get mode() { return mode; },
};
