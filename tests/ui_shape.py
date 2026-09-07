"""Browser check: the shape of a deck against the average, and the suggestion mode.

Two things are being checked, and they are the two the feature is for.

The «Форма колоды» tab must give numbers you can act on: how many creatures,
lands, ramp, draw and removal the average deck on this commander runs, beside
your own, with the large gaps called out. The averages come from the commander
page we already cache, so the tab must work without asking topdeck anything.

The suggestion mode must not nag. It offers itself once per deck, remembers the
answer, and after that it is one line under the statistics. Until it is turned
on, nothing is fetched at all.

Creates its own deck and deletes it afterwards; the user's decks are not
touched.

Needs a running server and Chromium:

    .venv/Scripts/python.exe tests/ui_shape.py
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
DECK_NAME = "UI Форма"
COMMANDER = "Tiamat"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def sweep(page):
    """Remove decks this test made, by name, without touching the user's."""
    return page.evaluate("""async (name) => {
      const r = await fetch('/api/decks').then(x => x.json());
      for (const d of r.decks.filter(d => d.name === name)) {
        await fetch('/api/decks/' + d.id, {method: 'DELETE'});
      }
      const after = await fetch('/api/decks').then(x => x.json());
      return after.decks.filter(d => d.name === name).length;
    }""", DECK_NAME)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1150}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")

    # A crashed earlier run must not make this one fail on its leftovers.
    sweep(page)

    page.click('.tab[data-tab="builder"]')
    page.wait_for_function(
        "() => document.querySelector('#panel-builder.active') !== null", timeout=20000)
    page.wait_for_timeout(700)

    print("=== a deck with a commander ===")
    page.fill("#bd-newdeck", DECK_NAME)
    page.press("#bd-newdeck", "Enter")
    page.wait_for_function(
        "() => !document.querySelector('#bd-editor').hidden", timeout=20000)
    check("deck created", page.input_value("#bd-name") == DECK_NAME,
          page.input_value("#bd-name"))

    check("nothing is offered while there is no commander",
          page.evaluate("() => document.querySelector('#bd-advice').hidden") is True)

    page.select_option("#bd-view", "rows")
    page.select_option("#bd-section", "commander")
    page.fill("#bd-add", COMMANDER)
    page.wait_for_function(
        "() => document.querySelectorAll('#bd-suggest .setrow').length > 0",
        timeout=30000)
    page.locator("#bd-suggest .setrow").first.click()
    page.wait_for_function(
        "() => document.querySelectorAll('#bd-cards .bdrow').length > 0", timeout=20000)

    page.select_option("#bd-section", "main")
    for name in ("Sol Ring", "Cultivate", "Lightning Bolt"):
        page.fill("#bd-add", name)
        page.wait_for_function(
            "() => document.querySelectorAll('#bd-suggest .setrow').length > 0",
            timeout=30000)
        page.locator("#bd-suggest .setrow").first.click()
        page.wait_for_timeout(500)

    print()
    print("=== the suggestion mode offers itself once ===")
    page.wait_for_function(
        "() => !document.querySelector('#bd-advice').hidden", timeout=20000)
    strip = " ".join((page.locator("#bd-advice").text_content() or "").split())
    check("offered after a commander appears", "Подсказывать карты" in strip, strip[:70])
    check("and the offer names the commander", COMMANDER in strip, strip[:90])
    check("nothing is computed before you agree",
          page.locator("#bd-advice-line").count() == 0)

    page.locator('#bd-advice button[data-advice="on"]').click()
    page.wait_for_function(
        "() => { const el = document.querySelector('#bd-advice-line');"
        " return el && el.textContent && el.textContent.indexOf('считаю') < 0; }",
        timeout=60000)
    line = " ".join((page.locator("#bd-advice-line").text_content() or "").split())
    check("turning it on shows the gaps in one line", bool(line), line[:90])
    check("and the line is about the average deck",
          "средней" in line or "расхождений нет" in line, line[:90])

    print()
    print("=== the shape tab ===")
    page.locator('#bd-advice button[data-advice="open"]').click()
    page.wait_for_function(
        "() => !document.querySelector('#rec-overlay').hidden", timeout=20000)
    page.wait_for_function(
        "() => document.querySelectorAll('#rec-pane-shape table.shape').length >= 2",
        timeout=60000)
    check("opens straight on the shape tab",
          page.evaluate(
              "() => document.querySelector('#rec-pane-shape').hidden") is False)

    shape = page.locator("#rec-pane-shape")
    text = " ".join((shape.text_content() or "").split())
    for word in ("Типы карт", "Функции", "Кривая маны", "Земли", "Рампа"):
        check("shows «%s»" % word, word in text)
    check("says how many decks the average is over", "колодам на этом командире" in text,
          text[-120:])

    rows = page.evaluate("""() => {
      const out = [];
      document.querySelectorAll('#rec-pane-shape table.shape tr').forEach((tr) => {
        const lbl = tr.querySelector('td.lbl');
        const nums = tr.querySelectorAll('td.num');
        if (lbl && nums.length === 2) {
          out.push({label: lbl.textContent.trim(),
                    yours: Number(nums[0].textContent),
                    average: Number(nums[1].textContent),
                    notable: tr.classList.contains('notable')});
        }
      });
      return out;
    }""")
    lands = next((r for r in rows if r["label"] == "Земли"), None)
    check("your side and the average side are both filled",
          lands is not None and lands["average"] > 20,
          str(lands))
    check("a deck of four cards is called out as short of lands",
          lands is not None and lands["notable"] and lands["yours"] < lands["average"],
          str(lands))
    ramp = next((r for r in rows if r["label"] == "Рампа"), None)
    check("ramp is counted on both sides", ramp is not None and ramp["average"] > 5,
          str(ramp))
    check("and our two ramp cards are seen", ramp is not None and ramp["yours"] == 2,
          str(ramp))
    advice = " ".join(
        (page.locator("#rec-pane-shape ul.shape-advice").first.text_content() or "").split())
    check("the advice says what to add", "добавить" in advice, advice[:110])

    print()
    print("=== themes and combos, from the same cached page ===")
    page.locator('#rec-tabs [data-rectab="themes"]').click()
    page.wait_for_timeout(400)
    themes = " ".join((page.locator("#rec-pane-themes").text_content() or "").split())
    check("themes are shown", "С чем его собирают" in themes)
    check("brackets and budget are shown", "брекет" in themes, themes[:90])
    check("popular combos are shown", "Частые комбо" in themes)
    check("chips are not empty",
          page.locator("#rec-pane-themes .themechips .chip").count() > 2,
          "%d чипов" % page.locator("#rec-pane-themes .themechips .chip").count())
    # A tab inside the modal must not reach the page's own tab router: these
    # buttons are .subtab for exactly that reason.
    check("the page behind the panel is still on the builder",
          page.evaluate(
              "() => document.querySelector('#panel-builder')"
              ".classList.contains('active')") is True)

    print()
    print("=== it can be switched off and stays off ===")
    page.locator("#rec-close").click()
    page.wait_for_timeout(300)
    page.locator('#bd-advice button[data-advice="off"]').click()
    page.wait_for_timeout(400)
    check("switched off, the strip is gone",
          page.evaluate("() => document.querySelector('#bd-advice').hidden") is True)

    deck_id = page.evaluate("() => bdDeck.id")
    page.click('.tab[data-tab="search"]')
    page.wait_for_timeout(300)
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(800)
    page.evaluate("(id) => bdOpen(id)", deck_id)
    page.wait_for_timeout(1200)
    check("and it does not come back on reopening",
          page.evaluate("() => document.querySelector('#bd-advice').hidden") is True)
    check("the answer is remembered per deck",
          page.evaluate("(id) => store.get('bdAdvice.' + id, null)", deck_id) is False)

    print()
    print("=== cleanup ===")
    left = sweep(page)
    page.wait_for_timeout(300)
    check("test deck deleted, user decks untouched", left == 0,
          "осталось с этим именем: %d" % left)

    print()
    check("no console errors", not errors, "; ".join(errors[:3]))
    page.screenshot(path="tests/ui_shape.png")
    browser.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL DECK-SHAPE CHECKS PASSED")
