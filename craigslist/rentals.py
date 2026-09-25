"""Craigslist apartments/housing ("apa") for Vancouver.

Rentals carry two fields free stuff doesn't - price and bedrooms - and are worth a
narrower radius than free stuff, because rentals post constantly and the 360 cap in
sapi.py means a wide crawl only reaches back a couple of hours. 10 km covers the
city proper, which is as far as anyone anchoring downtown will drag their pin.

Nothing here filters. The crawl returns every pinnable rental and the browser
decides what's within your walking radius, price range and bedroom count - which is
what lets one edge-cached response serve every viewer, and what makes dragging the
radius slider instant instead of a round trip.
"""

from . import sapi

CATEGORY = "apa"
RADIUS_KM = 10

# Walking pace, and how much longer a real pavement route is than a straight line.
# 1.25 suits downtown Vancouver's grid; a tangle of cul-de-sacs would be higher.
# Shipped to the browser in the API payload so the two ends can't drift apart.
WALK_SPEED_M_PER_MIN = 5000 / 60
WALK_DETOUR = 1.25


def walk_minutes(distance_m):
    """Straight-line metres -> roughly how long that is to walk."""
    return max(1, round(distance_m * WALK_DETOUR / WALK_SPEED_M_PER_MIN))


def metres_for_walk(minutes):
    """Inverse of walk_minutes: the search radius that matches a walking time."""
    return round(minutes * WALK_SPEED_M_PER_MIN / WALK_DETOUR)


def parse_item(item, locs=None):
    """One raw API item -> dict, or None if it lacks the fields we need.

    A missing price is kept as None rather than coerced to 0: plenty of real
    postings omit it, and "ask me" must not be displayed or filtered as "$0".
    """
    try:
        cl_id = str(item[0])
    except (IndexError, TypeError):
        return None

    url = sapi.url_for(item)
    if not url:
        return None  # no link to send anyone, so the row is useless to us

    price = item[3] if len(item) > 3 and isinstance(item[3], (int, float)) else None
    price = int(price) if price and price > 0 else None
    beds = sapi.tag(item, sapi.TAG_BEDS_AREA)
    lat, lon = sapi.geo(item)
    return {
        "id": cl_id,
        "url": url,
        "title": sapi.title(item),
        "thumb": sapi.thumb(item),
        "neighborhood": sapi.neighborhood(item, locs),
        "lat": lat,
        "lon": lon,
        "price": price,
        "price_display": sapi.tag1(item, sapi.TAG_PRICE_DISPLAY) or (f"${price}" if price else "?"),
        "bedrooms": beds[0] if beds else None,
        # The second value of tag 5 is floor area in square feet, not bathrooms.
        "sqft": beds[1] if beds and len(beds) > 1 and beds[1] else None,
    }


def crawl(radius_km=RADIUS_KM):
    """Every current rental posting we can pin, newest first, unfiltered.

    Returns (rows, total). Vancouver lists thousands of rentals at once and the cap
    hands over 360, so total is what the UI needs to be honest about showing you the
    newest slice rather than the whole market.
    """
    feed = sapi.fetch(CATEGORY, radius_km=radius_km)
    rows = [parse_item(raw, feed.locs) for raw in feed.items]
    return sapi.pinnable(rows, CATEGORY, len(feed.items)), feed.total
