# Craigslist Map 🗺️

Two live maps of Craigslist Vancouver, sharing one map, one theme and one codebase:

- **FreeMap** (`/`) — the **free** section as a treasure map. Free listings drop onto
  a dark map as glowing pins in real time; sweep your cursor like a flashlight to wake
  nearby pins, click one for a card with the real photo and a link to the post, and
  heart the good ones into your stash.
- **RentMap** (`/rentals`) — **rentals**, measured from a pin you drop anywhere. Pins
  are labelled with the rent; a docked list carries the detail a pin can't hold
  (bedrooms, floor area, walking time, year built, relisting history).

**Live:** https://craigslistmap.lettergen.io

Read-only by design: both maps discover and link out. Craigslist replies are
captcha-gated and are **not** automated.

## Architecture

Stateless, end to end. The server — local Flask `app.py`, or the Vercel functions in
`api/` — only crawls Craigslist on demand and returns what is currently posted.
Everything that needs to remember a previous visit happens in the browser:

- **freshness, loot-drops and the "gone" shatter** come from diffing successive polls
  against a first-seen map in `localStorage`
- **all filtering** — category and radius for free stuff; walking distance, price and
  bedrooms for rentals — runs client-side, so one edge-cached response serves every
  viewer and moving a slider is instant instead of a round trip
- **your anchor** (the point rental walking distances are measured from) lives only in
  your own `localStorage`. No address is baked into the page or stored on a server.

No background thread, no database.

### Where the code lives

```
craigslist/          reading Craigslist; read-only and stateless
  sapi.py            the internal search endpoint + how to decode its items
  free.py            the free section ("zip"): glyph, photo, category
  rentals.py         housing ("apa"): rent, bedrooms, floor area, walking model
  posted.py          the true post time for one posting
  building.py        year built, from the posting or City of Vancouver open data
payloads.py          the JSON both servers return (shared, so they can't drift)
httpjson.py          Vercel function boilerplate: dict -> JSON + cache header
app.py               local dev server, same routes as production
api/                 one Vercel function per route
static/
  app.js             the shell: map, pin diff engine, torch, card, ring, toast
  mode-free.js       what's particular to free stuff
  mode-rentals.js    what's particular to rentals (filters, dock, anchor)
  style.css          one dark theme; --accent switches gold -> mint on /rentals
  index.html         /          (FreeMap)
  rentals.html       /rentals   (RentMap)
```

A "mode" supplies where to poll, what a pin looks like, which items pass the current
filters and what goes on the card. Everything else is in `app.js`, once.

## Run

```bash
cd ~/projects/freemap
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/python app.py          # serves http://127.0.0.1:5001
```

Open http://127.0.0.1:5001 (free stuff) or http://127.0.0.1:5001/rentals. The
browser polls every 20 s; each poll is one request to Craigslist.

## Honest limits

These are all surfaced in the UI rather than hidden:

- **The 360 cap.** Craigslist's endpoint returns at most 360 postings per request and
  there is no way to page past them — measured, not assumed. Vancouver has ~1,000 free
  postings and ~6,800 rentals listed at once, so each map shows the newest 360 and says
  so ("newest 360 of 6,790 listed"). Good for catching what just appeared; not a way to
  browse the whole market.
- **"Spotted", not "posted".** The search endpoint carries no post time, so freshness is
  measured from when *your browser* first saw a posting. A card fetches the true posted
  time from the listing page when you open it.
- **Walking times are estimates.** Straight-line distance × 1.25 for street detours, at
  5 km/h. Not routed directions. The two constants ship in the API payload so the
  browser and the server can't drift apart.
- **Reposts.** Landlords relist the same unit and Craigslist mints a new id each time,
  so id-based dedupe can't see it. Identical rent, title and location collapse onto the
  newest row, tagged "relisted 3×" — often a sign it hasn't rented. Only within one
  crawl, since nothing is stored between visits.

## Deploy (Vercel)

```bash
vercel deploy --prod --yes
```

`vercel.json` maps `/` and `/rentals` to their static pages and bundles the
`craigslist/` package with each function. The custom domain
`craigslistmap.lettergen.io` is attached to the project. Note: the project's
`*.vercel.app` URL is behind Vercel Deployment Protection (login-gated); only the
custom domain is public.

## Tests / verification

```bash
./.venv/bin/python -m pytest tests/           # decoding, offline, no network
./.venv/bin/python tests/verify_ui.py         # FreeMap in a headless browser
./.venv/bin/python tests/verify_rentals.py    # RentMap in a headless browser
```

The browser suites need a server running. Point them at production instead:

```bash
FREEMAP_URL=https://craigslistmap.lettergen.io/ ./.venv/bin/python tests/verify_ui.py
RENTMAP_URL=https://craigslistmap.lettergen.io/rentals ./.venv/bin/python tests/verify_rentals.py
```

`tests/test_craigslist.py` guards the decoding of Craigslist's undocumented compact
arrays, using real captured responses — invented fixtures would test nothing, since
the whole risk is that the format isn't what we think. The filtering and walking-
distance rules used to be Python unit tests in `rental-watcher`; they now run in the
browser, so they're verified in `verify_rentals.py` against the JS that actually runs
(the ported `match()` cases, plus repost detection).

## Relationship to `rental-watcher`

`~/projects/rental-watcher` was a *watcher*: it polled on a schedule, kept history in
SQLite, emailed a digest and drove a browser to half-fill reply forms. This project
took over its knowledge — how to decode `apa` items, the walking model, the year-built
lookup, repost detection — and deliberately left the watching behind. ~2,500 of its
~3,000 lines (the database, mailer, IMAP watcher, Playwright replier, settings layer
and Jinja dashboard) have no counterpart here, which is what makes this deployable as
four stateless functions.

What that costs: **no push alerts** (you open the page rather than being emailed), and
**no cross-day history**, so relisting is only visible within one crawl. The old
project still runs locally if you want the digest emails back.

## Design

The visual target lives in Pixso (file `7xWshTLXaPoaDPey5wc9Nw`, node `3:1`).
RentMap reuses it, swapping the gold accent for mint so the two kinds of pin differ
in hue rather than only in lightness.

## Known follow-ups

- The inverted-OSM basemap reads slightly greener than the near-black mock; a keyed
  dark basemap would match exactly.
- Repost detection could span days by keeping a small tally in `localStorage`, the same
  trick used for first-seen.
- Only Vancouver. `sapi.AREA_ID`/`SUBAREA_ID` are the only things standing in the way
  of other cities.
