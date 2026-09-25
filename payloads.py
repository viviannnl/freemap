"""The JSON the browser gets, for both categories.

Shared by the local Flask app and the Vercel functions so the two can't drift -
this used to be copy-pasted into api/finds.py and app.py, which is exactly the kind
of duplication that goes stale quietly.

`listed` is how many postings Craigslist says exist in the area; the array holds the
newest 360 of them, which is all the endpoint will hand over. The UI shows both
numbers rather than implying it has everything.
"""

from craigslist import free, rentals, sapi

CENTER = {"lat": sapi.CENTER_LAT, "lon": sapi.CENTER_LON}


def free_payload():
    finds, listed = free.crawl()
    return {"center": CENTER, "finds": finds, "listed": listed}


def rentals_payload():
    listings, listed = rentals.crawl()
    return {
        "center": CENTER,
        # The walking model travels with the data so the browser derives walking
        # times from the same two numbers Python does, instead of its own copy.
        "walk": {
            "speed_m_per_min": rentals.WALK_SPEED_M_PER_MIN,
            "detour": rentals.WALK_DETOUR,
        },
        "listings": listings,
        "listed": listed,
    }
