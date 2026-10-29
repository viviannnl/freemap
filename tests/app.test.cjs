// Run the real app.js against small DOM/Leaflet adapters, without browser/network.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const S = require('../static/search.js');
const VAN = { lat: 49.2606, lon: -123.114, radiusKm: 10 };
const ATL = { lat: 33.75, lon: -84.39, radiusKm: 10 };
const tick = () => new Promise((resolve) => setImmediate(resolve));

function boot() {
  const elements = new Map(),
    layers = new Set(),
    timers = new Map(),
    requests = [],
    intervals = [];
  let timerId = 0;
  function classes() {
    const values = new Set();
    return {
      add(x) {
        values.add(x);
      },
      remove(x) {
        values.delete(x);
      },
      contains(x) {
        return values.has(x);
      },
      toggle(x, on) {
        if (on === undefined) on = !values.has(x);
        on ? values.add(x) : values.delete(x);
      },
    };
  }
  function element(id) {
    if (!elements.has(id))
      elements.set(id, {
        id,
        value: '10',
        textContent: '',
        innerHTML: '',
        style: {},
        dataset: {},
        attrs: {},
        listeners: {},
        classList: classes(),
        addEventListener(k, fn) {
          this.listeners[k] = fn;
        },
        setAttribute(k, v) {
          this.attrs[k] = v;
        },
      });
    return elements.get(id);
  }
  const map = {
    events: {},
    on(k, fn) {
      this.events[k] = fn;
      return this;
    },
    setView() {
      return this;
    },
    removeLayer(layer) {
      layers.delete(layer);
    },
  };
  function layer(kind, coords, options = {}) {
    const pin = { classList: classes() };
    return {
      kind,
      coords,
      options,
      events: {},
      _icon: {
        querySelector() {
          return pin;
        },
      },
      addTo() {
        layers.add(this);
        return this;
      },
      on(k, fn) {
        this.events[k] = fn;
        return this;
      },
      off(k) {
        delete this.events[k];
        return this;
      },
      setIcon() {},
      setLatLng(p) {
        this.coords = p;
        return this;
      },
    };
  }
  const store = {};
  const localStorage = {
    getItem(k) {
      return store[k] ?? null;
    },
    setItem(k, v) {
      store[k] = v;
    },
  };
  const document = {
    getElementById: element,
    querySelectorAll() {
      return [];
    },
    addEventListener() {},
    body: { classList: classes() },
  };
  const fetcher = (url, options) => {
    if (url.startsWith('/api/posted'))
      return Promise.resolve({
        ok: true,
        json: async () => ({ posted: null }),
      });
    return new Promise((resolve) => requests.push({ url, options, resolve }));
  };
  const context = vm.createContext({
    FreeMapSearch: {
      ...S,
      LatestSearch: class extends S.LatestSearch {
        constructor() {
          super(fetcher);
        }
      },
    },
    localStorage,
    window: { localStorage, addEventListener() {} },
    document,
    console: { warn() {} },
    L: {
      map: () => map,
      control: { zoom: () => ({ addTo() {} }) },
      tileLayer: () => ({ addTo() {} }),
      divIcon: (x) => x,
      marker: (c, o) => layer('marker', c, o),
      circle: (c, o) => layer('ring', c, o),
      circleMarker: (c, o) => layer('center', c, o),
    },
    setTimeout(fn, ms) {
      const id = ++timerId;
      timers.set(id, { fn, ms });
      return id;
    },
    clearTimeout(id) {
      timers.delete(id);
    },
    setInterval(fn) {
      intervals.push(fn);
    },
    requestAnimationFrame() {},
  });
  vm.runInContext(
    fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8'),
    context,
  );
  async function complete(index, selected, rows, status = 200) {
    // The real API echoes validated query numbers, including Leaflet's wrapped
    // longitude precision, rather than snapping them to a fixture's coordinates.
    const query = new URL(requests[index].url, 'http://local').searchParams;
    requests[index].resolve({
      ok: status === 200,
      json: async () =>
        status === 200
          ? {
              center: {
                lat: Number(query.get('lat')),
                lon: Number(query.get('lon')),
              },
              radius_km: Number(query.get('radius_km')),
              region: { name: selected.lat > 40 ? 'Vancouver' : 'Atlanta' },
              finds: rows,
            }
          : { error: 'Temporary source failure', finds: [] },
    });
    await tick();
  }
  function choose(selected) {
    element('chooseCenter').listeners.click();
    map.events.click({ latlng: { lat: selected.lat, lng: selected.lon } });
  }
  function runTimers(ms) {
    for (const [id, timer] of [...timers])
      if (timer.ms === ms) {
        timers.delete(id);
        timer.fn();
      }
  }
  return { element, layers, requests, intervals, complete, choose, runTimers };
}
function item(id, center) {
  return {
    id,
    title: id,
    lat: center.lat,
    lon: center.lon,
    category: 'furniture',
    glyph: '🪑',
    url: 'https://www.craigslist.org/view/d/' + id,
    thumb: null,
  };
}

test('map selection survives an older response and moves both center and radius ring', async () => {
  const app = boot();
  app.choose(ATL);
  await app.complete(1, ATL, [item('atlanta', ATL)]);
  await app.complete(0, VAN, [item('old-one', VAN), item('old-two', VAN)]);
  assert.equal(app.element('countN').textContent, 1);
  assert.equal(
    app.element('locationLabel').textContent,
    'Atlanta · free stuff, live',
  );
  const ring = [...app.layers].find((x) => x.kind === 'ring');
  assert.ok(Math.abs(ring.coords[1] - ATL.lon) < 1e-10);
  assert.equal(ring.options.radius, 10000);
  assert.equal(app.element('chooseCenter').attrs['aria-pressed'], 'false');
});

test('radius input updates the ring immediately and debounces the real backend request', async () => {
  const app = boot();
  await app.complete(0, VAN, [item('near', VAN)]);
  app.element('radius').value = '1';
  app.element('radius').listeners.input();
  assert.equal(app.requests.length, 1);
  assert.equal(
    [...app.layers].find((x) => x.kind === 'ring').options.radius,
    1000,
  );
  app.runTimers(350);
  assert.equal(
    new URL(app.requests[1].url, 'http://local').searchParams.get('radius_km'),
    '1',
  );
  await app.complete(1, { ...VAN, radiusKm: 1 }, [item('near', VAN)]);
  assert.equal(app.element('countN').textContent, 1);
});

test('same-selection source failure preserves successful markers and reports error status', async () => {
  const app = boot();
  await app.complete(0, VAN, [item('retained', VAN)]);
  app.intervals[0]();
  await app.complete(1, VAN, [], 502);
  assert.equal(app.element('countN').textContent, 1);
  assert.equal([...app.layers].filter((x) => x.kind === 'marker').length, 1);
  assert.equal(app.element('liveStatus').dataset.status, 'error');
});

test('changing regions leaves saved finds available without marking them gone', async () => {
  const app = boot();
  await app.complete(0, VAN, [item('saved-vancouver', VAN)]);
  [...app.layers].find((x) => x.kind === 'marker').events.click();
  app.element('cardHeart').onclick();
  app.choose(ATL);
  await app.complete(1, ATL, [item('new-atlanta', ATL)]);
  assert.equal(app.element('stashN').textContent, 1);
  assert.match(app.element('stashList').innerHTML, /saved-vancouver/);
  assert.doesNotMatch(app.element('stashList').innerHTML, /likely gone/);
});
