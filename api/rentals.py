"""GET /api/rentals - every current rental posting in Vancouver, unfiltered.

Unfiltered on purpose. Walking radius, price range and bedroom count are applied in
the browser (see static/mode-rentals.js), which means one edge-cached response
serves every viewer and dragging the radius slider costs nothing.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from httpjson import json_handler  # noqa: E402
from payloads import rentals_payload  # noqa: E402

handler = json_handler(lambda query: rentals_payload(), on_error={"listings": []})
