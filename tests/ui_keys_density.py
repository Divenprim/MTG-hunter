"""Browser check: walking results with the keyboard, and deck list density.

Two asks: arrows over the search grid with Enter to open, and the same density
control for the builder that the card search got.

The bug this test caught while it was being written: the keyboard cursor calls
scrollIntoView, whose scroll event was dismissing the preview -- so arrow keys
never showed a card at all. Hence the explicit check that the preview survives
a cursor move that scrolls the page.

Needs a running server and Chromium:

    .venv/Scripts/python.exe tests/ui_keys_density.py
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
VIEW = {"width": 1280, "height": 800}
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def cursor_state(page):
    return page.evaluate("""() => {
      const tiles = [...document.querySelectorAll('#search-results .card')];
      const i = tiles.findIndex(t => t.classList.contains('cursor'));
      const box = document.querySelector('#hoverpreview');
      const img = box.querySelector('img');
      return {
        i,
        name: i >= 0 ? tiles[i].querySelector('.cardname').textContent.trim() : '',
        open: !box.hidden,
        natural: img ? img.naturalWidth : 0,
        focused: document.activeElement ? (document.activeElement.id || '') : '',
        cursors: tiles.filter(t => t.classList.contains('cursor')).length,
      };
    }""")


with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_context(viewport=VIEW).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")

    print("=== arrows over the search grid ===")
    page.fill("#search-q", "goblin")
    page.wait_for_function(
        "() => { const m = document.querySelector('#search-meta');"
        " return m && (m.textContent || '').indexOf('показано') >= 0; }", timeout=30000)
    page.click('#search-density button[data-density="snug"]')
    page.wait_for_timeout(700)
    # The preview borrows the tile's own thumbnail for its first frame, so the
    # tiles have to have theirs before the keyboard can be judged.
    page.wait_for_function("""() => {
      const im = [...document.querySelectorAll('#search-results .card img')].slice(0, 12);
      return im.length > 8 && im.every(i => i.complete && i.naturalWidth > 0);
    }""", timeout=60000)
    page.wait_for_timeout(300)

    page.focus("#search-q")
    page.keyboard.press("ArrowDown")
    page.wait_for_timeout(600)
    st = cursor_state(page)
    check("↓ из поля запроса уводит в результаты", st["i"] == 0, str(st["i"]))
    check("поле отпускает фокус, иначе стрелки останутся в нём",
          st["focused"] != "search-q", st["focused"])

    page.keyboard.press("ArrowRight")
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(700)
    st = cursor_state(page)
    check("→ двигает курсор по одной карте", st["i"] == 2, str(st["i"]))
    check("курсор всегда один", st["cursors"] == 1, "%d" % st["cursors"])
    check("под курсором сама собой открывается карта",
          st["open"] and st["natural"] > 0, str(st))
    page.wait_for_function(
        """() => { const i = document.querySelector('#hoverpreview img');
             return i && i.src.indexOf('/normal/') >= 0 && i.naturalWidth > 400; }""",
        timeout=30000)
    check("и дорастает до полного размера", True, "дождались /normal/")
    print("      курсор на: " + st["name"])

    cols = page.evaluate(
        "() => getComputedStyle(document.querySelector('#search-results'))"
        ".gridTemplateColumns.split(' ').filter(x => x.trim()).length")
    page.keyboard.press("ArrowDown")
    page.wait_for_timeout(500)
    st = cursor_state(page)
    check("↓ идёт на строку ниже, а не на следующую карту", st["i"] == 2 + cols,
          "%d при %d колонках" % (st["i"], cols))

    print()
    print("=== the preview survives the scrolling the cursor itself causes ===")
    # Far enough down that the grid has to scroll to keep up.
    for _ in range(12):
        page.keyboard.press("ArrowDown")
    page.wait_for_timeout(1200)
    st = cursor_state(page)
    scrolled = page.evaluate("() => Math.round(window.scrollY)")
    check("страница действительно прокрутилась", scrolled > 100, "scrollY=%d" % scrolled)
    check("предпросмотр не закрылся от своей же прокрутки",
          st["open"] and st["natural"] > 0, str(st))
    check("и остался в пределах экрана", page.evaluate("""() => {
        const r = document.querySelector('#hoverpreview').getBoundingClientRect();
        return r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight;
      }"""))

    print()
    print("=== Enter, Home/End, Esc ===")
    page.keyboard.press("Home")
    page.wait_for_timeout(600)
    check("Home возвращает к первой карте", cursor_state(page)["i"] == 0)
    name = cursor_state(page)["name"]
    page.keyboard.press("Enter")
    page.wait_for_timeout(1300)
    check("Enter открывает карту под курсором",
          not page.evaluate("() => document.querySelector('#overlay').hidden"))
    opened = (page.locator("#modal-body h2").first.text_content() or "").strip()
    check("открылась именно она", opened == name, "«%s» вместо «%s»" % (opened, name))
    page.keyboard.press("Escape")
    page.wait_for_timeout(500)

    page.keyboard.press("ArrowUp")
    page.wait_for_timeout(500)
    st = cursor_state(page)
    check("↑ из первой строки возвращает в поле запроса", st["focused"] == "search-q",
          st["focused"])
    check("предпросмотр при этом закрыт", not st["open"])

    print()
    print("=== a new query drops the old cursor ===")
    page.fill("#search-q", "sol ring")
    page.wait_for_function(
        "() => { const m = document.querySelector('#search-meta');"
        " return m && (m.textContent || '').indexOf('показано') >= 0; }", timeout=30000)
    page.wait_for_timeout(800)
    st = cursor_state(page)
    check("курсор сброшен, а не показывает на исчезнувшую карту", st["i"] == -1, str(st["i"]))
    check("и предпросмотр закрыт", not st["open"])

    print()
    print("=== density in the builder ===")
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(900)
    if page.locator("#bd-cards .bdrow").count() == 0 and page.locator("#bd-decks .bddeck").count():
        page.locator("#bd-decks .bddeck").first.click()
        page.wait_for_timeout(2000)

    # Row density is measured in the list view; stacks is the default, so switch
    # first -- otherwise there are no rows to measure and the check misreports
    # it as "no deck".
    page.select_option("#bd-view", "rows")
    page.wait_for_timeout(600)

    if page.locator("#bd-cards .bdrow").count() == 0:
        check("в билдере есть колода для проверки", False, "нет ни одной колоды")
    else:
        page.wait_for_timeout(200)
        rows = {}
        for mode in ("tight", "snug", "roomy"):
            page.click('#bd-density button[data-bddensity="%s"]' % mode)
            page.wait_for_timeout(500)
            page.evaluate(
                "() => document.querySelector('#bd-cards').scrollIntoView({block: 'start'})")
            page.wait_for_timeout(400)
            rows[mode] = page.evaluate("""(vh) => {
              const rs = [...document.querySelectorAll('#bd-cards .bdrow')];
              const vis = rs.filter(r => { const b = r.getBoundingClientRect();
                return b.top >= 0 && b.bottom <= vh; });
              return {n: rs.length, vis: vis.length,
                      h: rs.length ? Math.round(rs[0].getBoundingClientRect().height) : 0};
            }""", VIEW["height"])
            print("      %-6s строка %dpx · целиком видно %d из %d"
                  % (mode, rows[mode]["h"], rows[mode]["vis"], rows[mode]["n"]))

        check("плотно — строк на экране больше",
              rows["tight"]["vis"] > rows["snug"]["vis"],
              "%d против %d" % (rows["tight"]["vis"], rows["snug"]["vis"]))
        check("крупно — меньше",
              rows["roomy"]["vis"] < rows["snug"]["vis"],
              "%d против %d" % (rows["roomy"]["vis"], rows["snug"]["vis"]))
        check("строка действительно ниже в крупном режиме",
              rows["roomy"]["h"] > rows["tight"]["h"],
              "%dpx против %dpx" % (rows["roomy"]["h"], rows["tight"]["h"]))

        page.select_option("#bd-view", "grid")
        page.wait_for_timeout(700)
        wide = {}
        for mode in ("tight", "roomy"):
            page.click('#bd-density button[data-bddensity="%s"]' % mode)
            page.wait_for_timeout(500)
            wide[mode] = page.evaluate(
                """() => { const g = document.querySelector('#bd-cards .gcard');
                  return g ? Math.round(g.getBoundingClientRect().width) : 0; }""")
        check("вид картинками тоже слушается плотности", wide["roomy"] > wide["tight"],
              "%dpx против %dpx" % (wide["roomy"], wide["tight"]))

        page.click('#bd-density button[data-bddensity="tight"]')
        page.wait_for_timeout(400)
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1300)
        check("выбор запоминается между запусками",
              page.evaluate("() => document.body.dataset.bddensity") == "tight",
              page.evaluate("() => document.body.dataset.bddensity"))

        print()
        print("=== the stats block folds away, so cards start near the top ===")
        page.click('.tab[data-tab="builder"]')
        page.wait_for_function(
            "() => document.querySelector('#panel-builder.active') !== null", timeout=20000)
        page.wait_for_timeout(1000)
        # A reload leaves no deck open, and the whole toolbar lives inside the
        # editor -- so the deck has to be opened again before anything in it can
        # be clicked.
        if page.evaluate("() => document.querySelector('#bd-editor').hidden"):
            page.locator("#bd-decks .bddeck").first.click()
            page.wait_for_function(
                "() => !document.querySelector('#bd-editor').hidden", timeout=20000)
            page.wait_for_timeout(1500)
        before = page.evaluate(
            """() => Math.round(document.querySelector('#bd-cards').getBoundingClientRect().top
                                + window.scrollY)""")
        page.click("#bd-stats-toggle")
        page.wait_for_timeout(600)
        after = page.evaluate(
            """() => Math.round(document.querySelector('#bd-cards').getBoundingClientRect().top
                                + window.scrollY)""")
        print("      список карт: y=%d → y=%d" % (before, after))
        check("свёрнутая статистика поднимает список карт", after < before - 150,
              "%d → %d" % (before, after))
        check("статистика скрыта именно атрибутом hidden",
              page.evaluate("() => document.querySelector('#bd-stats').hidden"))
        page.click("#bd-stats-toggle")
        page.wait_for_timeout(600)
        check("возвращается на место",
              not page.evaluate("() => document.querySelector('#bd-stats').hidden"))

        # Leave the panel as it was found.
        page.click('#bd-density button[data-bddensity="snug"]')
        page.select_option("#bd-view", "rows")
        page.wait_for_timeout(500)

    print()
    check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
    page.screenshot(path="tests/ui_keys_density.png")
    b.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL KEYBOARD/DENSITY CHECKS PASSED")
