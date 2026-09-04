"""Browser check: builder grouping modes, views, keyword and typal pickers.

Needs a running server and Chromium:

    .venv/Scripts/python.exe tests/ui_groups.py

Creates its own deck and deletes it at the end.
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
FAIL = []

CARDS = ["Sol Ring", "Cultivate", "Swords to Plowshares", "Rhystic Study",
         "Counterspell", "Ephemerate", "Wall of Omens", "Eternal Witness",
         "Plains", "Command Tower", "Doubling Season", "Blightsteel Colossus"]


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


with sync_playwright() as pw:
    b = pw.chromium.launch()
    p = b.new_context(viewport={"width": 1500, "height": 1150}).new_page()
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    p.goto(BASE, wait_until="networkidle")

    print("=== keyword and typal pickers in search ===")
    p.click("#filters-toggle")
    p.wait_for_timeout(1200)
    kw = p.locator("#f-kw-presets button").count()
    check("keyword presets are offered", kw >= 10, "%d keywords" % kw)
    typal = p.locator("#f-typal-list .tagrow").count()
    check("tribal list is populated", typal >= 20, "%d tribes" % typal)

    p.click('#f-kw-presets button[data-kw="defender"]')
    p.wait_for_function(
        "() => { const m=document.querySelector('#search-meta');"
        " return m && (m.textContent||'').indexOf('показано') >= 0; }", timeout=30000)
    composed = p.input_value("#search-q")
    check("keyword composes into the query", "kw:defender" in composed, composed)
    found = p.locator("#search-results .card").count()
    check("defenders are found", found > 0, "%d tiles" % found)

    p.fill("#f-typal-input", "dragon")
    p.wait_for_timeout(600)
    rows = p.locator("#f-typal-list .tagrow").count()
    check("tribal filter narrows the list", 0 < rows < typal, "%d rows" % rows)
    p.locator("#f-typal-list .tagrow").first.click()
    p.wait_for_timeout(2500)
    composed = p.input_value("#search-q")
    check("a tribe joins the query", "otag:typal-" in composed, composed)

    p.click("#filters-reset")
    p.wait_for_timeout(1800)
    p.click("#filters-toggle")

    print()
    print("=== builder: grouping modes ===")
    p.click('.tab[data-tab="builder"]')
    p.wait_for_timeout(700)
    p.fill("#bd-newdeck", "Группировка")
    p.press("#bd-newdeck", "Enter")
    p.wait_for_function("() => !document.querySelector('#bd-editor').hidden", timeout=20000)
    for name in CARDS:
        p.fill("#bd-add", name)
        p.wait_for_function(
            "() => document.querySelectorAll('#bd-suggest .setrow').length > 0", timeout=20000)
        p.locator("#bd-suggest .setrow").first.click()
        p.wait_for_timeout(430)

    def group_titles():
        return [t.strip() for t in p.locator("#bd-cards h4").all_text_contents()]

    # Grouping is checked in the list view: the default is stacks, where the
    # group name lives in a column header rather than an <h4>.
    p.select_option("#bd-view", "rows")
    p.wait_for_timeout(400)
    p.select_option("#bd-group", "type")
    p.wait_for_timeout(700)
    titles = " ".join(group_titles())
    check("grouped by card type", "Существа" in titles and "Земли" in titles, titles[:110])

    p.select_option("#bd-group", "cmc")
    p.wait_for_timeout(600)
    titles = " ".join(group_titles())
    check("grouped by mana value", "МС 1" in titles or "МС 2" in titles, titles[:110])
    order = [t.split()[1] for t in group_titles() if t.startswith("МС")]
    check("mana values ascend, not alphabetical", order == sorted(order), str(order))

    p.select_option("#bd-group", "keyword")
    p.wait_for_timeout(600)
    titles = " ".join(group_titles())
    check("grouped by keyword shows defenders", "Дефендеры" in titles, titles[:120])

    p.select_option("#bd-group", "color")
    p.wait_for_timeout(600)
    titles = " ".join(group_titles())
    check("grouped by colour", "Белые" in titles or "Бесцветные" in titles, titles[:110])

    p.select_option("#bd-group", "category")
    p.click('#bd-actions button[data-act="autocat"]')
    p.wait_for_timeout(3500)
    titles = " ".join(group_titles())
    got = [w for w in ("блинк", "туторы", "удаление", "рампа", "добор") if w in titles]
    check("categories include the new mechanics", len(got) >= 3, "found %s" % got)

    print()
    print("=== views ===")
    p.select_option("#bd-view", "compact")
    p.wait_for_timeout(600)
    check("compact view hides images",
          p.locator("#bd-cards .bdrow.compact").count() > 0)
    p.select_option("#bd-view", "grid")
    p.wait_for_timeout(900)
    grid = p.locator("#bd-cards .bdgrid .gcard").count()
    check("grid view shows card images", grid > 0, "%d cards" % grid)
    p.select_option("#bd-view", "rows")
    p.wait_for_timeout(600)

    print()
    print("=== filter inside the deck ===")
    p.fill("#bd-filter", "plains")
    p.wait_for_timeout(700)
    rows = p.locator("#bd-cards .bdrow").count()
    check("deck filter narrows the list", 0 < rows < len(CARDS), "%d rows" % rows)
    p.fill("#bd-filter", "")
    p.wait_for_timeout(600)

    print()
    print("=== cleanup ===")
    p.on("dialog", lambda d: d.accept())
    p.click("#bd-delete")
    p.wait_for_timeout(1800)
    # Only OUR deck must be gone. The user's own decks stay in the list, so an
    # empty list is the wrong thing to demand.
    left = [t.strip() for t in p.locator("#bd-decks .bddeck .nm").all_text_contents()]
    check("test deck deleted, user decks untouched",
          "Группировка" not in left, "осталось: %s" % left)

    print()
    check("no console errors", not errors, "; ".join(errors[:3]))
    p.screenshot(path="tests/ui_groups.png")
    b.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL GROUPING CHECKS PASSED")
