"""GET /api/posted?u=<posting url> - when a posting actually went up.

Lazy, one posting at a time, called when a card opens. A posting's time never
changes, so this caches hard.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from craigslist.posted import fetch_posted  # noqa: E402
from httpjson import json_handler  # noqa: E402

handler = json_handler(
    lambda query: {"posted": fetch_posted(query.get("u", ""))},
    cache="s-maxage=86400, stale-while-revalidate=86400",
    on_error={"posted": None},
)
