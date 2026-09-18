# FreeMap 🗺️

A live "treasure map" of Vancouver's **free** Craigslist stuff. Free listings drop
onto a dark map as glowing pins in real time; sweep your cursor like a flashlight to
wake nearby pins, click one for a card with the real photo and a link to the post,
and heart the good ones into your stash. Sibling project to `rental-watcher`, reusing
its Craigslist JSON-API approach.

Read-only by design: it discovers and links out. Craigslist replies are captcha-gated
and are **not** automated.

## Run

```bash
cd ~/projects/freemap
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python app.py          # serves http://127.0.0.1:5001
```

Open http://127.0.0.1:5001. The backend crawls once on startup, then every
`POLL_SECONDS` (default 120).

## How it works

- **`craigslist.py`** — one request per poll to `sapi.craigslist.org` for the `zip`
  (free) category in Vancouver. Coordinates and image ids come back inline; no page
  scraping. Verified: ~360 postings/poll, 100% geocoded, ~92% with photos.
- **`store.py`** — SQLite that times freshness from when *we first saw* a posting
  (the search API has no post time). Detects new arrivals (loot-drops) and
  disappearances (the "gone" shatter, kept visible for `GONE_TTL_S`).
- **`classify.py`** — title keywords → category + emoji glyph for the pin.
- **`app.py`** — Flask; background poll thread; `GET /api/finds` serves the drawable set.
- **`static/`** — Leaflet map (key-free OSM tiles inverted to dark), animated pins,
  cursor flashlight, listing card, `localStorage` stash, category + radius filters.

## Freshness model — honest caveat

`first_seen` is when this app first observed a posting, not the true Craigslist post
time. An always-on watcher converges (new posts are seen within a poll interval), but
a freshly started one shows everything as "just spotted". The UI says **"spotted"**,
not "posted", on purpose.

## Tests / verification

```bash
./.venv/bin/python -m pytest tests/            # store state machine (offline)
./.venv/bin/python tests/verify_ui.py          # headless-browser UI checks (needs server running)
```

Milestone success criteria, all passing:

| Milestone | Success criterion | Check |
|---|---|---|
| M1 data | Real free listings, geocoded + photos | `craigslist.py` → 360 pinnable, 100% coords, 331 photos |
| M2 API/map | `/api/finds` real shape; pins render | `verify_ui`: 196 pins, count reflects finds |
| M3 fun | Freshness colours, loot-drop, shatter, flashlight | `verify_ui`: 4 checks pass |
| M4 card/stash/filters | Card opens w/ real data + CTA; heart persists; radius+category filter | `verify_ui`: 6 checks pass |
| M5 polish | Matches the Pixso design on a dark map | screenshot `/tmp/freemap_live.png` |

## Design

The visual target lives in Pixso (file `7xWshTLXaPoaDPey5wc9Nw`, node `3:1`).

## Known follow-ups

- Freshness would be exact if we fetched each detail page's post time (costs N requests/poll — skipped on purpose).
- Neighbourhood names aren't in the API; the card shows distance from map centre instead.
- The inverted-OSM map reads slightly greener than the near-black mock; a keyed dark basemap would match exactly.
