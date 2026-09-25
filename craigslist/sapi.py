"""Shared access to Craigslist's internal search API.

Craigslist has no public API. The web UI is a JS app that talks to an internal
JSON endpoint (sapi.craigslist.org); one request returns every current posting in
an area with coordinates already attached, and the server honours a radius filter.
That is far gentler on Craigslist than scraping N detail pages.

This module knows how to talk to that endpoint and how to decode its items. It
knows nothing about *which* category you want or what you intend to do with the
result - see free.py and rentals.py, which each supply a search path and their own
parse_item().

On the 360 cap: the endpoint returns at most 360 items per request and there is no
way to page past them. Measured, not assumed - a larger batch size returns nothing,
the batch parameter's second field is not an offset, and s/offset/start return a
different result set rather than the next page. Every radius saturates (a 2 km
circle already reports ~1300 current rental postings), so a crawl always sees the
newest 360 and nothing older. That is the one number to keep in mind when choosing
a radius: the same 360 slots spent on a smaller area reach further back in time.

Response items are compact positional arrays. Decoded by inspection:

    [0] internal id (stable per posting -> our dedupe key)
    [1] sequence number (descending when sort=date)
    [2] category id
    [3] price (integer; -1 or absent when free)
    [4] "<precision>:<n>~<lat>~<lon>" geocode, or empty if ungeocoded
    [5] image suffix token
    [-1] title (last bare string)
    tagged sublists, [tag, *values]:
      4  -> image ids, e.g. "3:00q0q_9p0Nh5eR062_08I08I"
      5  -> [bedrooms, square feet] - the second value is floor area, not
            bathrooms: a live sample ran from 0 to 3000, and a "2 Bedroom /
            2 Bathroom" posting reported 1103
      6  -> url slug
      10 -> display price ("$2,650")
      13 -> url id

An image id "3:<name>_<suffix>" maps to a real thumbnail by dropping the leading
"N:" resolution class and appending a size: images.craigslist.org/<name>_<suffix>_600x450.jpg
(measured, not assumed - the name WITHOUT the suffix 404s; WITH it returns 200).

The tag numbers are undocumented and can change without notice, so every helper
here degrades to None rather than raising when a field moves.
"""

import collections
import logging
import math

import requests

log = logging.getLogger(__name__)

# total is how many postings Craigslist says are currently listed in the area, which
# is usually far more than the 360 it will hand over. The UI shows it, because "360
# of 6,790" is an honest thing to say and "live map of everything" would not be.
Feed = collections.namedtuple("Feed", "items locs total")

SAPI = "https://sapi.craigslist.org/web/v8/postings/search/full"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
BATCH_SIZE = 360

# Vancouver, BC / city of Vancouver.
AREA_ID = 16
SUBAREA_ID = 1

# Downtown Vancouver. Both categories crawl from here, so one centre serves both
# maps; per-view radius and anchor are the browser's business.
CENTER_LAT = 49.2606
CENTER_LON = -123.1140

TAG_IMAGES = 4
TAG_BEDS_AREA = 5
TAG_SLUG = 6
TAG_PRICE_DISPLAY = 10
TAG_URL_ID = 13

IMG_BASE = "https://images.craigslist.org"


def haversine_m(lat1, lon1, lat2, lon2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def tag(item, number):
    """Values of a tagged sublist, or None."""
    for field in item:
        if isinstance(field, list) and field and field[0] == number:
            return field[1:]
    return None


def tag1(item, number):
    vals = tag(item, number)
    return vals[0] if vals else None


def geo(item):
    """(lat, lon), or (None, None) when the posting isn't geocoded."""
    raw = item[4] if len(item) > 4 else None
    if not isinstance(raw, str) or "~" not in raw:
        return None, None
    parts = raw.split("~")
    try:
        return float(parts[1]), float(parts[2])
    except (IndexError, ValueError):
        return None, None


def neighborhood(item, locs):
    """Human place name, from the geocode's index into the feed's
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


def thumb(item, size="600x450"):
    """First image as a real thumbnail URL, or None."""
    ids = tag(item, TAG_IMAGES)
    if not ids or not isinstance(ids[0], str) or ":" not in ids[0]:
        return None
    name = ids[0].split(":", 1)[1]  # drop "N:" resolution class
    return f"{IMG_BASE}/{name}_{size}.jpg"


def title(item):
    """The title is the only bare string that isn't the geocode or image suffix,
    and it sits near the end - so scan backwards."""
    for field in reversed(item):
        if isinstance(field, str) and "~" not in field:
            return field
    return "(untitled)"


def url_for(item):
    """Canonical posting URL, or None when there's no id to link to."""
    url_id = tag1(item, TAG_URL_ID)
    if not url_id:
        return None
    return f"https://www.craigslist.org/view/d/{tag1(item, TAG_SLUG) or 'listing'}/{url_id}"


def fetch(search_path, lat=None, lon=None, radius_km=25):
    """Raw items for one category, newest first, as a Feed.

    Carries no per-viewer filters: radius, price, bedrooms and freshness are all
    decided later, so one request serves every viewer and Craigslist sees the same
    traffic whether one person is looking or fifty.
    """
    params = {
        "areaId": AREA_ID,
        "subAreaId": SUBAREA_ID,
        "batch": f"{AREA_ID}-0-{BATCH_SIZE}-1-0",
        "cc": "CA",
        "lang": "en",
        "searchPath": search_path,
        "sort": "date",
        "lat": CENTER_LAT if lat is None else lat,
        "lon": CENTER_LON if lon is None else lon,
        "search_distance": radius_km,
    }
    resp = requests.get(
        SAPI, params=params,
        headers={"User-Agent": UA, "Accept": "application/json"}, timeout=30,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    items = data.get("items", [])
    locs = (data.get("decode") or {}).get("locationDescriptions")
    total = data.get("totalResultCount", 0) or len(items)
    if total > BATCH_SIZE:
        # Not an error, but the reason the map can't show you everything: the cap
        # means you're seeing the newest 360 of `total` current postings.
        log.info(
            "%s: %d postings currently listed within %s km, capped at %d",
            search_path, total, radius_km, BATCH_SIZE,
        )
    return Feed(items, locs, total)


def pinnable(rows, search_path, raw_count):
    """Drop rows we can't put on a map, and say how many that was.

    A posting with no coordinates can't be pinned and can't be measured against a
    walking radius, so for a map it may as well not exist - but it's worth logging
    rather than silently losing.
    """
    out = [r for r in rows if r and r.get("lat") is not None and r.get("lon") is not None]
    log.info(
        "crawl %s: %d pinnable of %d items (%d unparseable or ungeocoded)",
        search_path, len(out), raw_count, raw_count - len(out),
    )
    return out
