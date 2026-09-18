"""SQLite store that turns a stream of crawls into a live, animatable feed.

Freshness on free stuff is the whole game, and Craigslist's search API does not
hand us a post time in the compact item. So we time from when *we* first saw a
posting: first_seen is set once and never moved, last_seen advances every poll a
posting is still present. That gives us three things the UI needs:

  * freshness buckets (fresh / warm / cool) from age since first_seen, which
    drives pin colour and the "posted ~N min ago" copy;
  * new arrivals - ids we had never stored - which drive the loot-drop animation;
  * disappearances - ids stored and still recent but absent from this crawl -
    which drive the "gone" shatter. We keep showing a gone pin briefly (until
    GONE_TTL) so the shatter is visible, then drop it.

first_seen is not the true post time - a posting can be hours old when a
freshly-started watcher first sees it. An always-on watcher converges: new
arrivals are seen within one poll interval of posting. Honest enough for a
live treasure map; we say "spotted" not "posted" in the API to be truthful.
"""

import sqlite3
import time

# Age thresholds in seconds -> freshness bucket.
FRESH_S = 30 * 60      # < 30 min: just dropped (gold, pulsing)
WARM_S = 3 * 60 * 60   # < 3 h: a few hours old (amber)
# older: cool (grey)

GONE_TTL_S = 10 * 60   # keep a vanished posting visible this long, as "gone"

DB_PATH = "freemap.db"


def connect(path=DB_PATH):
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS finds (
            cl_id      TEXT PRIMARY KEY,
            title      TEXT,
            url        TEXT,
            thumb      TEXT,
            lat        REAL,
            lon        REAL,
            category   TEXT,
            glyph      TEXT,
            first_seen REAL,
            last_seen  REAL,
            gone_at    REAL
        )
    """)
    conn.commit()
    return conn


def freshness(age_s):
    if age_s < FRESH_S:
        return "fresh"
    if age_s < WARM_S:
        return "warm"
    return "cool"


def sync(conn, listings, classify, now=None):
    """Reconcile one crawl against the store. Returns (new_ids, gone_ids).

    new_ids: postings seen for the first time this poll (drive loot-drops).
    gone_ids: postings that were present and are now absent (drive shatter).
    """
    now = now or time.time()
    seen = {row["cl_id"]: row for row in listings}

    existing = {r["cl_id"]: r for r in conn.execute("SELECT * FROM finds")}
    new_ids, gone_ids = [], []

    for cl_id, row in seen.items():
        category, glyph = classify(row["title"])
        if cl_id in existing:
            # Still here: refresh last_seen and clear any stale gone flag.
            conn.execute(
                "UPDATE finds SET last_seen=?, gone_at=NULL, thumb=?, title=? WHERE cl_id=?",
                (now, row["thumb"], row["title"], cl_id),
            )
        else:
            new_ids.append(cl_id)
            conn.execute(
                "INSERT INTO finds (cl_id,title,url,thumb,lat,lon,category,glyph,"
                "first_seen,last_seen,gone_at) VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
                (cl_id, row["title"], row["url"], row["thumb"], row["lat"], row["lon"],
                 category, glyph, now, now),
            )

    # Anything in the store but not in this crawl has just disappeared.
    for cl_id, r in existing.items():
        if cl_id not in seen and r["gone_at"] is None:
            gone_ids.append(cl_id)
            conn.execute("UPDATE finds SET gone_at=? WHERE cl_id=?", (now, cl_id))

    # Drop postings that have been gone longer than the TTL.
    conn.execute("DELETE FROM finds WHERE gone_at IS NOT NULL AND ? - gone_at > ?",
                 (now, GONE_TTL_S))
    conn.commit()
    return new_ids, gone_ids


def all_finds(conn, now=None):
    """Every find worth drawing, as API dicts (present + recently-gone)."""
    now = now or time.time()
    out = []
    for r in conn.execute("SELECT * FROM finds"):
        gone = r["gone_at"] is not None
        age = now - r["first_seen"]
        out.append({
            "id": r["cl_id"],
            "title": r["title"],
            "url": r["url"],
            "thumb": r["thumb"],
            "lat": r["lat"],
            "lon": r["lon"],
            "category": r["category"],
            "glyph": r["glyph"],
            "age_min": round(age / 60),
            "status": "gone" if gone else freshness(age),
        })
    return out
