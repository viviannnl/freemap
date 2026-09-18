/* FreeMap frontend: a live, animated treasure map of Vancouver free stuff.
 *
 * The backend hands us the full set of drawable finds every poll. We diff that
 * set against what's on the map to decide what animates:
 *   - an id we haven't drawn  -> loot-drop (bounce in) + toast
 *   - a find whose status is "gone" -> shatter, then remove
 *   - everything else         -> keep, just refresh its freshness class
 * Category chips and the radius slider filter which finds are eligible to draw.
 */

const POLL_MS = 20000;           // how often the browser re-polls /api/finds
const state = {
  markers: new Map(),            // id -> {marker, find}
  finds: new Map(),              // id -> find (latest from server)
  cat: 'all',
  radiusKm: 10,
  center: { lat: 49.2606, lon: -123.1140 },
  first: true,
  stash: loadStash(),
  ring: null,
};

/* ---- map ---- */
const map = L.map('map', { zoomControl: false, attributionControl: true })
  .setView([state.center.lat, state.center.lon], 12);
L.control.zoom({ position: 'bottomright' }).addTo(map);
// Key-free OpenStreetMap tiles; CSS inverts them to a dark "treasure map" (see
// .leaflet-tile-pane in style.css). Avoids the API key CARTO's dark basemap now needs.
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap', maxZoom: 19,
}).addTo(map);

/* ---- helpers ---- */
function haversineKm(a, b, c, d) {
  const R = 6371, r = Math.PI / 180;
  const dp = (c - a) * r, dl = (d - b) * r;
  const x = Math.sin(dp / 2) ** 2 +
    Math.cos(a * r) * Math.cos(c * r) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(x));
}
function distKm(f) {
  return haversineKm(state.center.lat, state.center.lon, f.lat, f.lon);
}
// Craigslist geocodes many free posts to the same neighbourhood centroid, so
// pins stack. Fan them out by a small, deterministic per-id offset (~<90 m) for
// display only - the card still reports the true distance from f.lat/lon.
function jittered(f) {
  let h = 0;
  for (const ch of f.id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  const ang = (h % 360) * Math.PI / 180;
  const rad = 0.0002 + ((h >> 9) % 100) / 100 * 0.0006;  // ~20-90 m
  return [f.lat + rad * Math.cos(ang), f.lon + rad * Math.sin(ang)];
}
function ageText(f) {
  if (f.status === 'gone') return '💨 likely gone';
  const m = f.age_min;
  if (m < 5) return '🔥 just spotted';
  if (m < 60) return `🔥 spotted ${m} min ago`;
  const h = Math.round(m / 60);
  return `spotted ${h}h ago`;
}
function eligible(f) {
  if (state.cat !== 'all' && f.category !== state.cat) return false;
  return distKm(f) <= state.radiusKm;
}

/* ---- pin element ---- */
function pinIcon(f) {
  const shortTitle = f.title.length > 22 ? f.title.slice(0, 21) + '…' : f.title;
  const tag = f.status === 'gone' ? 'gone'
    : (f.age_min < 60 ? `${f.age_min}m` : `${Math.round(f.age_min / 60)}h`);
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
  const next = new Map();
  // Gone finds are deliberately excluded from the draw set: that drops them into
  // the removal loop below, where they shatter instead of rendering as a pin.
  finds.forEach(f => {
    state.finds.set(f.id, f);
    if (eligible(f) && f.status !== 'gone') next.set(f.id, f);
  });

  // add or update
  next.forEach((f, id) => {
    const existing = state.markers.get(id);
    if (!existing) {
      const marker = L.marker(jittered(f), { icon: pinIcon(f) }).addTo(map);
      marker.on('click', () => openCard(id));
      state.markers.set(id, { marker, find: f });
      const el = marker._icon && marker._icon.querySelector('.pin');
      if (el && !state.first) { el.classList.add('dropping'); }
    } else if (existing.find.status !== f.status) {
      existing.marker.setIcon(pinIcon(f));   // freshness changed -> recolour
      existing.find = f;
      existing.marker.off('click').on('click', () => openCard(id));
    } else {
      existing.find = f;
    }
  });

  // remove finds no longer eligible/present; shatter the ones that went "gone"
  state.markers.forEach((m, id) => {
    const f = next.get(id);
    if (f) return;
    const serverFind = state.finds.get(id);
    const goneVisible = serverFind && serverFind.status === 'gone' && eligible(serverFind);
    const el = m.marker._icon && m.marker._icon.querySelector('.pin');
    if (goneVisible && el) {
      el.classList.add('shattering');
      setTimeout(() => { map.removeLayer(m.marker); state.markers.delete(id); }, 600);
    } else {
      map.removeLayer(m.marker);
      state.markers.delete(id);
    }
  });

  document.getElementById('countN').textContent = next.size;
  state.first = false;
}

let firstCountForToast = 0;
async function poll() {
  try {
    const r = await fetch('/api/finds');
    const data = await r.json();
    if (data.center) state.center = data.center;
    const prevIds = new Set(state.markers.keys());
    render(data.finds);
    // toast for genuinely new drops (not the initial paint)
    const newOnes = [...state.markers.keys()].filter(id => !prevIds.has(id));
    if (!state.firstDone) { state.firstDone = true; }
    else if (newOnes.length) {
      const f = state.finds.get(newOnes[0]);
      toast(`${f.glyph} New drop: ${f.title.slice(0, 30)}`);
    }
  } catch (e) { console.warn('poll failed', e); }
}

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
  document.querySelectorAll('.chip').forEach(c => c.classList.toggle('on', c === chip));
  state.cat = chip.dataset.cat;
  reflow();
});
const radiusInput = document.getElementById('radius');
radiusInput.addEventListener('input', () => {
  state.radiusKm = +radiusInput.value;
  document.getElementById('radiusLabel').textContent = `${state.radiusKm} km`;
  drawRing(); reflow();
});
function reflow() {
  // Re-evaluate eligibility against current filters without a network round-trip.
  render([...state.finds.values()]);
}

