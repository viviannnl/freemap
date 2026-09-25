/* FreeMap: Craigslist's free section as a live treasure map.
 *
 * Everything shared with the rentals map (the map, the pin diff engine, the torch,
 * the card, the ring) lives in app.js. This is only what's particular to free
 * stuff: glyph pins, category chips, a plain km radius, and the stash dock.
 */

const free = {
  key: 'freemap',          // keeps stashes saved on the live site working
  endpoint: '/api/finds',
  itemsKey: 'finds',
  accent: '#FFD166',
  defaultRadiusKm: 10,
  defaultZoom: 12,
  cat: 'all',

  // Free stuff is measured from the middle of the city: there's no "your place" to
  // walk from, you're driving across town for a free sofa.
  origin() { return state.center; },

  eligible(f) {
    if (free.cat !== 'all' && f.category !== free.cat) return false;
    return Shell.distKm(f) <= state.radiusKm;
  },

  pinIcon(f) {
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
  },

  // Only the freshness colour can change under a free pin, so that's the only
  // reason to rebuild its icon.
  pinChanged(before, after) { return before.status !== after.status; },

  cardGlyph(f) { return f.glyph; },
  newToast(f) { return `${f.glyph} New drop: ${f.title.slice(0, 30)}`; },
  stashEntry(f) { return { id: f.id, title: f.title, glyph: f.glyph, thumb: f.thumb, url: f.url }; },

  card(f) {
    document.getElementById('cardFacts').innerHTML = '';
  },

  afterRender(visible) {
    document.getElementById('countN').textContent = visible.length;
  },

  afterPoll() { free.renderStash(); },

  renderStash() {
    const items = Shell.stash();
    const list = document.getElementById('stashList');
    document.getElementById('stashN').textContent = items.length;
    document.getElementById('stashCount').textContent = `${items.length} saved`;
    if (!items.length) {
      list.innerHTML = `<div class="empty">Nothing stashed yet.<br>Tap 🤍 on a find to keep it here.</div>`;
      return;
    }
    list.innerHTML = items.map(s => {
      const live = state.finds.get(s.id);
      const goneNow = live && !state.crawlIds.has(s.id);
      const meta = goneNow ? '<span style="color:#e06a6a">💨 likely gone</span>'
        : (live ? Shell.ageText(live) : 'saved');
      const bg = s.thumb ? `style="background-image:url('${s.thumb}')"` : '';
      return `<div class="sitem" data-id="${s.id}">
        <div class="sthumb" ${bg}>${s.thumb ? '' : s.glyph}</div>
        <div><div class="si-t">${s.title}</div><div class="si-m">${meta}</div></div>
        <div class="si-x" data-x="${s.id}">×</div></div>`;
    }).join('');
  },

  init() {
    document.getElementById('chips').addEventListener('click', e => {
      const chip = e.target.closest('.chip'); if (!chip) return;
      document.querySelectorAll('.chip').forEach(c => c.classList.toggle('on', c === chip));
      free.cat = chip.dataset.cat;
      render(state.lastLive);
    });

    const radiusInput = document.getElementById('radius');
    radiusInput.addEventListener('input', () => {
      state.radiusKm = +radiusInput.value;
      document.getElementById('radiusLabel').textContent = `${state.radiusKm} km`;
      Shell.drawRing(); render(state.lastLive);
    });

    document.getElementById('stashList').addEventListener('click', e => {
      const x = e.target.closest('.si-x');
      if (x) { Shell.toggleStash(x.dataset.x); return; }
      const item = e.target.closest('.sitem'); if (!item) return;
      const f = state.finds.get(item.dataset.id);
      if (f) { Shell.map().setView([f.lat, f.lon], 15); Shell.openCard(item.dataset.id); }
      else {
        const s = Shell.stash().find(s => s.id === item.dataset.id);
        if (s) window.open(s.url, '_blank');
      }
    });

    document.getElementById('stashBtn').onclick =
      () => document.getElementById('stash').classList.toggle('open');
  },
};

Shell.init(free);
