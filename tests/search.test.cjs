const { test } = require('node:test');
const assert = require('node:assert/strict');
const S = require('../static/search.js');
const atlanta = { lat: 33.75, lon: -84.39, radiusKm: 10 };
const storage = () => ({
  value: null,
  getItem() {
    return this.value;
  },
  setItem(k, v) {
    this.value = v;
  },
});
const response = (settings, extra = {}) => ({
  ok: true,
  json: async () => ({
    center: { lat: settings.lat, lon: settings.lon },
    radius_km: settings.radiusKm,
    finds: [],
    ...extra,
  }),
});

test('fresh browser defaults to Vancouver and a 10 km radius', () => {
  assert.deepEqual(S.loadSettings(storage()), {
    lat: 49.2606,
    lon: -123.114,
    radiusKm: 10,
  });
});
test('chosen center and radius survive storage reload', () => {
  const store = storage();
  S.saveSettings(store, atlanta);
  assert.deepEqual(S.loadSettings(store), atlanta);
});
test('malformed, non-numeric, null, out-of-bounds and oversized saved values reset safely', () => {
  for (const value of [
    'bad',
    'null',
    '{}',
    JSON.stringify({ ...atlanta, lat: 91 }),
    JSON.stringify({ ...atlanta, radiusKm: 0 }),
    JSON.stringify({ ...atlanta, radiusKm: 26 }),
    JSON.stringify({ ...atlanta, lat: '33.7' }),
  ]) {
    const store = storage();
    store.value = value;
    assert.deepEqual(S.loadSettings(store), {
      lat: 49.2606,
      lon: -123.114,
      radiusKm: 10,
    });
  }
});
test('blocked browser storage does not prevent selection or default startup', () => {
  const store = {
    getItem() {
      throw Error('denied');
    },
    setItem() {
      throw Error('quota');
    },
  };
  assert.equal(S.loadSettings(store).lat, 49.2606);
  assert.doesNotThrow(() => S.saveSettings(store, atlanta));
});
test('restricted localStorage getter cannot abort startup', () => {
  const host = {};
  Object.defineProperty(host, 'localStorage', {
    get() {
      throw new Error('SecurityError');
    },
  });
  assert.equal(S.getStorage(host), null);
  assert.deepEqual(S.loadSettings(S.getStorage(host)), {
    lat: 49.2606,
    lon: -123.114,
    radiusKm: 10,
  });
});
test('request URL carries the selected center and kilometer radius', () => {
  const url = new URL(
    S.requestUrl({ ...atlanta, radiusKm: 3 }),
    'http://localhost',
  );
  assert.equal(url.pathname, '/api/finds');
  assert.equal(url.searchParams.get('lat'), '33.75');
  assert.equal(url.searchParams.get('lon'), '-84.39');
  assert.equal(url.searchParams.get('radius_km'), '3');
});
test('radius filtering uses the chosen center and includes the boundary', () => {
  const selection = { lat: 0, lon: 0, radiusKm: 1 };
  assert.ok(S.withinRadius(selection, { lat: 0, lon: 0.008 }));
  assert.equal(S.withinRadius(selection, { lat: 0, lon: 0.01 }), false);
  assert.ok(S.withinRadius({ ...selection, radiusKm: 0 }, { lat: 0, lon: 0 }));
  assert.equal(S.withinRadius(atlanta, { lat: 49.2606, lon: -123.114 }), false);
});
test('latest selection wins even when an old fetch ignores cancellation', async () => {
  const pending = [];
  const client = new S.LatestSearch(
    (url, options) =>
      new Promise((resolve) => pending.push({ resolve, url, options })),
  );
  const old = client.run({ lat: 49.2606, lon: -123.114, radiusKm: 10 });
  const current = client.run(atlanta);
  assert.ok(pending[0].options.signal.aborted);
  pending[1].resolve(response(atlanta));
  assert.equal((await current).center.lat, atlanta.lat);
  pending[0].resolve(response({ lat: 49.2606, lon: -123.114, radiusKm: 10 }));
  assert.equal(await old, null);
});
test('obsolete failures are ignored after the center changes', async () => {
  let rejectOld;
  const client = new S.LatestSearch(
    () =>
      new Promise((resolve, reject) => {
        rejectOld = reject;
      }),
  );
  const old = client.run(atlanta);
  client.cancel();
  rejectOld(Error('old timeout'));
  assert.equal(await old, null);
});
test('HTTP errors cannot become an empty successful map update', async () => {
  const client = new S.LatestSearch(async () => ({
    ok: false,
    json: async () => ({ error: 'Location is not covered', finds: [] }),
  }));
  await assert.rejects(client.run(atlanta), /not covered/);
});
test('default transport does not bind browser fetch to the search client', async () => {
  const original = globalThis.fetch;
  globalThis.fetch = function () {
    'use strict';
    if (this !== undefined && this !== globalThis)
      throw new TypeError('Illegal invocation');
    return Promise.resolve(response(atlanta));
  };
  try {
    assert.equal(
      (await new S.LatestSearch().run(atlanta)).center.lat,
      atlanta.lat,
    );
  } finally {
    globalThis.fetch = original;
  }
});
test('mismatched source center and malformed payloads are rejected', async () => {
  for (const payload of [
    { center: { lat: 49.2606, lon: -123.114 }, radius_km: 10, finds: [] },
    { center: { lat: atlanta.lat, lon: atlanta.lon }, radius_km: 3, finds: [] },
    { finds: [] },
  ]) {
    const client = new S.LatestSearch(async () => ({
      ok: true,
      json: async () => payload,
    }));
    await assert.rejects(client.run(atlanta), /search response/i);
  }
});
