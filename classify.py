"""Map a free-listing title to a category + emoji glyph for the map pin.

Keyword-based and deliberately simple: the point is a legible glyph on the map,
not perfect taxonomy. First matching category wins, so order matters - more
specific buckets come before broad ones. Everything unmatched is a generic gift.
"""

# (category, glyph, keywords) - checked in order.
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
    ("clothing",    "👕", ["clothes", "clothing", "shoes", "jacket", "shirt"]),
]

DEFAULT = ("misc", "🎁")


def classify(title):
    """(category, glyph) for a listing title."""
    t = (title or "").lower()
    for category, glyph, keywords in RULES:
        if any(kw in t for kw in keywords):
            return category, glyph
    return DEFAULT