/* ---- listing card ---- */
const card = document.getElementById('card');
let cardId = null;
function openCard(id) {
  const f = state.finds.get(id); if (!f) return;
  cardId = id;
  document.getElementById('cardTitle').textContent = f.title;
  document.getElementById('cardAge').textContent = ageText(f);
  document.getElementById('cardLoc').innerHTML = `📍 <b>${distKm(f).toFixed(1)} km</b> from map centre`;
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
function loadStash() {
  try { return JSON.parse(localStorage.getItem('freemap.stash') || '[]'); }
  catch { return []; }
}
function saveStash() { localStorage.setItem('freemap.stash', JSON.stringify(state.stash)); }
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
    const meta = live ? (live.status === 'gone' ? '<span style="color:#e06a6a">💨 likely gone</span>'
      : ageText(live)) : 'saved';
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
  const item = e.target.closest('.sitem');
  if (item) {
    const f = state.finds.get(item.dataset.id);
    if (f) { map.setView([f.lat, f.lon], 15); openCard(item.dataset.id); }
    else window.open(state.stash.find(s => s.id === item.dataset.id).url, '_blank');
  }
});
const stashPanel = document.getElementById('stash');
document.getElementById('stashBtn').onclick = () => stashPanel.classList.toggle('open');

/* ---- cursor flashlight ---- */
const torch = document.getElementById('flashlight');
let mx = 0, my = 0, torchQueued = false;
document.getElementById('map').addEventListener('mouseenter', () => document.body.classList.add('torch'));
document.getElementById('map').addEventListener('mouseleave', () => {
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
    const near = Math.hypot(cx - mx, cy - my) < R;
    el.classList.toggle('awake', near);
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
drawRing();
renderStash();
poll();
setInterval(poll, POLL_MS);
