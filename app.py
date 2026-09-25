"""Local dev server - the same endpoints Vercel serves, in one process.

A thin, stateless proxy: it crawls Craigslist on demand and returns what's current.
Freshness, filtering, loot-drops and the "gone" shatter are all derived in the
browser by diffing successive polls and remembering when each posting was first
seen (localStorage). That is what lets the exact same code run as serverless
functions (see api/) with no background thread and no database.
"""

import logging
import os

from flask import Flask, jsonify, request, send_from_directory

from craigslist.building import year_built
from craigslist.posted import fetch_posted, is_craigslist
from payloads import free_payload, rentals_payload

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

ROOT = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder="static")  # static served at /static/*


@app.route("/api/finds")
def finds():
    return jsonify(free_payload())


@app.route("/api/rentals")
def rentals():
    return jsonify(rentals_payload())


@app.route("/api/posted")
def posted():
    return jsonify({"posted": fetch_posted(request.args.get("u", ""))})


@app.route("/api/building")
def building():
    url = request.args.get("u", "")
    if not is_craigslist(url):
        return jsonify({"year_built": None, "year_source": None, "address": None})
    year, source, address = year_built(url)
    return jsonify({"year_built": year, "year_source": source, "address": address})


# Two real pages, not one page with a hash. Each has its own title, description and
# structured data, so the rentals half is findable rather than hidden behind JS.
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/rentals")
def rentals_page():
    return send_from_directory(app.static_folder, "rentals.html")


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
