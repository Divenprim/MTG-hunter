"""Browser check for the builder: build a deck, categorise, price, goldfish.

Needs a running server and Chromium, like tests/ui_check.py:

    .venv/Scripts/python.exe tests/ui_builder.py

It creates its own deck and deletes it at the end, so it does not touch decks
you actually care about. The price step really queries topdeck, so it takes
about half a minute.
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
FAIL = []
DECK_NAME = "UI Проверка"


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


CARDS = ["Sol Ring", "Cultivate", "Swords to Plowshares", "Rhystic Study",
         "Counterspell", "Beast Within", "Demonic Tutor", "Eternal Witness"]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)

    page.goto(BASE, wait_until="networkidle")
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(700)
    check("builder tab opens", page.locator("#panel-builder").is_visible())

    print()
    print("=== create a deck ===")
    page.fill("#bd-newdeck", DECK_NAME)
    page.press("#bd-newdeck", "Enter")
    page.wait_for_function(
        "() => !document.querySelector('#bd-editor').hidden", timeout=20000)
    check("editor opens for the new deck",
          page.input_value("#bd-name") == "UI Проверка",
          page.input_value("#bd-name"))
    check("format defaults to commander",
          page.input_value("#bd-format") == "commander")

    print()
    print("=== add cards through the suggestion box ===")
    page.select_option("#bd-section", "commander")
    page.fill("#bd-add", "Atraxa, Praetors")
    page.wait_for_function(
        "() => document.querySelectorAll('#bd-suggest .setrow').length > 0", timeout=20000)
    page.locator("#bd-suggest .setrow").first.click()
    page.wait_for_function(
        "() => document.querySelectorAll('#bd-cards .bdrow').length > 0", timeout=20000)
    check("commander added", page.locator("#bd-cards .bdrow").count() == 1)

    page.select_option("#bd-section", "main")
    for name in CARDS:
        page.fill("#bd-add", name)
        page.wait_for_function(
            "() => document.querySelectorAll('#bd-suggest .setrow').length > 0",
            timeout=20000)
        page.locator("#bd-suggest .setrow").first.click()
        page.wait_for_timeout(500)
    rows = page.locator("#bd-cards .bdrow").count()
    check("all cards were added", rows == len(CARDS) + 1, "%d rows" % rows)

    print()
    print("=== quantity stepper ===")
    first_main = page.locator("#bd-cards .bdrow").nth(1)
    first_main.locator('button[data-step="1"]').click()
    page.wait_for_timeout(800)
    qty = page.locator("#bd-cards .bdrow").nth(1).locator(".qty b").text_content()
    check("plus raises the quantity", qty.strip() == "2", "got %r" % qty)

    print()
    print("=== validation reacts ===")
    problems = page.locator("#bd-problems .problem").count()
    check("problems are listed", problems > 0, "%d problems" % problems)
    text = page.locator("#bd-problems").text_content() or ""
    check("singleton violation is reported", "синглтон" in text, text[:90])

    first_main.locator('button[data-step="-1"]').click()
    page.wait_for_timeout(800)

    print()
    print("=== auto-categorise from functional tags ===")
    page.click('#bd-actions button[data-act="autocat"]')
    page.wait_for_timeout(2500)
    # The category of a row lives in an <input class="cat"> -- its value is not
    # part of text_content(), so the list has to be read field by field.
    cats = [c.strip() for c in page.eval_on_selector_all(
        "#bd-cards input.cat", "els => els.map(e => e.value)") if c.strip()]
    got = sorted(set(cats))
    check("categories were assigned", len(got) >= 2, "found: %s" % got[:6])

    print()
    print("=== rouble prices from topdeck ===")
    # Wait for the BUTTON to come back, not for the status text: the old
    # status already said "цены известны" from the previous render, so waiting
    # on that string succeeds instantly and reads stale numbers.
    page.click("#bd-prices")
    page.wait_for_function(
        "() => !document.querySelector('#bd-prices').disabled", timeout=300000)
    page.wait_for_timeout(400)
    stat = page.locator("#bd-pricestat").text_content() or ""
    check("prices came back", "₽" in stat, stat[:100])
    priced = page.locator("#bd-cards .rub b").count()
    check("per-card rouble prices are shown", priced > 0, "%d priced rows" % priced)

    print()
    print("=== versions ===")
    page.click("#panel-builder details.help summary")
    page.wait_for_timeout(300)
    page.fill("#bd-version-label", "снимок")
    page.click("#bd-save-version")
    page.wait_for_timeout(1200)
    check("version saved", page.locator("#bd-versions .bdversion").count() >= 1)

    print()
    print("=== goldfishing ===")
    page.click('#bd-actions button[data-act="goldfish"]')
    page.wait_for_timeout(600)
    check("goldfish window opens", page.locator("#gf-overlay").is_visible())
    page.click("#gf-deal")
    page.wait_for_function(
        "() => document.querySelectorAll('#gf-hand .card').length > 0", timeout=20000)
    hand = page.locator("#gf-hand .card").count()
    check("a hand is dealt", hand > 0, "%d cards" % hand)
    page.click("#gf-draw")
    page.wait_for_timeout(400)
    check("drawing adds a card",
          page.locator("#gf-hand .card").count() == hand + 1)

    page.select_option("#gf-games", "200")
    page.click("#gf-run")
    page.wait_for_function(
        "() => document.querySelectorAll('#gf-stats .statbox').length > 0", timeout=60000)
    boxes = page.locator("#gf-stats .statbox").count()
    check("simulation reports statistics", boxes >= 5, "%d boxes" % boxes)
    stats_text = page.locator("#gf-stats").text_content() or ""
    check("assumptions are stated", "Допущения" in stats_text)
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)
    check("Esc closes goldfish", page.locator("#gf-overlay").is_hidden())

    print()
    print("=== missing cards to the hunt ===")
    page.click('#bd-actions button[data-act="hunt"]')
    page.wait_for_timeout(900)
    wants = page.input_value("#hunt-wants")
    check("missing cards reach the hunt", "Sol Ring" in wants, wants[:60])

    print()
    print("=== cleanup ===")
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(400)
    page.on("dialog", lambda d: d.accept())
    page.click("#bd-delete")
    page.wait_for_timeout(1500)
    # Only this test's deck must go; the user's own decks stay.
    left = [t.strip() for t in page.locator("#bd-decks .bddeck .nm").all_text_contents()]
    check("test deck deleted, user decks untouched", DECK_NAME not in left,
          "осталось: %s" % left)

    print()
    check("no console errors", not errors, "; ".join(errors[:3]))
    page.screenshot(path="tests/ui_builder.png")
    browser.close()

print()
if FAIL:
    print("FAILED: %s" % FAIL)
else:
    print("ALL BUILDER CHECKS PASSED")
