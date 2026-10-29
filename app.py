"""FreeMap - local dev server.

A thin, stateless proxy: it crawls Craigslist's free category on demand and
returns the current set of finds. Freshness (fresh/warm/cool), loot-drops and
the "gone" shatter are all derived in the browser by diffing successive polls
and remembering when each posting was first seen (localStorage). That keeps the
server stateless, which is what lets the exact same code run as a Vercel
serverless function (see api/finds.py) with no background thread or database.
"""

import logging
import os

from flask import Flask, jsonify, request, send_from_directory

import craigslist
from finds import build_payload as crawl_payload, search_response

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ROOT = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder="static")  # static served at /static/*


@app.route("/api/finds")
def finds():
    payload, status = search_response(request.args.to_dict(flat=False))
    return jsonify(payload), status


@app.route("/api/posted")
def posted():
    """Lazy: the true posted time for one posting (see craigslist.fetch_posted)."""
    return jsonify({"posted": craigslist.fetch_posted(request.args.get("u", ""))})


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# GEO/SEO discovery files, served at the site root (Vercel serves these as static
# files directly; locally Flask serves them here for parity).
@app.route("/robots.txt")
def robots():
    return send_from_directory(ROOT, "robots.txt", mimetype="text/plain")


@app.route("/llms.txt")
def llms():
    return send_from_directory(ROOT, "llms.txt", mimetype="text/plain")


@app.route("/sitemap.xml")
def sitemap():
    return send_from_directory(ROOT, "sitemap.xml", mimetype="application/xml")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
