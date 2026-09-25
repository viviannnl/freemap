"""GET /api/finds - every current free posting in Vancouver.

Stateless crawl proxy: one Craigslist request per invocation. Freshness, filtering
and animations are the browser's job (see static/mode-free.js), so nothing here
needs a database or a background thread. The edge cache keeps repeat traffic off
Craigslist.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from httpjson import json_handler  # noqa: E402
from payloads import free_payload  # noqa: E402

handler = json_handler(lambda query: free_payload(), on_error={"finds": []})
