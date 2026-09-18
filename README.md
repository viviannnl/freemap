# FreeMap 🗺️

A live "treasure map" of Vancouver's **free** Craigslist stuff. Free listings drop
onto a dark map as glowing pins in real time; sweep your cursor like a flashlight to
wake nearby pins, click one for a card with the real photo and a link to the post,
and heart the good ones into your stash. Sibling project to `rental-watcher`, reusing
its Craigslist JSON-API approach.

**Live:** https://craigslistmap.lettergen.io

Read-only by design: it discovers and links out. Craigslist replies are captcha-gated
and are **not** automated.

## Architecture

Stateless. The server (local Flask `app.py`, or the Vercel function `api/finds.py`)
just crawls Craigslist on demand and returns the current set of free postings. All
the liveliness - freshness colours, loot-drops, the "gone" shatter - is computed in
the browser by diffing successive polls and remembering when each posting was first
seen (`localStorage`). No background thread, no database, so it runs anywhere,
including a serverless function.

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
- **`classify.py`** — title keywords → category + emoji glyph for the pin.
- **`app.py`** — local Flask dev server; `GET /api/finds` returns the current finds.
- **`api/finds.py`** — the same payload as a Vercel serverless function.
- **`static/`** — Leaflet map (key-free OSM tiles inverted to dark), animated pins,
  cursor flashlight, listing card, `localStorage` stash + first-seen freshness,
  category + radius filters. Freshness thresholds (`FRESH_MS`, `WARM_MS`) live here.

## Freshness model — honest caveat

`first_seen` is when this app first observed a posting, not the true Craigslist post
time. An always-on watcher converges (new posts are seen within a poll interval), but
a freshly started one shows everything as "just spotted". The UI says **"spotted"**,
not "posted", on purpose.

## Deploy (Vercel)

```bash
vercel deploy --prod --yes
```

`vercel.json` maps `/` to `static/index.html` and bundles `craigslist.py` +
`classify.py` with the function. The custom domain `craigslistmap.lettergen.io`
is attached to the project. Note: the project's `*.vercel.app` URL is behind
Vercel Deployment Protection (login-gated); the custom domain is public.

## Tests / verification

```bash
./.venv/bin/python tests/verify_ui.py          # headless-browser UI checks (needs a server)
# against production instead of localhost:
FREEMAP_URL=https://craigslistmap.lettergen.io/ ./.venv/bin/python tests/verify_ui.py
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
