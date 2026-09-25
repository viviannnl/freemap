"""Decoding tests for the sapi response format.

The raw items in RAW_* are real responses captured from the sapi endpoint, trimmed
only of extra image entries. Decoding tests are worth nothing if the input is
invented, since the whole risk being guarded here is that Craigslist's undocumented
compact-array format isn't what we think it is.

Offline and pure - no network. Filtering and walking distance live in the browser
now, so they're verified in tests/verify_rentals.py instead.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from craigslist import free, rentals, sapi  # noqa: E402

# A real 1-bedroom in Yaletown, $2,500.
RAW_ONE_BED = [
    12992965, 152881, 1, 2500, "1:1~49.2749~-123.116", "0ak07J",
    [13, "pJzDaA2Dhxoi2T7KYqkvQs"],
    [4, "3:00606_gHIYQTtmiEb_0ak07J"],
    [6, "vancouver-beautiful-bedroom-den-condo"],
    [10, "$2,500"],
    "*** BEAUTIFUL 1 BEDROOM + DEN CONDO FOR RENT AT THE MAX *** (Yaletown)",
    [5, 1, 615],
]

# A real 2-bedroom, $4,200. Note tag 5 reports 1103 - floor area, not bathrooms,
# despite the posting advertising 2 bathrooms.
RAW_TWO_BED = [
    2155352, 152786, 1, 4200, "1:1~49.2761~-123.1177", "0CI0t2",
    [13, "8GSjr34FtNmLAmW1q2Hqd1"],
    [6, "vancouver-furnished-bedroom-bathroom"],
    [10, "$4,200"],
    "Furnished 2 Bedroom / 2 Bathroom - YaleTown",
    [5, 2, 1103],
]

# A real free posting: no price at all, one photo.
RAW_FREE_SOFA = [
    7891234567, 98012, 15, -1, "2:3~49.2712~-123.1284", "08I08I",
    [13, "kQ2mXbT9rLpNvA4uEwZs71"],
    [4, "3:00q0q_9p0Nh5eR062_08I08I"],
    [6, "vancouver-free-sectional-couch"],
    "Free sectional couch - must go today (Kitsilano)",
]

LOCS = ["", "downtown", "mount pleasant", "kitsilano"]


# --- shared decoding -----------------------------------------------------

def test_geo_decodes_a_geocode():
    assert sapi.geo(RAW_ONE_BED) == (49.2749, -123.116)


def test_geo_survives_a_malformed_geocode():
    assert sapi.geo([1, 1, 1, 2000, "1:1~notanumber~-123.11"]) == (None, None)


def test_geo_survives_a_missing_geocode():
    assert sapi.geo([1, 1, 1, 2000]) == (None, None)


def test_title_reads_the_title_not_the_image_suffix():
    """The image suffix ("0CI0t2") is a bare string too, and sits earlier in the
    array. Scanning from the end is what keeps it from being read as the title."""
    assert sapi.title(RAW_TWO_BED) == "Furnished 2 Bedroom / 2 Bathroom - YaleTown"


def test_neighborhood_indexes_the_feeds_location_table():
    assert sapi.neighborhood(RAW_FREE_SOFA, LOCS) == "Kitsilano"


def test_neighborhood_is_none_without_a_location_table():
    assert sapi.neighborhood(RAW_ONE_BED, None) is None


def test_thumb_keeps_the_suffix():
    """The name WITHOUT the trailing suffix 404s, so dropping it would give every
    card a broken image - measured against the live CDN, not assumed."""
    assert sapi.thumb(RAW_FREE_SOFA) == (
        "https://images.craigslist.org/00q0q_9p0Nh5eR062_08I08I_600x450.jpg"
    )


def test_thumb_is_none_without_images():
    assert sapi.thumb(RAW_TWO_BED) is None


def test_url_for_is_none_without_a_url_id():
    assert sapi.url_for([123, 1, 1, 2000, "1:1~49.28~-123.11", "abc"]) is None


def test_haversine_matches_a_known_distance():
    """402 Dunsmuir to Waterfront Station, about 600 m on the map."""
    d = sapi.haversine_m(49.2806, -123.1116, 49.2859, -123.1116)
    assert 570 < d < 620


# --- rentals -------------------------------------------------------------

def test_rentals_parse_decodes_a_real_posting():
    item = rentals.parse_item(RAW_ONE_BED, LOCS)
    assert item["id"] == "12992965"
    assert item["price"] == 2500
    assert item["price_display"] == "$2,500"
    assert item["bedrooms"] == 1
    assert item["sqft"] == 615
    assert item["lat"] == 49.2749 and item["lon"] == -123.116
    assert item["title"].startswith("*** BEAUTIFUL 1 BEDROOM")
    assert item["url"].endswith(
        "/vancouver-beautiful-bedroom-den-condo/pJzDaA2Dhxoi2T7KYqkvQs"
    )


def test_rentals_parse_returns_none_without_a_url_id():
    """No url id means no link to send, which makes the row useless to us."""
    assert rentals.parse_item([123, 1, 1, 2000, "1:1~49.28~-123.11", "abc"]) is None


def test_rentals_parse_survives_missing_fields():
    """The tag numbers are undocumented and can change; degrading beats raising."""
    item = rentals.parse_item([123, 1, 1, None, None, [13, "xyz"], "A place"])
    assert item["price"] is None
    assert item["price_display"] == "?"
    assert item["bedrooms"] is None
    assert item["sqft"] is None
    assert item["lat"] is None and item["lon"] is None


def test_rentals_parse_keeps_a_missing_price_as_none():
    """Plenty of real postings omit the price. "Ask me" must not display as $0, and
    must not be filtered as if it were free."""
    item = rentals.parse_item([123, 1, 1, -1, "1:1~49.28~-123.11", [13, "xyz"], "A place"])
    assert item["price"] is None and item["price_display"] == "?"


# --- free stuff ----------------------------------------------------------

def test_free_parse_decodes_a_real_posting():
    item = free.parse_item(RAW_FREE_SOFA, LOCS)
    assert item["id"] == "7891234567"
    assert item["title"].startswith("Free sectional couch")
    assert item["neighborhood"] == "Kitsilano"
    assert item["thumb"].endswith("_600x450.jpg")
    assert item["lat"] == 49.2712 and item["lon"] == -123.1284


def test_free_parse_attaches_a_category_and_glyph():
    item = free.parse_item(RAW_FREE_SOFA, LOCS)
    assert item["category"] == "furniture" and item["glyph"] == "🛋️"


def test_classify_prefers_the_more_specific_bucket():
    """Rule order is load-bearing: "moving boxes" must not fall through to the
    materials rule on "box", nor a couch to the generic gift."""
    assert free.classify("free moving boxes")[0] == "boxes"
    assert free.classify("free lumber and plywood")[0] == "materials"
    assert free.classify("Something indescribable") == ("misc", "🎁")


def test_classify_is_case_insensitive():
    assert free.classify("FREE SOFA")[0] == "furniture"


def test_classify_matches_plurals():
    for title, category in [("free chairs", "furniture"), ("free dishes", "kitchen"),
                            ("free bikes", "bike"), ("free plants", "plants")]:
        assert free.classify(title)[0] == category, title


def test_classify_does_not_match_keywords_buried_inside_other_words():
    """Substring matching quietly mis-glyphed real postings: "crib" inside
    "indescribable", "pan" inside "pants", "pot" inside "spotless"."""
    assert free.classify("Something indescribable") == ("misc", "🎁")  # not kids/crib
    assert free.classify("free pantry, empty")[0] != "kitchen"          # not pan
    assert free.classify("spotless free desk")[0] == "furniture"        # desk, not pot
    assert free.classify("free landfill permit")[0] != "materials"      # not fill


# --- dropping what can't go on a map ------------------------------------

def test_pinnable_drops_ungeocoded_rows():
    rows = [
        {"id": "a", "lat": 49.28, "lon": -123.11},
        {"id": "b", "lat": None, "lon": None},
        None,
    ]
    assert [r["id"] for r in sapi.pinnable(rows, "apa", 3)] == ["a"]


# --- the walking model --------------------------------------------------

def test_walk_minutes_and_metres_for_walk_round_trip():
    for minutes in (5, 10, 20, 45):
        assert rentals.walk_minutes(rentals.metres_for_walk(minutes)) == minutes


def test_walk_minutes_never_returns_zero():
    """Next door is a one minute walk, not a zero minute one."""
    assert rentals.walk_minutes(0) == 1
