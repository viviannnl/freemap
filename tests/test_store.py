"""Store state-machine tests: the logic behind loot-drops, freshness and shatter.

Pure and offline - no network, no real crawl. We drive sync() with hand-made
listing lists and a fixed clock so every transition is deterministic.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import store  # noqa: E402


def classify(title):
    return ("misc", "🎁")


def listing(cl_id, title="thing", lat=49.26, lon=-123.11):
    return {"cl_id": cl_id, "title": title, "url": f"u/{cl_id}",
            "thumb": None, "lat": lat, "lon": lon}


def fresh_db():
    return store.connect(":memory:")


def test_new_arrivals_reported_once():
    conn = fresh_db()
    new, gone = store.sync(conn, [listing("a"), listing("b")], classify, now=1000)
    assert set(new) == {"a", "b"} and gone == []
    # Same crawl again: nothing new, nothing gone.
    new, gone = store.sync(conn, [listing("a"), listing("b")], classify, now=1060)
    assert new == [] and gone == []


def test_first_seen_is_stable():
    conn = fresh_db()
    store.sync(conn, [listing("a")], classify, now=1000)
    store.sync(conn, [listing("a")], classify, now=9999)
    row = conn.execute("SELECT first_seen,last_seen FROM finds WHERE cl_id='a'").fetchone()
    assert row["first_seen"] == 1000 and row["last_seen"] == 9999


def test_disappearance_flags_gone_then_expires():
    conn = fresh_db()
    store.sync(conn, [listing("a")], classify, now=1000)
    # 'a' drops out of the crawl -> flagged gone, still drawable.
    new, gone = store.sync(conn, [], classify, now=1100)
    assert gone == ["a"]
    drawn = {f["id"]: f for f in store.all_finds(conn, now=1100)}
    assert drawn["a"]["status"] == "gone"
    # Reported gone only once.
    _, gone2 = store.sync(conn, [], classify, now=1200)
    assert gone2 == []
    # After the TTL it is removed entirely.
    store.sync(conn, [], classify, now=1100 + store.GONE_TTL_S + 1)
    assert store.all_finds(conn, now=99999) == []


def test_reappearance_clears_gone():
    conn = fresh_db()
    store.sync(conn, [listing("a")], classify, now=1000)
    store.sync(conn, [], classify, now=1100)          # gone
    store.sync(conn, [listing("a")], classify, now=1200)  # back
    drawn = {f["id"]: f for f in store.all_finds(conn, now=1200)}
    assert drawn["a"]["status"] != "gone"


def test_freshness_buckets():
    conn = fresh_db()
    store.sync(conn, [listing("a")], classify, now=1000)
    f = lambda t: store.all_finds(conn, now=t)[0]["status"]
    assert f(1000 + 5 * 60) == "fresh"          # 5 min
    assert f(1000 + 60 * 60) == "warm"          # 1 h
    assert f(1000 + 8 * 60 * 60) == "cool"      # 8 h


def test_gone_beats_freshness():
    # A vanished posting reads as gone regardless of how fresh it was.
    conn = fresh_db()
    store.sync(conn, [listing("a")], classify, now=1000)
    store.sync(conn, [], classify, now=1000 + 60)  # gone while still "fresh"
    assert store.all_finds(conn, now=1000 + 60)[0]["status"] == "gone"
