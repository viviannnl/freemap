/* RentMap: Craigslist rentals on the same map, with the detail in a docked list.
 *
 * Everything shared with the free-stuff map (the map, the pin diff engine, the
 * torch, the card, the ring, the first-seen freshness clock) lives in app.js.
 * This is what rentals add:
 *
 *   - a draggable anchor pin. Walking distance is measured from wherever you drop
 *     it, so the page is useful to anyone; it is remembered in localStorage, which
 *     is the only place your own address ever lives.
 *   - filters applied here rather than on the server: the crawl is unfiltered, so
 *     one edge-cached response serves every viewer and moving a slider is instant.
 *   - a list, because a rental carries more than a pin can hold.
 *
 * The walking model (pace, detour factor) is not duplicated here - it arrives in
 * the API payload so the two ends cannot drift apart.
 */

// Room shares and sublets are a different search from "a place of my own", and they
// dominate the feed. Default to hiding them, with a chip to bring them back.
const SHARE_KEYWORDS = [
  'room for rent', 'roommate', 'room mate', 'shared room', 'room available',
  'private bedroom', 'private room', 'room in', 'bedroom for rent', 'sublet',
];

const rentals = {
  key: 'rentmap',
  endpoint: '/api/rentals',
  itemsKey: 'listings',
  accent: '#5FD3C4',
  defaultRadiusKm: 1,
  defaultZoom: 13,

  // Filters (all client-side)
  walkMin: 15,
  minPrice: 0,
  maxPrice: 0,          // 0 == no cap, same sentinel the old dashboard used
  beds: new Set([0, 1, 2, 3]),   // 3 means "3 or more"
  wholeUnitsOnly: true,
  sort: 'new',
  view: 'live',         // 'live' = what's within reach, 'saved' = your shortlist

  anchor: null,         // {lat, lon} - set in init()
  anchorMarker: null,
  walkModel: { speed_m_per_min: 5000 / 60, detour: 1.25 },
  builtCache: {},       // id -> {year_built, year_source, address}
  selectedId: null,

  // Never null: the ring and every distance are drawn before the first payload
  // lands, so there has to be somewhere to measure from from the very first frame.
  origin() { return rentals.anchor || state.center; },

  /* ---- the walking model, from the server ---- */
  walkMinutes(distanceM) {
    const { speed_m_per_min, detour } = rentals.walkModel;
    return Math.max(1, Math.round(distanceM * detour / speed_m_per_min));
  },
  metresForWalk(minutes) {
    const { speed_m_per_min, detour } = rentals.walkModel;
    return Math.round(minutes * speed_m_per_min / detour);
  },

  /* ---- filtering ----
   * The pure half of rental-watcher's match(), moved to where the sliders are.
   * Order is cheapest-test-first; distance is last because it costs a haversine. */
  eligible(f) {
    const bedKey = f.bedrooms === null || f.bedrooms === undefined
      ? null : Math.min(f.bedrooms, 3);
    if (bedKey !== null && !rentals.beds.has(bedKey)) return false;
    // A missing price is not a reason to reject: plenty of real listings omit it,
    // and "ask me" shouldn't be treated as "too expensive".
    if (f.price !== null) {
      if (rentals.minPrice && f.price < rentals.minPrice) return false;
      if (rentals.maxPrice && f.price > rentals.maxPrice) return false;
    }
    if (rentals.wholeUnitsOnly && rentals.looksShared(f)) return false;
    return Shell.distKm(f) * 1000 <= rentals.metresForWalk(rentals.walkMin);
  },

  looksShared(f) {
    const t = (f.title || '').toLowerCase();
    return SHARE_KEYWORDS.some(kw => t.includes(kw));
  },

  /* ---- pins ---- */
  pinIcon(f) {
    const price = f.price ? '$' + (f.price / 1000).toFixed(f.price >= 10000 ? 0 : 1).replace(/\.0$/, '') + 'k'
      : '?';
    const beds = f.bedrooms === 0 ? 'st' : (f.bedrooms ? f.bedrooms + 'bd' : '');
    return L.divIcon({
      className: '',
      html: `<div class="pin rent ${f.status}" data-id="${f.id}">
               <div class="ring"></div>
               <div class="dot"><span class="glyph">${price}</span>${
                 beds ? `<span class="beds">${beds}</span>` : ''}</div>
               <div class="tag">${rentals.shortTitle(f)} · ${rentals.walkOf(f)} min walk</div>
             </div>`,
      iconSize: [66, 44], iconAnchor: [33, 40],
    });
  },
  pinChanged(before, after) { return before.status !== after.status; },

  shortTitle(f) {
    return f.title.length > 30 ? f.title.slice(0, 29) + '…' : f.title;
  },
  walkOf(f) { return rentals.walkMinutes(Shell.distKm(f) * 1000); },

  cardGlyph(f) { return '🏠'; },
  newToast(f) {
    return `🏠 Just listed: ${f.price_display} · ${f.title.slice(0, 26)}`;
  },
  stashEntry(f) {
    return { id: f.id, title: f.title, glyph: '🏠', thumb: f.thumb, url: f.url,
             price_display: f.price_display };
  },

  /* ---- card ---- */
  card(f) {
    const bits = [];
    bits.push(`<b>${f.price_display}</b>`);
    bits.push(f.bedrooms === 0 ? 'studio'
      : f.bedrooms ? `${f.bedrooms} bed` : 'size not given');
    if (f.sqft) bits.push(`${f.sqft} sq ft`);
    bits.push(`<b>${rentals.walkOf(f)} min</b> walk`);
    document.getElementById('cardFacts').innerHTML = bits.join(' · ');
  },

  /* ---- render ---- */
  afterRender(visible) {
    document.getElementById('countN').textContent = visible.length;
    rentals.renderList(visible);
  },

  /* ---- the list ---- */
  sorters: {
    new: (a, b) => (a.age_min - b.age_min),
    price: (a, b) => (a.price === null) - (b.price === null) || (a.price || 0) - (b.price || 0),
    walk: (a, b) => Shell.distKm(a) - Shell.distKm(b),
  },

  /* Landlords repost the same place every few days and Craigslist mints a new id
   * each time, so dedupe on id can't see it. Identical price, title and location
   * three rows apart is the tell. Rather than guess and hide, the newest row says
   * how many times it appears. Coordinates wobble between postings, so bucket them.
   * Ported from rental-watcher's mark_reposts(); expects newest-first input. */
  markReposts(items) {
    const canonical = new Map();
    items.forEach(item => {
      const title = (item.title || '').toLowerCase().replace(/[^a-z0-9]+/g, '').slice(0, 40);
      const key = [item.price, Math.round(Shell.distKm(item) * 40), title].join('|');
      const first = canonical.get(key);
      if (!first) {
        canonical.set(key, item);
        item.repost = false; item.repeats = 0;
      } else {
        item.repost = true; item.repeats = 0;
        first.repeats += 1;
      }
    });
  },

  renderList(visible) {
    const list = document.getElementById('rentList');
    const rows = [...visible].sort(rentals.sorters[rentals.sort] || rentals.sorters.new);
    rentals.markReposts(rows);
    const saved = Shell.stash();

    document.getElementById('rentCount').textContent = rows.filter(r => !r.repost).length;
    document.getElementById('savedN').textContent = saved.length;
    document.getElementById('dockTitle').textContent =
      rentals.view === 'saved' ? 'Your shortlist' : 'Within reach';
    // Honest about the cap: Craigslist hands over the newest 360 of however many
    // are actually listed, so the map is a recent slice, not the whole market.
    document.getElementById('rentListed').textContent = rentals.view === 'saved'
      ? `${saved.length} saved`
      : (state.listed > state.lastLive.length
          ? `newest ${state.lastLive.length} of ${state.listed.toLocaleString()} listed`
          : `${state.listed.toLocaleString()} listed`);

    if (rentals.view === 'saved') { rentals.renderSaved(list, saved); return; }

    const shown = rows.filter(r => !r.repost);
    if (!shown.length) {
      list.innerHTML = `<div class="empty">Nothing matches right now.<br>
        Widen the walk radius or the price range.</div>`;
      return;
    }

    list.innerHTML = shown.map(f => {
      const built = rentals.builtCache[f.id];
      const walk = rentals.walkOf(f);
      const pct = Math.min(100, Math.round(
        Shell.distKm(f) * 1000 / rentals.metresForWalk(rentals.walkMin) * 100));
      const facts = [
        f.bedrooms === 0 ? '<b>studio</b>' : (f.bedrooms ? `<b>${f.bedrooms} bed</b>` : 'size ?'),
        `<b>${walk} min</b> walk`,
        `${Math.round(Shell.distKm(f) * 1000)} m`,
      ];
      if (f.sqft) facts.push(`${f.sqft} sq ft`);
      const builtBit = built
        ? (built.year_built
            ? `<span class="tagline" title="Source: ${built.year_source}">built ${built.year_built}</span>`
            : `<span class="tagline" title="No record found">age unknown</span>`)
        : `<button class="agebtn" data-age="${f.id}" title="Fetch the posting and look up its age">look up age</button>`;
      return `<article class="rl ${f.id === rentals.selectedId ? 'selected' : ''}" data-id="${f.id}" id="rl-${f.id}">
        ${f.thumb ? `<div class="rthumb" style="background-image:url('${f.thumb}')"></div>` : ''}
        <div class="top">
          <span class="price">${f.price_display}</span>
          ${f.age_min < 30 ? '<span class="newtag">NEW</span>' : ''}
        </div>
        <div class="facts">${facts.join(' · ')}</div>
        <div class="meter"><span style="width:${pct}%"></span></div>
        <span class="rtitle">${rentals.escape(f.title)}</span>
        <div class="hood">${f.neighborhood ? '📍 ' + f.neighborhood : ''}${
          f.repeats >= 2 ? ` · <span class="tagline relist" title="Posted ${f.repeats + 1} times at this price. Often means it hasn't rented.">relisted ${f.repeats + 1}×</span>` : ''}</div>
        <div class="foot">
          <span>${Shell.ageText(f)} · ${builtBit}</span>
          <a class="go" href="${f.url}" target="_blank" rel="noopener">View post →</a>
        </div>
      </article>`;
    }).join('');
  },

  /* The shortlist. A saved place keeps showing even once it drops out of the crawl
   * or out of your current filters - the whole point of saving it is that you
   * already decided you cared, and having it vanish because you nudged a slider
   * would lose work. */
  renderSaved(list, saved) {
    if (!saved.length) {
      list.innerHTML = `<div class="empty">Nothing saved yet.<br>
        Tap 🤍 on a listing to keep it here.</div>`;
      return;
    }
    list.innerHTML = saved.map(s => {
      const live = state.finds.get(s.id);
      const gone = !state.crawlIds.has(s.id);
      const meta = gone ? '<span style="color:#e06a6a">💨 no longer listed</span>'
        : `${Shell.ageText(live)} · <b>${rentals.walkOf(live)} min</b> walk`;
      return `<article class="rl ${gone ? 'gone' : ''}" data-id="${s.id}" id="rl-${s.id}">
        ${s.thumb ? `<div class="rthumb" style="background-image:url('${s.thumb}')"></div>` : ''}
        <div class="top"><span class="price">${s.price_display || '—'}</span>
          <span class="si-x" data-x="${s.id}" title="Remove">×</span></div>
        <div class="facts">${meta}</div>
        <span class="rtitle">${rentals.escape(s.title)}</span>
        <div class="foot"><span></span>
          <a class="go" href="${s.url}" target="_blank" rel="noopener">View post →</a></div>
      </article>`;
    }).join('');
  },

  escape(s) {
    return (s || '').replace(/[&<>"]/g, c => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  },

  /* ---- year built, on demand ---- */
  async lookupAge(id, button) {
    const f = state.finds.get(id); if (!f) return;
    button.disabled = true;
    button.textContent = 'looking…';
    try {
      const r = await fetch('/api/building?u=' + encodeURIComponent(f.url));
      const d = await r.json();
      rentals.builtCache[id] = d;      // memoised: a building's age never changes
      render(state.lastLive);
    } catch {
      button.disabled = false;
      button.textContent = 'retry';
      button.title = 'That lookup failed. Click to try again.';
    }
  },

  /* ---- two-way link between pin and row ---- */
  select(id, { fly = false } = {}) {
    rentals.selectedId = id;
    document.querySelectorAll('.rl.selected').forEach(el => el.classList.remove('selected'));
    const row = document.getElementById('rl-' + id);
    if (row) {
      row.classList.add('selected');
      row.scrollIntoView({ behavior: 'smooth', block: 'center' });
      row.classList.remove('flash');
      void row.offsetWidth;
      row.classList.add('flash');
    }
    const f = state.finds.get(id);
    if (fly && f) Shell.map().setView([f.lat, f.lon], 15);
  },

  onCardOpen(f) { rentals.select(f.id); },

  // Hearting a listing changes the shortlist count and, in shortlist view, the list
  // itself - so a save has to reflow it.
  renderStash() { if (state.lastLive.length) render(state.lastLive); },

  /* ---- the anchor you measure from ---- */
  loadAnchor() {
    try {
      const saved = JSON.parse(localStorage.getItem('rentmap.anchor') || 'null');
      if (saved && typeof saved.lat === 'number') return saved;
    } catch { /* fall through to the default */ }
    return null;
  },
  saveAnchor() { localStorage.setItem('rentmap.anchor', JSON.stringify(rentals.anchor)); },

  drawAnchor() {
    const pos = [rentals.anchor.lat, rentals.anchor.lon];
    if (rentals.anchorMarker) { rentals.anchorMarker.setLatLng(pos); return; }
    rentals.anchorMarker = L.marker(pos, {
      draggable: true,
      zIndexOffset: 1000,
      icon: L.divIcon({
        className: '',
        html: `<div class="pin anchor"><div class="dot"><span class="glyph">📍</span></div>
                 <div class="tag">Drag me — distances are measured from here</div></div>`,
        iconSize: [30, 30], iconAnchor: [15, 15],
      }),
    }).addTo(Shell.map());
    rentals.anchorMarker.on('dragend', () => {
      const p = rentals.anchorMarker.getLatLng();
      rentals.anchor = { lat: p.lat, lon: p.lng };
      rentals.saveAnchor();
      Shell.drawRing();
      render(state.lastLive);
      Shell.toast('📍 Measuring from your new spot');
    });
  },

  onData(data) {
    if (data.walk) rentals.walkModel = data.walk;
  },

  /* ---- controls ---- */
  syncWalkLabel() {
    document.getElementById('walkLabel').textContent = `${rentals.walkMin} min`;
    document.getElementById('walkMetres').textContent =
      `${rentals.metresForWalk(rentals.walkMin)} m`;
    state.radiusKm = rentals.metresForWalk(rentals.walkMin) / 1000;
  },

  init() {
    // Wherever you last dropped it, or the middle of the city for a first visit -
    // never a real address baked into the page.
    rentals.anchor = rentals.loadAnchor() || { ...state.center };
    rentals.drawAnchor();
    rentals.syncWalkLabel();

    const walk = document.getElementById('walk');
    walk.value = rentals.walkMin;
    walk.addEventListener('input', () => {
      rentals.walkMin = +walk.value;
      rentals.syncWalkLabel();
      Shell.drawRing();
      render(state.lastLive);
    });

    const reprice = () => {
      rentals.minPrice = +document.getElementById('minPrice').value || 0;
      rentals.maxPrice = +document.getElementById('maxPrice').value || 0;
      render(state.lastLive);
    };
    document.getElementById('minPrice').addEventListener('change', reprice);
    document.getElementById('maxPrice').addEventListener('change', reprice);

    // Bed chips are multi-select, because "studio or one bedroom" is one search and
    // a single-choice control can't say it.
    document.getElementById('bedChips').addEventListener('click', e => {
      const chip = e.target.closest('.chip'); if (!chip) return;
      const n = +chip.dataset.beds;
      if (rentals.beds.has(n)) rentals.beds.delete(n); else rentals.beds.add(n);
      if (!rentals.beds.size) rentals.beds.add(n);   // never filter everything out
      chip.classList.toggle('on', rentals.beds.has(n));
      render(state.lastLive);
    });

    const shareChip = document.getElementById('wholeChip');
    shareChip.addEventListener('click', () => {
      rentals.wholeUnitsOnly = !rentals.wholeUnitsOnly;
      shareChip.classList.toggle('on', rentals.wholeUnitsOnly);
      render(state.lastLive);
    });

    document.getElementById('sorts').addEventListener('click', e => {
      const b = e.target.closest('[data-sort]'); if (!b) return;
      rentals.sort = b.dataset.sort;
      document.querySelectorAll('#sorts [data-sort]').forEach(
        el => el.classList.toggle('on', el === b));
      render(state.lastLive);
    });

    const dock = document.getElementById('dock');
    const setDock = open => {
      dock.classList.toggle('open', open);
      document.body.classList.toggle('dock-open', open);
    };
    document.getElementById('dockWide').onclick = () => {
      dock.classList.toggle('wide');
      document.getElementById('dockWide').classList.toggle('on', dock.classList.contains('wide'));
      Shell.map().invalidateSize();
    };
    document.getElementById('dockToggle').onclick = () => setDock(true);
    document.getElementById('dockClose').onclick = () => setDock(false);

    const shortlist = document.getElementById('shortlistBtn');
    shortlist.onclick = () => {
      rentals.view = rentals.view === 'saved' ? 'live' : 'saved';
      shortlist.classList.toggle('on', rentals.view === 'saved');
      render(state.lastLive);
    };

    document.getElementById('rentList').addEventListener('click', e => {
      const age = e.target.closest('[data-age]');
      if (age) { e.stopPropagation(); rentals.lookupAge(age.dataset.age, age); return; }
      const x = e.target.closest('[data-x]');
      if (x) { e.stopPropagation(); Shell.toggleStash(x.dataset.x); return; }
      if (e.target.closest('.go')) return;          // let the link do its job
      const row = e.target.closest('.rl'); if (!row) return;
      // A shortlisted place can outlive the crawl, so there may be no pin to fly to.
      if (state.finds.has(row.dataset.id)) {
        rentals.select(row.dataset.id, { fly: true });
        Shell.openCard(row.dataset.id);
      } else {
        const s = Shell.stash().find(s => s.id === row.dataset.id);
        if (s) window.open(s.url, '_blank');
      }
    });

    // The dock is the point of this page, so it starts open.
    setDock(true);
  },
};

Shell.init(rentals);
