"""Browser check: reading and handling search results without opening cards.

Two complaints drove this:

  * "чтобы когда наводишься на карточку, открывалась её большая версия" -- you
    had to click a card and open a modal just to read it;
  * "чтобы во время поиска карты что ты ищешь виднелись сразу, а не приходилось
    их листать" -- tiles were fixed at 180px, which on a 1280x800 laptop meant
    six cards fully visible out of six hundred results.

So: a hover preview, a density switch, a sticky search row, and quick actions on
the tile itself.

Needs a running server and Chromium:

    .venv/Scripts/python.exe tests/ui_search_ux.py
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
VIEW = {"width": 1280, "height": 800}
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def geometry(page):
    return page.evaluate(
        """(vh) => {
      const cards = Array.from(document.querySelectorAll('#search-results .card'));
      const fully = cards.filter(c => {
        const b = c.getBoundingClientRect();
        return b.top >= 0 && b.bottom <= vh;
      });
      const first = cards[0] ? cards[0].getBoundingClientRect() : null;
      return {
        n: fully.length,
        w: first ? Math.round(first.width) : 0,
        h: first ? Math.round(first.height) : 0,
        top: Math.round(document.querySelector('#search-results').getBoundingClientRect().top),
      };
    }""",
        VIEW["height"],
    )


with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_context(viewport=VIEW).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")

    page.fill("#search-q", "goblin")
    page.wait_for_function(
        "() => { const m = document.querySelector('#search-meta');"
        " return m && (m.textContent || '').indexOf('показано') >= 0; }", timeout=30000)
    page.wait_for_timeout(900)

    print("=== how much of the result set you can see at once ===")
    seen = {}
    for mode in ("tight", "snug", "roomy"):
        page.click('#search-density button[data-density="%s"]' % mode)
        page.wait_for_timeout(400)
        g = geometry(page)
        seen[mode] = g
        print("      %-6s плитка %dx%d · сетка с y=%d · целиком видно %d карт"
              % (mode, g["w"], g["h"], g["top"], g["n"]))

    # The old layout showed 6. Anything at or below that is a regression.
    check("средний режим показывает заметно больше прежних шести",
          seen["snug"]["n"] >= 14, "%d карт" % seen["snug"]["n"])
    check("плотный режим показывает ещё больше",
          seen["tight"]["n"] > seen["snug"]["n"] and seen["tight"]["n"] >= 28,
          "%d карт" % seen["tight"]["n"])
    check("крупный режим действительно крупнее",
          seen["roomy"]["w"] > seen["snug"]["w"] > seen["tight"]["w"],
          "%d / %d / %d" % (seen["roomy"]["w"], seen["snug"]["w"], seen["tight"]["w"]))
    check("сетка начинается выше, чем прежние 184px",
          seen["snug"]["top"] < 160, "y=%d" % seen["snug"]["top"])

    print()
    print("=== the choice is remembered ===")
    page.click('#search-density button[data-density="tight"]')
    page.wait_for_timeout(300)
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(900)
    check("после перезагрузки режим тот же",
          page.evaluate("() => document.body.dataset.density") == "tight",
          page.evaluate("() => document.body.dataset.density"))
    page.click('#search-density button[data-density="snug"]')
    page.wait_for_timeout(400)

    print()
    print("=== the search row does not scroll away ===")
    page.mouse.wheel(0, 1400)
    page.wait_for_timeout(400)
    bar = page.evaluate(
        "() => Math.round(document.querySelector('.panel.active .toolbar').getBoundingClientRect().top)")
    check("строка поиска остаётся на экране", 0 <= bar < 60, "top=%d" % bar)
    page.mouse.wheel(0, -1400)
    page.wait_for_timeout(400)

    print()
    print("=== hover preview ===")
    tile = page.locator("#search-results .card").nth(2)
    tile.hover()
    page.wait_for_function("() => !document.querySelector('#hoverpreview').hidden", timeout=8000)
    page.wait_for_timeout(600)
    box = page.evaluate("""() => {
      const b = document.querySelector('#hoverpreview');
      const r = b.getBoundingClientRect();
      const img = b.querySelector('img');
      const bar = document.querySelector('.panel.active .toolbar').getBoundingClientRect();
      return {
        w: Math.round(r.width), h: Math.round(r.height),
        inside: r.left >= 0 && r.top >= 0 && r.right <= innerWidth && r.bottom <= innerHeight,
        clearsBar: r.top >= bar.bottom,
        natural: img ? img.naturalWidth : 0,
        src: img ? img.src : "",
        events: getComputedStyle(b).pointerEvents,
      };
    }""")
    check("предпросмотр открывается по наведению, без клика", box["w"] > 200, "%dpx" % box["w"])
    # It goes up instantly with the thumbnail the tile already shows -- Scryfall's
    # full-size image can take seconds on a cold cache, and an empty frame or a
    # long nothing are both worse. Then it sharpens.
    check("сразу что-то видно, а не пустая рамка", box["natural"] > 0,
          "naturalWidth=%d" % box["natural"])
    check("рамка сразу в пропорциях карты",
          1.2 < round(box["h"] / max(1, box["w"]), 2) < 1.6,
          "%dx%d" % (box["w"], box["h"]))
    page.wait_for_function(
        """() => { const i = document.querySelector('#hoverpreview img');
             return i && i.src.indexOf('/normal/') >= 0 && i.naturalWidth > 400; }""",
        timeout=30000)
    check("затем подменяется на большую картинку", True, "дождались /normal/")
    check("окно целиком в пределах экрана", box["inside"], str(box))
    check("не накрывает строку поиска", box["clearsBar"])
    check("не перехватывает мышь", box["events"] == "none", box["events"])

    # Near the right edge it has to flip to the other side.
    page.locator("#search-results .card").nth(7).hover()
    page.wait_for_timeout(600)
    flip = page.evaluate("""() => { const r = document.querySelector('#hoverpreview').getBoundingClientRect();
      return {inside: r.left >= 0 && r.right <= innerWidth,
              left: Math.round(r.left), right: Math.round(r.right)}; }""")
    check("у правого края переворачивается влево", flip["inside"], str(flip))

    page.mouse.move(4, 4)
    page.wait_for_timeout(400)
    check("уводишь мышь — закрывается",
          page.evaluate("() => document.querySelector('#hoverpreview').hidden"))

    print()
    print("=== quick actions on the tile ===")
    tile = page.locator("#search-results .card").nth(2)
    name = (tile.locator(".cardname").text_content() or "").strip()
    tile.hover()
    page.wait_for_timeout(300)
    check("кнопки появляются при наведении", tile.locator(".q-hunt").is_visible())
    tile.locator(".q-hunt").click()
    page.wait_for_timeout(500)
    # The modal lives inside #overlay; the quick action must not open it.
    check("карточка не открылась вместо добавления",
          page.evaluate("() => document.querySelector('#overlay').hidden"))
    page.click('.tab[data-tab="hunt"]')
    page.wait_for_timeout(400)
    wants = page.input_value("#hunt-wants")
    check("карта попала в список охоты", name in wants, wants.strip()[:60])

    page.click('.tab[data-tab="search"]')
    page.wait_for_timeout(400)
    tile4 = page.locator("#search-results .card").nth(3)
    fav_name = (tile4.locator(".cardname").text_content() or "").strip()
    tile4.hover()
    page.wait_for_timeout(300)
    tile4.locator(".q-fav").click()
    page.wait_for_timeout(1000)
    check("карточка не открылась и от звёздочки",
          page.evaluate("() => document.querySelector('#overlay').hidden"))
    page.click('.tab[data-tab="favourites"]')
    page.wait_for_timeout(1200)
    favs = page.locator("#panel-favourites").text_content() or ""
    check("карта попала в избранное", fav_name in favs, "«%s» не нашлась" % fav_name)

    print()
    print("=== cleanup: the test must not leave cards in real user data ===")
    # This test adds to the actual favourites and hunt list, so it takes both
    # back. Leaving test cards in the user's "Хочу купить" is not acceptable.
    removed = page.evaluate("""async (name) => {
      const r = await fetch('/api/favourites').then(x => x.json());
      let done = false;
      for (const f of r.favourites.folders) {
        for (const c of f.cards) {
          if (c.name === name) {
            await fetch('/api/favourites/folders/' + f.id + '/cards/' + c.id,
                        {method: 'DELETE'});
            done = true;
          }
        }
      }
      return done;
    }""", fav_name)
    check("добавленная тестом карта убрана из избранного", removed,
          "«%s» осталась в избранном" % fav_name)

    page.click('.tab[data-tab="hunt"]')
    page.wait_for_timeout(300)
    lines = page.input_value("#hunt-wants").splitlines()
    kept = chr(10).join(l for l in lines if name.lower() not in l.lower())
    page.fill("#hunt-wants", kept)
    page.dispatch_event("#hunt-wants", "input")
    page.wait_for_timeout(300)
    check("список охоты вернулся без тестовой карты",
          name not in page.input_value("#hunt-wants"))
    page.click('.tab[data-tab="search"]')
    page.wait_for_timeout(300)

    print()
    # Clicking a tile still opens the card: the quick actions must not have
    # swallowed the ordinary click.
    page.click('.tab[data-tab="search"]')
    page.wait_for_timeout(400)
    page.locator("#search-results .card").nth(5).locator("img").click()
    page.wait_for_timeout(900)
    check("обычный клик по плитке по-прежнему открывает карту",
          not page.evaluate("() => document.querySelector('#overlay').hidden"))
    page.keyboard.press("Escape")
    page.wait_for_timeout(300)

    check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
    page.screenshot(path="tests/ui_search_ux.png")
    b.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL SEARCH-UX CHECKS PASSED")
