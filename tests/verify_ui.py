"""Headless-browser verification of the visual milestones (M3-M5).

Drives the live app at 127.0.0.1:5001: confirms pins render with freshness
classes, the cursor flashlight lights up, a pin click opens the card with real
data, the stash persists a save, and the loot-drop / gone-shatter animation
classes actually get applied by the render diff. Screenshots the result.

Run: ./.venv/bin/python tests/verify_ui.py
Exits non-zero if any check fails.
"""

import os
import sys
from playwright.sync_api import sync_playwright

URL = os.getenv("FREEMAP_URL", "http://127.0.0.1:5001/")
checks = []


def check(name, ok):
    checks.append((name, ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}")


with sync_playwright() as p:
    b = p.chromium.launch()
    page = b.new_page(viewport={"width": 1440, "height": 900})
    page.goto(URL, wait_until="networkidle")
    page.wait_for_selector(".pin", timeout=15000)
    page.wait_for_timeout(1500)

    # M2/M3: pins render, coloured by freshness
    pins = page.locator(".pin").count()
    check(f"pins rendered ({pins})", pins > 50)
    fresh = page.locator(".pin.fresh").count()
    check(f"freshness classes applied (fresh={fresh})", fresh > 0)
    count_n = int(page.locator("#countN").inner_text())
    check(f"count reflects visible finds ({count_n})", count_n > 0)

    # radius filter: shrinking radius reduces visible count
    page.eval_on_selector("#radius", "el => { el.value = 3; el.dispatchEvent(new Event('input')); }")
    page.wait_for_timeout(400)
    count_small = int(page.locator("#countN").inner_text())
    check(f"radius filter narrows results ({count_n} -> {count_small})", count_small < count_n)
    page.eval_on_selector("#radius", "el => { el.value = 15; el.dispatchEvent(new Event('input')); }")
    page.wait_for_timeout(400)

    # category filter
    page.click('.chip[data-cat="furniture"]')
    page.wait_for_timeout(400)
    only_furn = page.evaluate("() => [...document.querySelectorAll('.pin .glyph')].every(g => "
                              "['🪑','🛋️','🛏️','🪟'].includes(g.textContent))")
    check("category chip filters pins", only_furn)
    page.click('.chip[data-cat="all"]')
    page.wait_for_timeout(300)

    # M3: cursor flashlight lights up and wakes nearby pins
    page.mouse.move(720, 450)
    page.wait_for_timeout(300)
    torch_on = page.evaluate("() => document.body.classList.contains('torch') && "
                             "+getComputedStyle(document.getElementById('flashlight')).opacity > 0.5")
    check("cursor flashlight active over map", torch_on)

    # M4: clicking a pin -> card opens with real data. Fire the marker's click
    # through Leaflet (pixel-clicking is unreliable: many free posts share one
    # coordinate, so markers stack and occlude each other).
    page.evaluate("() => state.markers.values().next().value.marker.fire('click')")
    page.wait_for_timeout(400)
    card_open = page.locator("#card.open").count() == 1
    check("pin click opens listing card", card_open)
    title = page.locator("#cardTitle").inner_text()
    cta = page.get_attribute("#cardCta", "href") or ""
    check(f"card shows real title ({title[:24]!r})", len(title) > 1 and title != "—")
    check("card CTA links to craigslist", "craigslist.org" in cta)
    loc = page.inner_text("#cardLoc")
    check(f"card shows neighborhood + distance ({loc!r})", "km" in loc)

    # posted time is fetched lazily from the detail page and replaces the fallback
    try:
        page.wait_for_function("() => /posted/.test(document.getElementById('cardAge').textContent)",
                               timeout=20000)
        posted_txt = page.inner_text("#cardAge")
        check(f"card loads true posted time ({posted_txt!r})", "posted" in posted_txt)
    except Exception:
        check("card loads true posted time (detail fetch timed out)", False)

    # M4: heart -> stash persists
    page.click("#cardHeart")
    page.wait_for_timeout(200)
    stash_n = int(page.locator("#stashN").inner_text())
    saved = page.evaluate("() => JSON.parse(localStorage.getItem('freemap.stash')||'[]').length")
    check(f"heart saves to stash (badge={stash_n}, storage={saved})", stash_n == 1 and saved == 1)

    # M3: loot-drop + gone-shatter animation classes get applied by the diff
    drop_ok = page.evaluate("""() => {
      const f = [...state.finds.values()][0];
      const fake = {...f, id: 'TEST_NEW_'+Date.now()};
      state.first = false;
      render([...state.finds.values(), fake]);
      const el = document.querySelector(`.pin[data-id="${fake.id}"]`);
      return !!el && el.classList.contains('dropping');
    }""")
    check("new find triggers loot-drop animation", drop_ok)

    shatter_ok = page.evaluate("""() => {
      const entry = [...state.markers.entries()].find(([id]) => !id.startsWith('TEST_'));
      if (!entry) return false;
      const [id, m] = entry;
      // A crawl that no longer contains this id = it was claimed -> shatter.
      render(state.lastLive.filter(x => x.id !== id));
      const el = m.marker._icon && m.marker._icon.querySelector('.pin');
      return !!el && el.classList.contains('shattering');
    }""")
    check("vanished find triggers shatter animation", shatter_ok)

    page.screenshot(path="/tmp/freemap_live.png")
    print("  screenshot -> /tmp/freemap_live.png")
    b.close()

failed = [n for n, ok in checks if not ok]
print(f"\n{len(checks)-len(failed)}/{len(checks)} checks passed")
sys.exit(1 if failed else 0)
