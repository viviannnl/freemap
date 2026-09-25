"""GET /api/building?u=<posting url> - how old the building is.

Lazy, one posting at a time, called when you click "look up age" on a rental card.
Costs a posting fetch plus maybe a City of Vancouver open-data query, which is why
it isn't done for every listing in the crawl. A building's age never changes, so
this caches hard; the browser memoises on top of that for the session.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from craigslist.building import year_built  # noqa: E402
from craigslist.posted import is_craigslist  # noqa: E402
from httpjson import json_handler  # noqa: E402


def build(query):
    url = query.get("u", "")
    # The browser hands us this URL, so the host check is what stops the endpoint
    # being used as an open proxy.
    if not is_craigslist(url):
        return {"year_built": None, "year_source": None, "address": None}
    year, source, address = year_built(url)
    return {"year_built": year, "year_source": source, "address": address}


handler = json_handler(
    build,
    cache="s-maxage=86400, stale-while-revalidate=86400",
    on_error={"year_built": None, "year_source": None, "address": None},
)
