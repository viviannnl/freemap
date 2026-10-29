"""Vercel serverless function: GET /api/finds.

Stateless crawl proxy - one Craigslist request per invocation, parsed into the
same JSON shape the local Flask app returns. Freshness and animations are the
browser's job (see static/app.js), so nothing here needs a database or a
background thread. An edge cache header keeps repeat traffic off Craigslist.

Imports the shared crawl/classify modules from the project root; vercel.json's
includeFiles ensures they are bundled with this function.
"""

import json
import os
import sys

from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from finds import build_payload as crawl_payload, search_response  # noqa: E402


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
        payload, code = search_response(query)
        body = json.dumps(payload)
        cache = "s-maxage=60, stale-while-revalidate=120" if code == 200 else "no-store"
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body.encode())
