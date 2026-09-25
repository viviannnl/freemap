"""Craigslist's free section ("zip") for Vancouver.

Every price is 0 or absent, so nothing here parses or filters on price. What the
map wants instead is a photo and a glyph, which is what classify() supplies.

Free stuff is worth travelling for, so the coverage radius is wide - but note the
360 cap in sapi.py: a wider radius reaches less far back in time.
"""

import re

from . import sapi

CATEGORY = "zip"
RADIUS_KM = 25

# (category, glyph, keywords) - checked in order, first match wins, so more
# specific buckets come before broad ones. Keyword-based and deliberately simple:
# the point is a legible glyph on the map, not perfect taxonomy.
RULES = [
    ("boxes",       "📦", ["moving box", "boxes", "packing", "cardboard"]),
    ("materials",   "🪵", ["lumber", "wood", "plywood", "bricks", "gravel", "soil",
                            "concrete", "tiles", "pallet", "fill", "dirt"]),
    ("electronics", "🖥️", ["monitor", "tv", "television", "computer", "laptop",
                            "printer", "speaker", "stereo", "cable", "router",
                            "keyboard", "phone", "console"]),
    ("appliance",   "🧺", ["fridge", "freezer", "washer", "dryer", "microwave",
                            "dishwasher", "oven", "stove", "vacuum"]),
    ("furniture",   "🛋️", ["sofa", "couch", "futon", "sectional", "loveseat"]),
    ("furniture",   "🪑", ["chair", "stool", "bench", "seat"]),
    ("furniture",   "🛏️", ["bed", "mattress", "frame", "headboard"]),
    ("furniture",   "🪟", ["desk", "dresser", "table", "shelf", "shelving",
                            "cabinet", "drawer", "wardrobe", "bookcase"]),
    ("bike",        "🚲", ["bike", "bicycle", "scooter"]),
    ("plants",      "🪴", ["plant", "garden", "pot", "flower", "seedling"]),
    ("kids",        "🧸", ["kid", "child", "baby", "toy", "stroller", "crib"]),
    ("books",       "📚", ["book", "magazine", "textbook"]),
    ("kitchen",     "🍽️", ["dish", "plate", "kitchen", "pan", "pot", "cutlery",
                            "glassware", "mug"]),
    ("clothing",    "👕", ["clothes", "clothing", "shoes", "jacket", "shirt",
                            "pants", "jeans", "coat", "boots"]),
]

DEFAULT = ("misc", "🎁")

# Keywords match whole words, with an optional plural, rather than as substrings.
# Plain `kw in title` looked fine and quietly mis-glyphed real postings: "crib" hit
# "indes-crib-able", "pan" hit "pants" and "pantry", "pot" hit "spotless", "fill"
# hit "refill". Short keywords are the whole point of the list, so they have to be
# bounded. "dish" still needs to catch "dishes", hence the optional "e".
_MATCHERS = [
    (category, glyph, [re.compile(rf"\b{re.escape(kw)}(?:e?s)?\b") for kw in keywords])
    for category, glyph, keywords in RULES
]


def classify(title):
    """(category, glyph) for a listing title."""
    text = (title or "").lower()
    for category, glyph, patterns in _MATCHERS:
        if any(p.search(text) for p in patterns):
            return category, glyph
    return DEFAULT


def parse_item(item, locs=None):
    """One raw API item -> dict, or None if it lacks the fields we need.

    Degrades rather than raises: a missing or moved field becomes None, because the
    tag numbers are undocumented and one changing shouldn't take the map down.
    """
    try:
        cl_id = str(item[0])
    except (IndexError, TypeError):
        return None

    url = sapi.url_for(item)
    if not url:
        return None  # no link to send anyone, so the row is useless to us

    name = sapi.title(item)
    category, glyph = classify(name)
    lat, lon = sapi.geo(item)
    return {
        "id": cl_id,
        "url": url,
        "title": name,
        "thumb": sapi.thumb(item),
        "neighborhood": sapi.neighborhood(item, locs),
        "lat": lat,
        "lon": lon,
        "category": category,
        "glyph": glyph,
    }


def crawl(radius_km=RADIUS_KM):
    """Every current free posting we can pin, newest first, with how many exist.

    Returns (rows, total) - total being what Craigslist says is listed in the area,
    which the 360 cap usually keeps us from seeing all of.
    """
    feed = sapi.fetch(CATEGORY, radius_km=radius_km)
    rows = [parse_item(raw, feed.locs) for raw in feed.items]
    return sapi.pinnable(rows, CATEGORY, len(feed.items)), feed.total
