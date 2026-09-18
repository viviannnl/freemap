"""FreeMap - a live treasure map of Vancouver's free Craigslist stuff.

A background thread polls Craigslist every POLL_SECONDS, reconciles the crawl
into SQLite (store.py), and the frontend polls /api/finds to draw and animate
pins. The split keeps upstream load flat: one crawl serves every browser.
"""

import logging
import os
import threading
import time

from flask import Flask, jsonify, send_from_directory

import craigslist
import store
from classify import classify

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
log = logging.getLogger("freemap")

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "120"))

app = Flask(__name__, static_folder="static", static_url_path="")
conn = store.connect()
_lock = threading.Lock()


def poll_once():
    """One crawl -> store reconcile. Safe to call from the thread or a test."""
    listings = craigslist.crawl()
    with _lock:
        new_ids, gone_ids = store.sync(conn, listings, classify)
    if new_ids or gone_ids:
        log.info("poll: %d new drops, %d gone", len(new_ids), len(gone_ids))
    return new_ids, gone_ids


def poll_loop():
    while True:
        try:
            poll_once()
        except Exception:
            log.exception("poll failed; will retry next interval")
        time.sleep(POLL_SECONDS)


@app.route("/api/finds")
def finds():
    with _lock:
        data = store.all_finds(conn)
    return jsonify({
        "center": {"lat": craigslist.CENTER_LAT, "lon": craigslist.CENTER_LON},
        "finds": data,
    })


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


def start():
    # Seed synchronously so the first page load already has pins, then poll.
    try:
        poll_once()
    except Exception:
        log.exception("initial crawl failed; starting empty")
    threading.Thread(target=poll_loop, daemon=True).start()


if __name__ == "__main__":
    start()
    app.run(host="127.0.0.1", port=5001, debug=False)
