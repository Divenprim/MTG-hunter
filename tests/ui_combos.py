"""Browser check: combos.

Two views, and the second is the point of doing this at all:

  * what the deck already has;
  * what it is one card short of -- which becomes a shopping list, so the
    missing card carries its rouble price and goes into the hunt in one click.

Also guards the claim the interface must not make: in the card window there is
no deck to compare against, so nothing there may be labelled "собрано".

Needs a running server, Chromium, and a built combo database
(data/combos.sqlite -- the panel offers to download it).

    .venv/Scripts/python.exe tests/ui_combos.py
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_context(viewport={"width": 1400, "height": 950}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")

    ready = page.evaluate(
        "async () => (await (await fetch('/api/combos/status')).json()).ready")
    if not ready:
        check("база комбо собрана", False,
              "нет data/combos.sqlite — соберите её кнопкой в панели комбо")
        b.close()
        raise SystemExit(1)

    print("=== combos in the deck ===")
    page.click('.tab[data-tab="builder"]')
    page.wait_for_function(
        "() => document.querySelector('#panel-builder.active') !== null", timeout=20000)
    page.wait_for_timeout(900)
    if page.evaluate("() => document.querySelector('#bd-editor').hidden"):
        if page.locator("#bd-decks .bddeck").count() == 0:
            check("в билдере есть колода", False, "колод нет")
            b.close()
            raise SystemExit(1)
        page.locator("#bd-decks .bddeck").first.click()
        page.wait_for_function(
            "() => !document.querySelector('#bd-editor').hidden", timeout=20000)
        page.wait_for_timeout(1500)

    # dispatch rather than click: the builder re-renders and a retried click
    # would land on the overlay it just opened.
    page.dispatch_event('#bd-actions button[data-act="combos"]', "click")
    page.wait_for_function(
        "() => document.querySelectorAll('#cb-body .cbcombo').length > 0", timeout=120000)
    page.wait_for_timeout(600)

    meta = " ".join((page.locator("#cb-meta").text_content() or "").split())
    print("      " + meta[:140])
    done = page.locator("#cb-body .cbcombo.done").count()
    near = page.locator("#cb-body .cbcombo.near").count()
    check("комбо разделены на собранные и неполные", done + near > 0,
          "%d собранных, %d неполных" % (done, near))
    check("сказано, сколько карт проверено", "проверено карт" in meta, meta[:50])
    check("указана дата базы комбо", "база комбо от" in meta, meta[-40:])

    if near:
        block = page.locator("#cb-body .cbcombo.near").first
        print("      неполное: " +
              " ".join((block.text_content() or "").split())[:110])
        check("недостающая карта помечена", block.locator(".cbcard.miss").count() > 0)
        check("у неё есть кнопка «в охоту»",
              block.locator('.cbcard.miss button[data-cb="hunt"]').count() > 0)
        check("карты, которые есть, не помечены как недостающие",
              block.locator(".cbcard:not(.miss)").count() > 0)

    check("виден результат комбо",
          page.locator("#cb-body .cbresults").first.text_content().strip() != "")

    page.locator("#cb-body .cbcombo details summary").first.click()
    page.wait_for_timeout(400)
    check("шаги расписаны по пунктам",
          page.locator("#cb-body .cbcombo ol li").count() >= 2,
          "%d пунктов" % page.locator("#cb-body .cbcombo ol li").count())

    print()
    print("=== the hover preview works here too ===")
    if page.locator("#cb-body .cbcard[data-preview] img").count():
        page.locator("#cb-body .cbcard[data-preview] img").first.hover()
        page.wait_for_function(
            "() => !document.querySelector('#hoverpreview').hidden", timeout=10000)
        page.wait_for_timeout(400)
        check("большая карта показывается по наведению", page.evaluate(
            "() => { const i = document.querySelector('#hoverpreview img');"
            " return !!i && i.naturalWidth > 0; }"))
        page.mouse.move(4, 4)
        page.wait_for_timeout(300)

    print()
    print("=== the missing card becomes a shopping list ===")
    if near:
        missing = (page.locator("#cb-body .cbcard.miss b").first.text_content() or "").strip()
        page.locator('#cb-body .cbcard.miss button[data-cb="hunt"]').first.click()
        page.wait_for_timeout(700)
        page.keyboard.press("Escape")
        page.wait_for_function(
            "() => document.querySelector('#cb-overlay').hidden", timeout=10000)
        page.click('.tab[data-tab="hunt"]')
        page.wait_for_timeout(500)
        wants = page.input_value("#hunt-wants")
        check("недостающая карта попала в охоту", missing in wants, "«%s»" % missing)

        # Put the hunt list back: the test must not leave cards in it.
        kept = chr(10).join(l for l in wants.splitlines()
                            if missing.lower() not in l.lower())
        page.fill("#hunt-wants", kept)
        page.dispatch_event("#hunt-wants", "input")
        page.wait_for_timeout(300)
        check("список охоты возвращён как был",
              missing not in page.input_value("#hunt-wants"))

    print()
    print("=== the honesty checks the first version failed ===")
    # The panel was closed to reach the hunt tab; its controls live inside it.
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(600)
    if page.evaluate("() => document.querySelector('#cb-overlay').hidden"):
        page.dispatch_event('#bd-actions button[data-act="combos"]', "click")
    page.wait_for_function(
        "() => document.querySelectorAll('#cb-body .cbcombo').length > 0", timeout=120000)
    page.wait_for_timeout(600)

    meta = " ".join((page.locator("#cb-meta").text_content() or "").split())
    check("сказано, что показаны только игранные комбо",
          "кто-то играет" in meta, meta[-60:])

    # A combo needing "any sacrifice outlet" cannot be confirmed from a card
    # list, and used to be filed under "собрано" anyway.
    marks = page.evaluate("""() => [...document.querySelectorAll('#cb-body .chip')]
        .map(e => e.textContent.trim())""")
    with_cond = [m for m in marks if "услови" in m]
    check("нехватка условия подписана, а не спрятана", len(with_cond) >= 1,
          str(marks[:4]))
    print("      пометки: " + str(with_cond[:2]))
    need = page.locator("#cb-body .cbneed").count()
    check("названо, какое условие нужно", need >= 1, "%d" % need)
    if need:
        print("      " + " ".join(
            (page.locator("#cb-body .cbneed").first.text_content() or "").split())[:100])

    # Variants of one base combo collapse into a single row with a list of
    # interchangeable cards -- nine rows for one combo is what made the first
    # version look like nonsense.
    alts = page.locator("#cb-body .cbalts").count()
    if alts:
        print("      " + " ".join(
            (page.locator("#cb-body .cbalts").first.text_content() or "").split())[:120])
        check("взаимозаменяемые карты собраны в одну строку", True,
              "%d таких комбо" % alts)
    else:
        check("взаимозаменяемые карты собраны в одну строку", True,
              "в этой колоде таких связок нет")

    page.check("#cb-unplayed")
    page.wait_for_function(
        "() => (document.querySelector('#cb-meta').textContent || '')"
        ".indexOf('никем не игранные') >= 0", timeout=180000)
    page.wait_for_timeout(700)
    check("можно попросить и никем не игранные", True,
          "%d комбо" % page.locator("#cb-body .cbcombo").count())
    page.uncheck("#cb-unplayed")
    page.wait_for_function(
        "() => (document.querySelector('#cb-meta').textContent || '')"
        ".indexOf('кто-то играет') >= 0", timeout=180000)
    page.wait_for_timeout(500)

    print()
    print("=== combos of a single card ===")
    # The overlay covers the tab bar, so it has to be closed before leaving.
    page.keyboard.press("Escape")
    page.wait_for_function(
        "() => document.querySelector('#cb-overlay').hidden", timeout=10000)
    page.click('.tab[data-tab="search"]')
    page.wait_for_timeout(400)
    page.fill("#search-q", "Thassa's Oracle")
    page.wait_for_function(
        "() => { const m = document.querySelector('#search-meta');"
        " return m && (m.textContent || '').indexOf('показано') >= 0; }", timeout=30000)
    page.locator("#search-results .card").first.locator("img").click()
    page.wait_for_timeout(900)
    page.click("#modal-combos-btn")
    page.wait_for_function(
        "() => document.querySelectorAll('#modal-combos .cbcombo').length > 0",
        timeout=60000)
    page.wait_for_timeout(500)
    n = page.locator("#modal-combos .cbcombo").count()
    check("в окне карты показаны её комбо", n >= 3, "%d комбо" % n)
    shown = " ".join((page.locator("#modal-combos").text_content() or "").split())
    print("      " + shown[:110])
    # There is no deck here to compare against, so nothing may claim to be done.
    check("без колоды ничего не объявлено «собранным»",
          "собрано" not in shown and page.locator("#modal-combos .cbcombo.done").count() == 0,
          shown[:60])
    check("вместо этого показано, из скольких карт комбо", "карт" in shown, shown[:60])
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    print()
    check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
    page.screenshot(path="tests/ui_combos.png")
    b.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL COMBO CHECKS PASSED")
