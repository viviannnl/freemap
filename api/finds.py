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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import craigslist  # noqa: E402
from classify import classify  # noqa: E402


def crawl_payload():
    rows = craigslist.crawl()
    finds = []
    for r in rows:
        category, glyph = classify(r["title"])
        finds.append({
            "id": r["cl_id"], "title": r["title"], "url": r["url"],
            "thumb": r["thumb"], "lat": r["lat"], "lon": r["lon"],
            "neighborhood": r.get("neighborhood"),
            "category": category, "glyph": glyph,
        })
    return {"center": {"lat": craigslist.CENTER_LAT, "lon": craigslist.CENTER_LON},
            "finds": finds}


class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        try:
            body = json.dumps(crawl_payload())
            code, cache = 200, "s-maxage=60, stale-while-revalidate=120"
        except Exception as e:  # never 500 with a blank body - the map handles empty
            body = json.dumps({"error": str(e), "finds": []})
            code, cache = 502, "no-store"
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body.encode())
