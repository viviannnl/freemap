"""Craigslist free-stuff search, defaulting to Vancouver.

Craigslist has no public API. The web UI is a JS app that talks to an internal
JSON endpoint (sapi.craigslist.org); one request per poll returns every current
posting in the area with coordinates already attached, and the server honours a
radius filter. That is far gentler on Craigslist than scraping detail pages.

Adapted from the rental-watcher project. Two differences that matter for free
stuff:

  * searchPath is "zip" (Craigslist's "free" category) instead of "apa", so
    every price is 0/absent - we don't parse or filter on price.
  * we parse the image ids so cards can show the real photo.

Response items are compact positional arrays. Decoded by inspection:

    [0] internal id (stable per posting -> our dedupe key)
    [1] sequence number (descending when sort=date)
    [2] category id
    [3] price (-1 / absent for free)
    [4] "<precision>:<n>~<lat>~<lon>" geocode, or empty if ungeocoded
    [5] image suffix token
    tagged sublists, [tag, *values]:
      4  -> image ids, e.g. "3:00q0q_9p0Nh5eR062_08I08I"
      6  -> url slug
      13 -> url id

An image id "3:<name>_<suffix>" maps to a real thumbnail by dropping the leading
"N:" resolution class and appending a size: images.craigslist.org/<name>_<suffix>_600x450.jpg
(measured, not assumed - the name WITHOUT the suffix 404s; WITH it returns 200).

The tag numbers are undocumented and can change; parse_item() degrades rather
than raises when a field is missing.
"""

import logging
import math
import re
from functools import lru_cache
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

SAPI = "https://sapi.craigslist.org/web/v8/postings/search/full"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
BATCH_SIZE = 360

# Original Vancouver defaults. Coordinates in a search let Craigslist resolve
# the target region; its returned distanceUnits determine km/mile conversion.
AREA_ID = 16
SUBAREA_ID = 1
CATEGORY = "zip"  # free
CENTER_LAT = 49.2606
CENTER_LON = -123.1140
RADIUS_KM = 25
KM_PER_MILE = 1.609344

TAG_IMAGES = 4
TAG_SLUG = 6
TAG_URL_ID = 13

IMG_BASE = "https://images.craigslist.org"


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _tag(item, tag):
    for field in item:
        if isinstance(field, list) and field and field[0] == tag:
            return field[1:]
    return None


def _tag1(item, tag):
    vals = _tag(item, tag)
    return vals[0] if vals else None


def _geo(item):
    raw = item[4] if len(item) > 4 else None
    if not isinstance(raw, str) or "~" not in raw:
        return None, None
    parts = raw.split("~")
    try:
        return float(parts[1]), float(parts[2])
    except (IndexError, ValueError):
        return None, None


def _neighborhood(item, locs):
    """Human place name for a posting, from the geocode's index into the feed's
    locationDescriptions table (e.g. "1:1~lat~lon" -> locs[1] == 'mount pleasant').
    """
    if not locs:
        return None
    raw = item[4] if len(item) > 4 else None
    if not isinstance(raw, str) or ":" not in raw:
        return None
    try:
        idx = int(raw.split("~")[0].split(":")[1])
        name = locs[idx]
        return name.title() if isinstance(name, str) and name else None
    except (IndexError, ValueError):
        return None


def _thumb(item, size="600x450"):
    """First image as a real thumbnail URL, or None."""
    ids = _tag(item, TAG_IMAGES)
    if not ids or not isinstance(ids[0], str) or ":" not in ids[0]:
        return None
    name = ids[0].split(":", 1)[1]  # drop "N:" resolution class
    return f"{IMG_BASE}/{name}_{size}.jpg"


def _title(item):
    # The title is the only bare string that isn't the geocode or image suffix.
    for field in reversed(item):
        if isinstance(field, str) and "~" not in field:
            return field
    return "(untitled)"


def parse_item(item, locs=None):
    """One raw API item -> dict, or None if it lacks the fields we need."""
    try:
        cl_id = str(item[0])
    except (IndexError, TypeError):
        return None

    slug, url_id = _tag1(item, TAG_SLUG), _tag1(item, TAG_URL_ID)
    if not url_id:
        return None

    lat, lon = _geo(item)
    if lat is None or lon is None:
        return None  # can't pin it, so it can't go on the map

    return {
        "cl_id": cl_id,
        "url": f"https://www.craigslist.org/view/d/{slug or 'listing'}/{url_id}",
        "title": _title(item),
        "thumb": _thumb(item),
        "neighborhood": _neighborhood(item, locs),
        "lat": lat,
        "lon": lon,
    }


class UnsupportedLocation(ValueError):
    """The source could not honor the requested geographic center."""


class UpstreamError(RuntimeError):
    """The source returned an unusable response."""


def _params(lat, lon, distance, area_id=AREA_ID, country="CA"):
    return {
        "areaId": area_id,
        "batch": f"{area_id}-0-{BATCH_SIZE}-1-0",
        "cc": country,
        "lang": "en",
        "searchPath": CATEGORY,
        "sort": "date",
        "lat": lat,
        "lon": lon,
        "search_distance": distance,
    }


