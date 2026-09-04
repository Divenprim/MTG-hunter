"""Browser check: commander suggestions.

"предложка карт по командиру" -- pick a commander, see what people actually
play with it, and act on it: into the deck, into the hunt, or find out what it
costs in roubles.

The panel is only useful if the local joins are visible, so the checks are about
those: what is already in the deck, what you own, and the rouble price. It also
guards the thing that would be rude rather than merely broken -- no topdeck
request may happen just from opening the panel.

Needs a running server and Chromium:

    .venv/Scripts/python.exe tests/ui_recommend.py
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
COMMANDER = "The Ur-Dragon"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def reopen_panel(page):
    """Open the suggestions panel again.

    A plain click can race: the builder panel re-renders after a tab switch,
    Playwright retries the click, and by then the overlay it just opened is
    what blocks it. Dispatching the event avoids the retry entirely.
    """
    if page.evaluate("() => document.querySelector('#rec-overlay').hidden"):
        page.dispatch_event('#bd-actions button[data-act="recommend"]', "click")
    page.wait_for_function(
        "() => !document.querySelector('#rec-overlay').hidden", timeout=20000)
    page.wait_for_timeout(500)


def open_builder(page):
    page.click('.tab[data-tab="builder"]')
    page.wait_for_function(
        "() => document.querySelector('#panel-builder.active') !== null", timeout=20000)
    page.wait_for_timeout(900)
    if page.evaluate("() => document.querySelector('#bd-editor').hidden"):
        if page.locator("#bd-decks .bddeck").count() == 0:
            return False
        page.locator("#bd-decks .bddeck").first.click()
        page.wait_for_function(
            "() => !document.querySelector('#bd-editor').hidden", timeout=20000)
        page.wait_for_timeout(1500)
    return True


with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_context(viewport={"width": 1400, "height": 950}).new_page()
    errors = []
    requests = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("request", lambda r: requests.append(r.url))
    page.goto(BASE, wait_until="networkidle")

    if not open_builder(page):
        check("в билдере есть колода для проверки", False, "нет ни одной колоды")
        raise SystemExit(1)

    print("=== opening the panel ===")
    page.click('#bd-actions button[data-act="recommend"]')
    page.wait_for_timeout(800)
    check("окно открылось", not page.evaluate("() => document.querySelector('#rec-overlay').hidden"))

    # This deck has no commander, so the panel must explain instead of asking
    # the server a question it cannot answer.
    body = " ".join((page.locator("#rec-body").text_content() or "").split())
    if "не выбран командир" in body:
        check("без командира окно объясняет, что делать", True)
        check("и не отправляет обречённый запрос",
              not any("/api/recommend" in u for u in requests),
              "запрос всё же ушёл")
    else:
        check("окно что-то показало", bool(body), body[:60])

    print()
    print("=== suggestions for a commander ===")
    before = len(requests)
    page.fill("#rec-commander", COMMANDER)
    page.click("#rec-run")
    page.wait_for_function(
        "() => document.querySelectorAll('#rec-body .recrow').length > 0", timeout=180000)
    page.wait_for_timeout(800)

    meta = " ".join((page.locator("#rec-meta").text_content() or "").split())
    print("      " + meta[:150])
    rows = page.locator("#rec-body .recrow").count()
    groups = page.locator("#rec-body .recgroup").count()
    check("есть разделы и строки", groups >= 5 and rows > 50,
          "%d разделов, %d строк" % (groups, rows))
    check("сказано, на скольких колодах это основано", "колодам с EDHREC" in meta,
          meta[:60])

    # Nothing here may talk to topdeck: 250 cards at 1.5s would be minutes.
    asked_topdeck = [u for u in requests[before:] if "/api/offers" in u or "/api/prices" in u]
    check("предложка не трогает topdeck сама", not asked_topdeck,
          "; ".join(asked_topdeck[:2]))

    print()
    print("=== the numbers a builder reads ===")
    first = page.locator("#rec-body .recrow").first
    text = " ".join((first.text_content() or "").split())
    print("      первая строка: " + text[:110])
    check("видна доля колод", "%" in text, text[:60])
    check("есть шкала доли", first.locator(".share .bar i").count() > 0)
    check("есть кнопки «в колоду» и «в охоту»",
          first.locator('button[data-rec="deck"]').count() > 0
          and first.locator('button[data-rec="hunt"]').count() > 0)

    print()
    print("=== filters and sorting ===")
    all_rows = page.locator("#rec-body .recrow").count()
    page.select_option("#rec-min-share", "0.5")
    page.wait_for_timeout(500)
    half = page.locator("#rec-body .recrow").count()
    check("фильтр по доле колод сужает список", 0 < half < all_rows,
          "%d -> %d" % (all_rows, half))

    shares = page.evaluate("""() => [...document.querySelectorAll('#rec-body .recrow .share b')]
        .map(e => parseInt(e.textContent) || 0)""")
    check("при фильтре «в половине колод» ниже 50% ничего не осталось",
          all(x >= 50 for x in shares), str(sorted(shares)[:5]))

    page.select_option("#rec-sort", "share")
    page.wait_for_timeout(500)
    order = page.evaluate("""() => {
      const g = document.querySelector('#rec-body .recgroup');
      return [...g.querySelectorAll('.recrow .share b')].map(e => parseInt(e.textContent) || 0);
    }""")
    check("сортировка по доле действительно упорядочивает",
          order == sorted(order, reverse=True), str(order[:6]))

    page.select_option("#rec-sort", "edhrec")
    page.select_option("#rec-min-share", "0")
    page.wait_for_timeout(500)

    print()
    print("=== hover preview works here too ===")
    page.locator("#rec-body .recrow img[data-preview]").first.hover()
    page.wait_for_function(
        "() => !document.querySelector('#hoverpreview').hidden", timeout=10000)
    page.wait_for_timeout(500)
    check("большая карта показывается по наведению", page.evaluate(
        "() => { const i = document.querySelector('#hoverpreview img');"
        " return !!i && i.naturalWidth > 0; }"))
    page.mouse.move(5, 5)
    page.wait_for_timeout(300)

    print()
    print("=== into the hunt, and cleaning up after ourselves ===")
    name = page.locator("#rec-body .recrow").first.get_attribute("data-name") or ""
    page.locator("#rec-body .recrow").first.locator('button[data-rec="hunt"]').click()
    page.wait_for_timeout(700)
    page.keyboard.press("Escape")
    page.wait_for_timeout(400)
    page.click('.tab[data-tab="hunt"]')
    page.wait_for_timeout(500)
    wants = page.input_value("#hunt-wants")
    check("карта из предложки попала в охоту", name in wants, "«%s»" % name)

    kept = chr(10).join(l for l in wants.splitlines() if name.lower() not in l.lower())
    page.fill("#hunt-wants", kept)
    page.dispatch_event("#hunt-wants", "input")
    page.wait_for_timeout(300)
    check("список охоты возвращён как был",
          name not in page.input_value("#hunt-wants"))

    print()
    print("=== rouble prices, on demand ===")
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(600)
    reopen_panel(page)
    # One card only: each name is a polite 1.5s request to topdeck, and a test
    # has no business generating traffic for the sake of a bigger number.
    # Sol Ring, because it is genuinely always on sale -- picking whichever card
    # happens to lack a price can land on one nobody in Russia is selling, and
    # then "no price" is the correct answer and proves nothing.
    picked = page.evaluate("""() => {
      const rows = [...document.querySelectorAll('#rec-body .recrow')];
      const row = rows.find(r => r.dataset.name === 'Sol Ring') || rows[0];
      if (!row) return null;
      row.querySelector('input').click();
      return row.dataset.name;
    }""")
    if not picked:
        check("есть карта, которой можно спросить цену", False, "строк нет")
    else:
        print("      спрашиваю цену: " + picked)
        page.click("#rec-prices-picked")
        # Wait for the request to FINISH, not for a price to appear: a card
        # nobody sells legitimately comes back without one.
        page.wait_for_function(
            "() => !document.querySelector('#rec-prices-picked').disabled",
            timeout=180000)
        page.wait_for_timeout(600)
        shown = page.evaluate("""(name) => {
          const row = [...document.querySelectorAll('#rec-body .recrow')]
            .find(r => r.dataset.name === name);
          return row ? (row.querySelector('.rub').textContent || '').trim() : '';
        }""", picked)
        print("      получено: " + (shown or "(строка исчезла)"))
        if picked == "Sol Ring":
            check("цена в рублях подставилась в строку", "₽" in shown, shown)
        else:
            check("запрос цен завершился без ошибки", True,
                  "«%s»: %s" % (picked, shown))

        page.select_option("#rec-sort", "rub")
        page.wait_for_timeout(500)
        order = page.evaluate("""() => {
          const g = document.querySelector('#rec-body .recgroup');
          return [...g.querySelectorAll('.recrow .rub')].map(e => (e.textContent || '').trim());
        }""")
        if any("₽" in x for x in order):
            check("сортировка «дешевле в рублях» ставит известные цены выше прочерков",
                  "₽" in order[0], str(order[:3]))
        else:
            check("сортировка «дешевле в рублях» не падает без цен", True,
                  "цен в этой группе нет")
        page.select_option("#rec-sort", "edhrec")
        page.wait_for_timeout(300)

    print()
    print("=== the cache means the second open is instant ===")
    # The overlay covers the tab bar, so it has to go before switching tabs.
    page.keyboard.press("Escape")
    page.wait_for_function(
        "() => document.querySelector('#rec-overlay').hidden", timeout=10000)
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(600)
    reopen_panel(page)
    page.fill("#rec-commander", COMMANDER)
    started = page.evaluate("() => performance.now()")
    page.click("#rec-run")
    page.wait_for_function(
        "() => document.querySelectorAll('#rec-body .recrow').length > 0", timeout=60000)
    took = page.evaluate("(t) => performance.now() - t", started)
    check("повторный запрос быстрый (кеш на диске)", took < 4000, "%d мс" % took)
    meta = " ".join((page.locator("#rec-meta").text_content() or "").split())
    check("и честно сказано, что данные из кеша", "из кеша" in meta, meta[:80])

    print()
    check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
    page.screenshot(path="tests/ui_recommend.png")
    b.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL SUGGESTION CHECKS PASSED")
