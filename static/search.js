/* Search settings and request lifecycle shared by the map and offline tests. */
(function (root) {
  const DEFAULTS = Object.freeze({ lat: 49.2606, lon: -123.114, radiusKm: 10 });
  const STORAGE_KEY = 'freemap.search';

  function getStorage(host) {
    try {
      return host.localStorage;
    } catch {
      return null;
    }
  }

  function valid(settings) {
    return (
      settings &&
      [settings.lat, settings.lon, settings.radiusKm].every(Number.isFinite) &&
      Math.abs(settings.lat) <= 90 &&
      Math.abs(settings.lon) <= 180 &&
      settings.radiusKm >= 1 &&
      settings.radiusKm <= 25
    );
  }
  function loadSettings(storage) {
    try {
      const saved = JSON.parse(storage.getItem(STORAGE_KEY));
      if (valid(saved))
        return { lat: saved.lat, lon: saved.lon, radiusKm: saved.radiusKm };
    } catch {
      /* Private browsing, invalid JSON, or storage restrictions. */
    }
    return { ...DEFAULTS };
  }
  function saveSettings(storage, settings) {
    try {
      if (valid(settings))
        storage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch {
      /* The selection still works when persistence is unavailable. */
    }
  }
  function requestUrl(settings) {
    return (
      '/api/finds?' +
      new URLSearchParams({
        lat: settings.lat,
        lon: settings.lon,
        radius_km: settings.radiusKm,
      })
    );
  }
  function distanceKm(center, point) {
    const r = Math.PI / 180;
    const dp = (point.lat - center.lat) * r,
      dl = (point.lon - center.lon) * r;
    const a =
      Math.sin(dp / 2) ** 2 +
      Math.cos(center.lat * r) *
        Math.cos(point.lat * r) *
        Math.sin(dl / 2) ** 2;
    return 6371 * 2 * Math.asin(Math.sqrt(Math.min(1, a)));
  }
  function withinRadius(settings, point) {
    return distanceKm(settings, point) <= settings.radiusKm;
  }

  class LatestSearch {
    constructor(fetcher = (url, options) => fetch(url, options)) {
      this.fetcher = fetcher;
      this.revision = 0;
      this.controller = null;
    }
    cancel() {
      this.revision++;
      if (this.controller) this.controller.abort();
    }
    async run(settings) {
      this.cancel();
      const revision = this.revision;
      const selected = { ...settings };
      this.controller = new AbortController();
      try {
        const response = await this.fetcher(requestUrl(selected), {
          signal: this.controller.signal,
        });
        const data = await response.json();
        if (revision !== this.revision) return null;
        if (!response.ok || data.error)
          throw new Error(data.error || 'Could not update from Craigslist.');
        if (
          !data.center ||
          data.center.lat !== selected.lat ||
          data.center.lon !== selected.lon ||
          data.radius_km !== selected.radiusKm ||
          !Array.isArray(data.finds)
        ) {
          throw new Error('Invalid search response. Please try again.');
        }
        return data;
      } catch (error) {
        if (revision !== this.revision || error.name === 'AbortError')
          return null;
        throw error;
      }
    }
  }
  const api = {
    DEFAULTS,
    getStorage,
    loadSettings,
    saveSettings,
    requestUrl,
    distanceKm,
    withinRadius,
    LatestSearch,
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.FreeMapSearch = api;
})(typeof window !== 'undefined' ? window : this);
