"""Browser check: suggestions from a sample of real decks.

The tab answers what the aggregated numbers cannot: of the decks that look like
yours, how many run this card, and is that more than the sample runs it
generally. So the checks are about the two numbers being there and being
different from each other, about what must never be suggested (your own
commander, cards already in the deck), and about the sample being described
honestly rather than presented as the truth.

One thing here is not about the interface at all: pressing «Остановить» must
actually stop the traffic. That is the promise made to somebody else's server,
so it is checked -- the run fetches exactly one chunk and stops.

Uses the sample already on disk if there is one, and creates and deletes its
own deck. Needs a running server and Chromium:

    .venv/Scripts/python.exe tests/ui_cooccur.py
"""

import os
from playwright.sync_api import sync_playwright

# Куда стучаться. По умолчанию -- обычный запуск; MTGH_UI_BASE нужна,
# когда на этом порту уже работает другая копия программы (скажем,
# запущенная по https для планшета).
BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
DECK_NAME = "UI Выборка"
COMMANDER = "Tiamat"
IN_DECK = ["Sol Ring", "Command Tower", "Arcane Signet", "Dragon Tempest",
           "Cultivate"]
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def sweep(page):
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
    sweep(page)

    page.click('.tab[data-tab="builder"]')
    page.wait_for_function(
        "() => document.querySelector('#panel-builder.active') !== null", timeout=20000)
    page.wait_for_timeout(700)

    print("=== a deck to compare against ===")
    page.fill("#bd-newdeck", DECK_NAME)
    page.press("#bd-newdeck", "Enter")
    page.wait_for_function(
        "() => !document.querySelector('#bd-editor').hidden", timeout=20000)
    page.select_option("#bd-view", "rows")
    page.select_option("#bd-section", "commander")
    page.fill("#bd-add", COMMANDER)
    page.wait_for_function(
        "() => document.querySelectorAll('#bd-suggest .setrow').length > 0", timeout=30000)
    page.locator("#bd-suggest .setrow").first.click()
    # Командир показывается карточкой, а не строкой списка: ждём именно её.
    page.wait_for_function(
        "() => document.querySelectorAll('#bd-cards .cmdcard').length > 0",
        timeout=20000)

    page.select_option("#bd-section", "main")
    for name in IN_DECK:
        page.fill("#bd-add", name)
        page.wait_for_function(
            "() => document.querySelectorAll('#bd-suggest .setrow').length > 0",
            timeout=30000)
        page.locator("#bd-suggest .setrow").first.click()
        page.wait_for_timeout(450)
    check("deck built", page.locator("#bd-cards .bdrow").count() >= 5,
          "%d строк" % page.locator("#bd-cards .bdrow").count())

    print()
    print("=== the tab opens without fetching anything ===")
    page.dispatch_event('#bd-actions button[data-act="recommend"]', "click")
    page.wait_for_function(
        "() => !document.querySelector('#rec-overlay').hidden", timeout=20000)
    page.locator('#rec-tabs [data-rectab="cooccur"]').click()
    page.wait_for_function(
        "() => document.querySelector('#rec-sample').innerHTML.length > 0",
        timeout=30000)
    head = " ".join((page.locator("#rec-sample").text_content() or "").split())
    check("the sample size is stated", "скачано колод" in head, head[:80])
    check("the target can be chosen", page.locator("#rec-target").count() == 1)
    have = page.evaluate("() => (coState && coState.decks) || 0")
    print("      колод в кеше: %s" % have)

    print()
    print("=== what the numbers are, said out loud ===")
    if have:
        page.wait_for_function(
            "() => document.querySelectorAll('#rec-cooccur-body .recrow').length > 0"
            " || document.querySelector('#rec-cooccur-body').textContent.includes('Пересчитать')",
            timeout=60000)
    body = " ".join((page.locator("#rec-cooccur-body").text_content() or "").split())
    check("says the decks come from Archidekt", "Archidekt" in body, body[:90])
    check("calls the sample a sample", "выборка" in body.lower(), body[:120])
    check("explains the second column",
          "чаще, чем в выборке" in body or "около нуля" in body, body[:200])

    rows = page.evaluate("""() => {
      return [...document.querySelectorAll('#rec-cooccur-body .recrow')].map((r) => ({
        name: r.dataset.name,
        share: (r.querySelector('.share') || {}).textContent || '',
        title: (r.querySelector('.share') || {}).title || '',
      }));
    }""")
    check("rows are rendered", len(rows) > 0, "%d строк" % len(rows))
    if rows:
        check("a row shows how many of the near decks run it",
              "колодах из" in rows[0]["title"], rows[0]["title"])
        names = {r["name"] for r in rows}
        check("your own commander is never suggested", COMMANDER not in names)
        check("cards already in the deck are not suggested",
              not (names & set(IN_DECK)), str(names & set(IN_DECK)))

    print()
    print("=== what travels with a card ===")
    if rows:
        page.locator('#rec-cooccur-body .recrow [data-rec="pairs"]').first.click()
        page.wait_for_function(
            "() => { const b = document.querySelector('.copairs');"
            " return b && b.textContent.indexOf('смотрю') < 0; }", timeout=60000)
        pairs = " ".join((page.locator(".copairs").first.text_content() or "").split())
        check("the pair list answers from the sample",
              "В выборке" in pairs or "выборке этой карты нет" in pairs, pairs[:110])
        page.locator('#rec-cooccur-body .recrow [data-rec="pairs"]').first.click()
        page.wait_for_timeout(300)
        check("and it folds away again", page.locator(".copairs").count() == 0)

    print()
    print("=== stopping actually stops ===")
    before = page.evaluate("() => (coState && coState.decks) || 0")
    # Цель должна быть больше уже скачанного, иначе качать нечего: сбор
    # закончится, не начавшись, и останавливать будет нечего.
    target = next((n for n in (60, 150, 300) if n > before), 300)
    page.select_option("#rec-target", str(target))
    page.wait_for_timeout(600)
    page.locator("#rec-sample-go").click()
    page.wait_for_function(
        "() => document.querySelector('#rec-sample-stop') !== null", timeout=20000)
    page.locator("#rec-sample-stop").click()
    check("the stop button is offered while fetching", True)
    # One chunk is at most CHUNK decks at 1.5s each, so allow it to finish.
    page.wait_for_function(
        "() => coBusy === false", timeout=180000)
    after = page.evaluate("() => (coState && coState.decks) || 0")
    chunk = page.evaluate("() => (coState && coState.chunk) || 12")
    check("it stopped after one chunk, not at the target",
          after - before <= chunk and after < target,
          "было %s, стало %s из %s (порция %s)" % (before, after, target, chunk))
    check("and what was fetched is kept", after >= before, "%s -> %s" % (before, after))

    print()
    print("=== cleanup ===")
    page.locator("#rec-close").click()
    page.wait_for_timeout(300)
    left = sweep(page)
    check("test deck deleted, user decks untouched", left == 0,
          "осталось с этим именем: %d" % left)

    print()
    check("no console errors", not errors, "; ".join(errors[:3]))
    page.screenshot(path="tests/ui_cooccur.png")
    browser.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL SAMPLE CHECKS PASSED")
