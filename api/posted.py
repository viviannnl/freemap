"""Vercel serverless function: GET /api/posted?u=<craigslist post url>.

Returns {"posted": "<ISO datetime>"} - the true posted time scraped lazily from
one posting's detail page, since the search API omits it. The client calls this
only when a card is opened. Host-checked in craigslist.fetch_posted to prevent
use as an open proxy. Posted time never changes, so it's aggressively cacheable.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import craigslist  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        url = (qs.get("u") or [""])[0]
        posted = craigslist.fetch_posted(url)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "s-maxage=86400, stale-while-revalidate=604800")
        self.end_headers()
        self.wfile.write(json.dumps({"posted": posted}).encode())
