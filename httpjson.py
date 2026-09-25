"""Boilerplate for a Vercel Python function that answers JSON.

Each function in api/ is one line of routing plus a build() that returns a dict, so
the response shaping, error handling and cache header live in one place instead of
being re-typed per endpoint.
"""

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse


def json_handler(build, cache="s-maxage=60, stale-while-revalidate=120", on_error=None):
    """A request handler that answers `build(query)` as JSON.

    `query` is a {name: first-value} dict. A failure answers 502 with a body the
    page can still read: never a blank 500, because the map is built to render an
    empty result and shouldn't have to guess whether it got one.
    """

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = {k: v[0] for k, v in parse_qs(urlparse(self.path).query).items()}
            try:
                body = json.dumps(build(query))
                code, cache_header = 200, cache
            except Exception as exc:
                payload = {"error": str(exc)}
                payload.update(on_error or {})
                body = json.dumps(payload)
                code, cache_header = 502, "no-store"
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Cache-Control", cache_header)
            self.end_headers()
            self.wfile.write(body.encode())

        def log_message(self, *args):
            pass  # Vercel captures stdout; the default access log is just noise

    return Handler
