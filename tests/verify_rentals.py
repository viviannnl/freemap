"""Headless-browser verification of the rentals map.

The filtering and walking-distance logic used to be pure Python in rental-watcher,
covered by unit tests. It now lives in the browser, so it's verified here in the
language it actually runs in - both as in-page unit checks of the pure functions
(the ported match() cases) and as real interactions with the map and the dock.

Run: ./.venv/bin/python tests/verify_rentals.py   (needs the server running)
Exits non-zero if any check fails.
"""

import os
import sys

from playwright.sync_api import sync_playwright

URL = os.getenv("RENTMAP_URL", "http://127.0.0.1:5001/rentals")
checks = []


def check(name, ok):
    checks.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1500, "height": 950})
    page.goto(URL, wait_until="networkidle")
    page.wait_for_selector(".pin.rent", timeout=20000)
    page.wait_for_timeout(1200)

    # --- pins ------------------------------------------------------------
    pins = page.locator(".pin.rent").count()
    check(f"rental pins rendered ({pins})", pins > 5)
    priced = page.evaluate(
        "() => [...document.querySelectorAll('.pin.rent .glyph')]"
        ".filter(g => /^\\$|^\\?$/.test(g.textContent)).length")
    check(f"pins are labelled with rent ({priced} of {pins})", priced == pins)
    check("freshness classes applied", page.locator(".pin.rent.fresh, .pin.rent.warm,"
                                                    " .pin.rent.cool").count() == pins)
    check("anchor pin is on the map", page.locator(".pin.anchor").count() == 1)

    # --- the walking model, ported from test_craigslist.py ---------------
    round_trip = page.evaluate("""() => [5,10,20,45].every(
        m => Shell.mode.walkMinutes(Shell.mode.metresForWalk(m)) === m)""")
    check("walkMinutes/metresForWalk round trip", round_trip)
    check("next door is a one minute walk, not zero",
          page.evaluate("() => Shell.mode.walkMinutes(0) === 1"))
    model = page.evaluate("() => Shell.mode.walkModel")
    check(f"walking model came from the server ({model})",
          abs(model["speed_m_per_min"] - 5000 / 60) < 0.01 and model["detour"] == 1.25)

    # --- eligible(): the ported match() cases ---------------------------
    cases = page.evaluate("""() => {
      const m = Shell.mode;
      const at = (dLat) => ({id:'t', title:'Bright studio', price:2000, bedrooms:0,
                             lat: m.anchor.lat + dLat, lon: m.anchor.lon});
      const save = {walkMin:m.walkMin, minPrice:m.minPrice, maxPrice:m.maxPrice,
                    beds:new Set(m.beds), whole:m.wholeUnitsOnly};
      const out = {};
      m.walkMin = 10; m.minPrice = 0; m.maxPrice = 0;
      m.beds = new Set([0,1,2,3]); m.wholeUnitsOnly = true;

      out.near = m.eligible(at(0.0018));            // ~200 m
      out.far  = m.eligible(at(0.018));             // ~2 km, past a 10 min walk
      m.walkMin = 40; out.farAt40 = m.eligible(at(0.018)); m.walkMin = 10;

      m.beds = new Set([1]);
      out.studioRejected = m.eligible({...at(0.0018), bedrooms:0});
      m.beds = new Set([0,1,2,3]);
      out.studioAccepted = m.eligible({...at(0.0018), bedrooms:0});
      out.unknownBedsKept = m.eligible({...at(0.0018), bedrooms:null});

      m.maxPrice = 2500;
      out.overCap = m.eligible({...at(0.0018), price:3000});
      out.noPriceKept = m.eligible({...at(0.0018), price:null});
      m.maxPrice = 0;
      out.zeroCapIsNoCap = m.eligible({...at(0.0018), price:99000});
      m.minPrice = 1500;
      out.underFloor = m.eligible({...at(0.0018), price:900});
      m.minPrice = 0;

      out.shareHidden = m.eligible({...at(0.0018), title:'ROOM FOR RENT in shared house'});
      m.wholeUnitsOnly = false;
      out.shareShown = m.eligible({...at(0.0018), title:'ROOM FOR RENT in shared house'});

      const item = at(0.0018); const before = JSON.stringify(item);
      m.eligible(item); out.pure = JSON.stringify(item) === before;

      Object.assign(m, {walkMin:save.walkMin, minPrice:save.minPrice,
                        maxPrice:save.maxPrice, beds:save.beds,
                        wholeUnitsOnly:save.whole});
      return out;
    }""")
    check("accepts a listing within the walk radius", cases["near"] is True)
    check("rejects one past the walk radius", cases["far"] is False)
    check("the same listing passes at a wider radius", cases["farAt40"] is True)
    check("rejects a studio when studios are deselected", cases["studioRejected"] is False)
    check("accepts a studio when selected", cases["studioAccepted"] is True)
    check("keeps a listing with no bedroom count", cases["unknownBedsKept"] is True)
    check("rejects a price over the cap", cases["overCap"] is False)
    check("keeps a listing with no price ('ask me' isn't 'too expensive')",
          cases["noPriceKept"] is True)
    check("a max of 0 means no cap", cases["zeroCapIsNoCap"] is True)
    check("rejects a price under the floor", cases["underFloor"] is False)
    check("hides room shares by default", cases["shareHidden"] is False)
    check("shows room shares when asked", cases["shareShown"] is True)
    check("eligible() does not mutate the listing", cases["pure"] is True)

    # --- repost detection, ported from mark_reposts() -------------------
    reposts = page.evaluate("""() => {
      const m = Shell.mode;
      const base = {price:2400, lat:m.anchor.lat, lon:m.anchor.lon,
                    title:'Bright 1 bed in Yaletown'};
      const rows = [{...base, id:'a'}, {...base, id:'b'}, {...base, id:'c'},
                    {...base, id:'d', price:3100, title:'Totally different place'}];
      m.markReposts(rows);
      return {firstRepeats: rows[0].repeats, laterAreReposts: rows[1].repost &&
              rows[2].repost, distinctIsNot: rows[3].repost};
    }""")
    check("relisted places collapse onto the newest row", reposts["firstRepeats"] == 2)
    check("the older duplicates are marked reposts", reposts["laterAreReposts"] is True)
    check("a genuinely different listing isn't", reposts["distinctIsNot"] is False)

    # --- interactions ---------------------------------------------------
    shown = int(page.locator("#countN").inner_text())
    check(f"count reflects visible rentals ({shown})", shown > 0)
    rows = page.locator("#rentList .rl").count()
    check(f"dock lists the rentals ({rows} rows)", rows > 0)

    page.eval_on_selector("#walk", "el => { el.value = 3; el.dispatchEvent(new Event('input')); }")
    page.wait_for_timeout(500)
    tight = int(page.locator("#countN").inner_text())
    check(f"walk slider narrows results ({shown} -> {tight})", tight < shown)
    page.eval_on_selector("#walk", "el => { el.value = 30; el.dispatchEvent(new Event('input')); }")
    page.wait_for_timeout(500)
    wide = int(page.locator("#countN").inner_text())
    check(f"and widens them again ({tight} -> {wide})", wide > tight)

    page.click('#bedChips .chip[data-beds="0"]')
    page.wait_for_timeout(400)
    no_studios = page.evaluate(
        "() => [...state.markers.values()].every(m => m.item.bedrooms !== 0)")
    check("deselecting Studio removes studio pins", no_studios)
    page.click('#bedChips .chip[data-beds="0"]')
    page.wait_for_timeout(300)

    page.fill("#maxPrice", "1800")
    page.dispatch_event("#maxPrice", "change")
    page.wait_for_timeout(400)
    under_cap = page.evaluate(
        "() => [...state.markers.values()].every(m => m.item.price === null || m.item.price <= 1800)")
    check("price cap removes dearer pins", under_cap)
    page.fill("#maxPrice", "")
    page.dispatch_event("#maxPrice", "change")
    page.wait_for_timeout(400)

    # sorting
    page.click('#sorts [data-sort="price"]')
    page.wait_for_timeout(400)
    ascending = page.evaluate("""() => {
      const prices = [...document.querySelectorAll('#rentList .rl .price')]
        .map(el => +el.textContent.replace(/[^0-9]/g, '') || Infinity);
      return prices.every((p, i) => i === 0 || prices[i-1] <= p);
    }""")
    check("sorting by price orders the list", ascending)
    page.click('#sorts [data-sort="new"]')
    page.wait_for_timeout(300)

    # --- two-way link between pin and row -------------------------------
    linked = page.evaluate("""() => {
      const id = [...state.markers.keys()][0];
      state.markers.get(id).marker.fire('click');
      const row = document.getElementById('rl-' + id);
      return {cardOpen: document.querySelector('#card.open') !== null,
              rowSelected: !!row && row.classList.contains('selected')};
    }""")
    page.wait_for_timeout(300)
    check("pin click opens the card", linked["cardOpen"] is True)
    check("pin click selects the matching row", linked["rowSelected"] is True)
    facts = page.inner_text("#cardFacts")
    check(f"card shows rent, size and walk time ({facts!r})",
          "walk" in facts and ("$" in facts or "?" in facts))
    check("card CTA links to craigslist",
          "craigslist.org" in (page.get_attribute("#cardCta", "href") or ""))

    row_click = page.evaluate("""() => {
      const rows = [...document.querySelectorAll('#rentList .rl')];
      const row = rows[Math.min(3, rows.length - 1)];
      row.click();
      return row.dataset.id;
    }""")
    page.wait_for_timeout(500)
    check("clicking a row opens that listing's card",
          page.evaluate("() => Shell.mode.selectedId") == row_click)

    # --- shortlist -------------------------------------------------------
    page.click("#cardHeart")
    page.wait_for_timeout(400)
    saved = page.evaluate("() => JSON.parse(localStorage.getItem('rentmap.stash')||'[]').length")
    check(f"heart saves to the shortlist (storage={saved})", saved == 1)
    page.click("#shortlistBtn")
    page.wait_for_timeout(400)
    check("shortlist view shows the saved place",
          page.locator("#rentList .rl").count() == 1)
    check("shortlist survives a filter that would hide it", page.evaluate("""() => {
      Shell.mode.maxPrice = 1;           // nothing can pass this
      render(state.lastLive);
      return document.querySelectorAll('#rentList .rl').length === 1;
    }"""))
    page.evaluate("() => { Shell.mode.maxPrice = 0; Shell.mode.view = 'live';"
                  " document.getElementById('shortlistBtn').classList.remove('on');"
                  " render(state.lastLive); }")
    page.wait_for_timeout(300)

    # --- the anchor ------------------------------------------------------
    moved = page.evaluate("""() => {
      const m = Shell.mode;
      const before = {...m.anchor};
      const id = [...state.markers.keys()][0];
      const was = m.walkOf(state.finds.get(id));
      m.anchor = {lat: before.lat + 0.02, lon: before.lon};
      m.saveAnchor();
      render(state.lastLive);
      const now = state.finds.has(id) ? m.walkOf(state.finds.get(id)) : null;
      const stored = JSON.parse(localStorage.getItem('rentmap.anchor'));
      m.anchor = before; m.saveAnchor(); render(state.lastLive);
      return {changed: now === null || now !== was,
              persisted: Math.abs(stored.lat - (before.lat + 0.02)) < 1e-9};
    }""")
    check("moving the anchor re-measures walking distance", moved["changed"] is True)
    check("the anchor is remembered in localStorage", moved["persisted"] is True)

    # --- year built, on demand ------------------------------------------
    page.wait_for_timeout(300)
    has_button = page.locator("#rentList .agebtn").count() > 0
    if has_button:
        page.locator("#rentList .agebtn").first.click()
        try:
            page.wait_for_function(
                "() => Object.keys(Shell.mode.builtCache).length > 0", timeout=40000)
            result = page.evaluate("() => Object.values(Shell.mode.builtCache)[0]")
            check(f"year-built lookup answers ({result})", isinstance(result, dict))
        except Exception:
            check("year-built lookup answers (timed out)", False)
    else:
        check("year-built lookup button present", False)

    page.screenshot(path="/tmp/rentmap_live.png")
    print("  screenshot -> /tmp/rentmap_live.png")
    b.close()

failed = [n for n, ok in checks if not ok]
print(f"\n{len(checks)-len(failed)}/{len(checks)} checks passed")
sys.exit(1 if failed else 0)