def _request_data(params):
    resp = requests.get(
        SAPI, params=params,
        headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30,
    )
    resp.raise_for_status()
    try:
        payload = resp.json()
        data = payload["data"]
        if payload.get("errors") or not isinstance(data.get("items"), list):
            raise UpstreamError("Invalid Craigslist search response")
        return data
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise UpstreamError("Invalid Craigslist search response") from exc


def _checked_region(data, lat, lon):
    try:
        location = data["location"]
        actual_lat, actual_lon = float(location["lat"]), float(location["lon"])
        if (not math.isfinite(actual_lat) or not math.isfinite(actual_lon)
                or haversine_m(lat, lon, actual_lat, actual_lon) > 1000):
            raise UnsupportedLocation("Craigslist does not cover this search center.")
        area_id = int(location["areaId"])
        # Sparse searches may omit the target area from `areas`, even when the
        # feed appends nearby items. The active distance filter still names units.
        unit = next((entry.get("name") for entry in data.get("humanReadableParams", [])
                     if entry.get("key") == "search_distance"), None)
        if unit is None:
            unit = data.get("areas", {}).get(str(area_id), {}).get("distanceUnits")
        if unit not in ("km", "mi"):
            raise UpstreamError("Unknown Craigslist distance unit")
        return {"area_id": area_id, "country": location["country"],
                "name": location["city"], "distance_unit": unit}
    except UnsupportedLocation:
        raise
    except (KeyError, ValueError, TypeError, OverflowError) as exc:
        raise UpstreamError("Missing Craigslist region metadata") from exc


@lru_cache(maxsize=128)
def resolve_region(lat, lon):
    """Bounded metadata-only cache. The source resolves regions from coordinates.

    A valid seed area/batch is required, even for a geographic search. Discover
    target units first; cc alone does not control the response's distance units.
    """
    if lat == CENTER_LAT and lon == CENTER_LON:
        return {"area_id": AREA_ID, "country": "CA", "name": "Vancouver", "distance_unit": "km"}
    return _checked_region(_request_data(_params(lat, lon, 1)), lat, lon)


def search(lat=None, lon=None, radius_km=None):
    """Return parsed rows and region metadata for the selected geographic search."""
    lat = CENTER_LAT if lat is None else lat
    lon = CENTER_LON if lon is None else lon
    radius_km = RADIUS_KM if radius_km is None else radius_km
    region = resolve_region(lat, lon)
    distance = radius_km / KM_PER_MILE if region["distance_unit"] == "mi" else radius_km
    params = _params(lat, lon, distance, region["area_id"], region["country"])
    if lat == CENTER_LAT and lon == CENTER_LON:
        params["subAreaId"] = SUBAREA_ID
    data = _request_data(params)
    actual_region = _checked_region(data, lat, lon)
    if actual_region["distance_unit"] != region["distance_unit"]:
        resolve_region.cache_clear()
        raise UpstreamError("Craigslist region changed; please retry")
    items = data.get("items", [])
    locs = (data.get("decode") or {}).get("locationDescriptions")
    parsed = [p for p in (parse_item(raw, locs) for raw in items) if p]
    log.info(
        "crawl: %d free postings for %s %s search at %.4f,%.4f (%d unparseable)",
        len(parsed), distance, region["distance_unit"], lat, lon, len(items) - len(parsed),
    )
    return parsed, actual_region


def crawl(lat=None, lon=None, radius_km=None):
    """Preserve the original list-returning interface for scripts."""
    return search(lat, lon, radius_km)[0]


_DATETIME_RE = re.compile(r'datetime="([^"]+)"')


def fetch_posted(url):
    """The true 'posted' timestamp (ISO string) for one posting, or None.

    The search API carries no post time, so this fetches the detail page and reads
    its first <time datetime=...> element (the "posted:" line). Called lazily, one
    posting at a time, when a card is opened - never in bulk.

    Only Craigslist URLs are fetched: this endpoint takes a URL from the client, so
    the host check is what stops it being used as an open proxy (SSRF).
    """
    try:
        host = urlparse(url).hostname or ""
    except ValueError:
        return None
    if not (host == "craigslist.org" or host.endswith(".craigslist.org")):
        return None
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=15, allow_redirects=True)
        if r.status_code != 200:
            return None
        m = _DATETIME_RE.search(r.text)
        return m.group(1) if m else None
    except requests.RequestException:
        return None


if __name__ == "__main__":  # quick manual probe
    logging.basicConfig(level=logging.INFO)
    rows = crawl()
    print(f"{len(rows)} pinnable free listings")
    withimg = sum(1 for r in rows if r["thumb"])
    print(f"{withimg} have photos")
    for r in rows[:5]:
        print(f"  {r['title'][:40]:42} {r['lat']:.4f},{r['lon']:.4f}  img={bool(r['thumb'])}")
