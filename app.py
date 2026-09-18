"""FreeMap - local dev server.

A thin, stateless proxy: it crawls Craigslist's free category on demand and
returns the current set of finds. Freshness (fresh/warm/cool), loot-drops and
the "gone" shatter are all derived in the browser by diffing successive polls
and remembering when each posting was first seen (localStorage). That keeps the
server stateless, which is what lets the exact same code run as a Vercel
serverless function (see api/finds.py) with no background thread or database.
"""

import logging

from flask import Flask, jsonify, request, send_from_directory

import craigslist
from classify import classify

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = Flask(__name__, static_folder="static")  # static served at /static/*


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


@app.route("/api/finds")
def finds():
    return jsonify(crawl_payload())


@app.route("/api/posted")
def posted():
    """Lazy: the true posted time for one posting (see craigslist.fetch_posted)."""
    return jsonify({"posted": craigslist.fetch_posted(request.args.get("u", ""))})


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5001, debug=False)
