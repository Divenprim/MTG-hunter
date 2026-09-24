"""Browser check: тема, отмена, клавиши, недавние запросы, профили, что нового.

Каждая проверка тут про одно и то же: удобство должно работать молча и не
трогать чужого. Поэтому отмена проверяется на своей папке избранного, клавиши
билдера — на своей колоде, и всё созданное удаляется в конце.

Needs a running server and Chromium:

    .venv/Scripts/python.exe tests/ui_comfort.py
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
DECK_NAME = "UI Удобство"
FOLDER_NAME = "UI Отмена"
QUERY = "s:clb t:dragon"
SAVED_NAME = "UI Сохранённый"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def sweep(page):
    """Убрать за собой: тестовая колода и тестовая папка избранного."""
    return page.evaluate("""async ([deck, folder]) => {
      const d = await fetch('/api/decks').then(x => x.json());
      for (const x of d.decks.filter(x => x.name === deck)) {
        await fetch('/api/decks/' + x.id, {method: 'DELETE'});
      }
      const f = await fetch('/api/favourites').then(x => x.json());
      const doc = f.favourites || f;
      for (const x of (doc.folders || []).filter(x => x.name === folder)) {
        await fetch('/api/favourites/folders/' + x.id, {method: 'DELETE'});
      }
      const after = await fetch('/api/decks').then(x => x.json());
      return after.decks.filter(x => x.name === deck).length;
    }""", [DECK_NAME, FOLDER_NAME])


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1150}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    # Один обработчик на все диалоги: prompt отвечаем именем, confirm просто
    # принимаем. Второй page.on("dialog") ломает первый.
    page.on("dialog", lambda d: d.accept(SAVED_NAME if d.type == "prompt" else ""))

    page.goto(BASE, wait_until="networkidle")
    sweep(page)

    print("=== что нового ===")
    # Свежий браузер: полоса должна показаться сама.
    page.wait_for_function(
        "() => !document.querySelector('#whatsnew').hidden", timeout=20000)
    news = " ".join((page.locator("#whatsnew").text_content() or "").split())
    check("полоса с новшествами показана", "что нового" in news.lower(), news[:80])
    # Сколько именно строк -- дело версии: у большой их пять, у починочной
    # бывает две. Проверяется, что полоса не пустая.
    check("и в ней есть строки", page.locator("#whatsnew li").count() > 0,
          "%d строк" % page.locator("#whatsnew li").count())
    page.locator("#whatsnew-close").click()
    page.wait_for_timeout(200)
    check("«Понятно» убирает её",
          page.evaluate("() => document.querySelector('#whatsnew').hidden") is True)
    check("и запоминает версию",
          bool(page.evaluate("() => store.get('seenVersion', '')")),
          str(page.evaluate("() => store.get('seenVersion', '')")))

    print()
    print("=== тема ===")
    check("по умолчанию тёмная — обновление не перекрашивает программу само",
          page.evaluate("() => document.documentElement.dataset.theme") == "dark")
    # Сравниваем явную тёмную с явной светлой: система на машине с тестом может
    # быть любой, и «как в системе» тогда ничего не докажет.
    page.locator('#theme-switch [data-theme="dark"]').click()
    page.wait_for_timeout(250)
    dark_bg = page.evaluate(
        "() => getComputedStyle(document.body).backgroundColor")
    page.locator('#theme-switch [data-theme="light"]').click()
    page.wait_for_timeout(250)
    light_bg = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    check("светлая тема применяется",
          page.evaluate("() => document.documentElement.dataset.theme") == "light"
          and light_bg != dark_bg, "%s -> %s" % (dark_bg, light_bg))
    page.locator('#theme-switch [data-theme="dark"]').click()
    page.wait_for_timeout(250)
    check("и обратно на тёмную",
          page.evaluate("() => getComputedStyle(document.body).backgroundColor") == dark_bg)
    page.locator('#theme-switch [data-theme="auto"]').click()
    page.wait_for_timeout(250)
    check("«как в системе» слушает систему",
          page.evaluate("""() => {
            const light = matchMedia('(prefers-color-scheme: light)').matches;
            const isLight = document.documentElement.classList.contains('sys-light');
            return light === isLight;
          }"""))
    page.locator('#theme-switch [data-theme="dark"]').click()
    page.reload(wait_until="networkidle")
    check("выбор темы помнится после перезагрузки",
          page.evaluate("() => document.documentElement.dataset.theme") == "dark")

    print()
    print("=== горячие клавиши ===")
    page.keyboard.press("?")
    page.wait_for_function(
        "() => !document.querySelector('#keys-overlay').hidden", timeout=10000)
    keys = " ".join((page.locator("#keys-body").text_content() or "").split())
    check("окно открывается по «?»", page.locator("#keys-body .keygroup").count() >= 3,
          "%d групп" % page.locator("#keys-body .keygroup").count())
    check("в нём есть раздел про билдер", "Билдер" in keys, keys[:70])
    page.keyboard.press("Escape")
    page.wait_for_timeout(200)
    check("и закрывается по Esc",
          page.evaluate("() => document.querySelector('#keys-overlay').hidden") is True)

    print()
    print("=== недавние и сохранённые запросы ===")
    page.click('.tab[data-tab="search"]')
    page.fill("#search-q", QUERY)
    page.press("#search-q", "Enter")
    page.wait_for_function(
        "() => document.querySelectorAll('#search-results .card').length > 0",
        timeout=30000)
    check("запрос запомнился",
          QUERY in (page.evaluate("() => store.get('recentQueries', [])") or []),
          str(page.evaluate("() => store.get('recentQueries', [])")))

    page.keyboard.press("Control+s")
    page.wait_for_timeout(400)
    saved = page.evaluate("() => store.get('savedQueries', [])") or []
    check("Ctrl+S сохраняет запрос под именем",
          any(x.get("name") == SAVED_NAME and x.get("q") == QUERY for x in saved),
          str(saved))

    page.fill("#search-q", "")
    page.click("#search-q")
    page.wait_for_function(
        "() => { const b = document.querySelector('#recent-queries');"
        " return b && !b.hidden; }", timeout=10000)
    rows = page.locator("#recent-queries .qrow").count()
    check("выпадашка показывает историю", rows > 0, "%d строк" % rows)
    page.locator("#recent-queries .qrow").first.click()
    page.wait_for_timeout(400)
    check("выбор подставляет запрос в строку",
          page.input_value("#search-q") == QUERY, page.input_value("#search-q"))

    print()
    print("=== профили фильтров охоты ===")
    page.click('.tab[data-tab="hunt"]')
    page.wait_for_timeout(400)
    page.check("#f-skip-ordered")
    page.select_option("#f-condition", "NM")
    page.fill("#f-maxprice", "500")
    page.locator("#hunt-profile-save").click()
    page.wait_for_timeout(400)
    check("профиль сохранён",
          page.locator('#hunt-profiles [data-profile]').count() == 1,
          "%d чипов" % page.locator('#hunt-profiles [data-profile]').count())

    page.uncheck("#f-skip-ordered")
    page.select_option("#f-condition", "")
    page.fill("#f-maxprice", "")
    page.locator('#hunt-profiles [data-profile]').first.click()
    page.wait_for_timeout(400)
    check("профиль возвращает поля",
          page.is_checked("#f-skip-ordered")
          and page.input_value("#f-condition") == "NM"
          and page.input_value("#f-maxprice") == "500",
          "skip=%s cond=%s max=%s" % (page.is_checked("#f-skip-ordered"),
                                      page.input_value("#f-condition"),
                                      page.input_value("#f-maxprice")))
    page.locator("#hunt-profiles [data-drop-profile]").first.click()
    page.wait_for_timeout(300)
    check("и убирается", page.locator('#hunt-profiles [data-profile]').count() == 0)

    print()
    print("=== отмена последнего действия ===")
    page.click('.tab[data-tab="favourites"]')
    page.wait_for_timeout(500)
    made = page.evaluate("""async (name) => {
      const r = await fetch('/api/favourites/folders',
        {method: 'POST', headers: {'Content-Type': 'application/json'},
         body: JSON.stringify({name: name})}).then(x => x.json());
      const doc = r.favourites || r;
      const f = (doc.folders || []).find(x => x.name === name);
      await fetch('/api/favourites/folders/' + f.id + '/cards',
        {method: 'POST', headers: {'Content-Type': 'application/json'},
         body: JSON.stringify({name: 'Sol Ring', quantity: 1})});
      return f.id;
    }""", FOLDER_NAME)
    page.reload(wait_until="networkidle")
    page.click('.tab[data-tab="favourites"]')
    page.wait_for_timeout(700)

    before = page.evaluate("() => (favDoc.folders || []).length")
    page.evaluate("(id) => { favCurrent = id; renderFavourites(); }", made)
    page.wait_for_timeout(300)
    page.locator("#fav-delete").click()
    page.wait_for_function(
        "() => document.querySelector('#toast .undo') !== null", timeout=20000)
    check("после удаления предложено отменить", True)
    check("папка действительно удалена",
          page.evaluate("() => (favDoc.folders || []).length") == before - 1,
          "было %d" % before)

    page.locator("#toast .undo").click()
    page.wait_for_function(
        "(n) => (favDoc.folders || []).length === n", arg=before, timeout=20000)
    names = page.evaluate("() => (favDoc.folders || []).map(f => f.name)")
    check("отмена вернула папку", FOLDER_NAME in names, str(names))
    cards = page.evaluate("""(name) => {
      const f = (favDoc.folders || []).find(x => x.name === name);
      return f ? f.cards.length : -1;
    }""", FOLDER_NAME)
    check("и её содержимое", cards == 1, "карт: %s" % cards)

    print()
    print("=== клавиши в билдере ===")
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(600)
    page.fill("#bd-newdeck", DECK_NAME)
    page.press("#bd-newdeck", "Enter")
    page.wait_for_function(
        "() => !document.querySelector('#bd-editor').hidden", timeout=20000)
    page.select_option("#bd-view", "rows")
    page.select_option("#bd-section", "main")
    for name in ("Sol Ring", "Cultivate", "Lightning Bolt"):
        page.fill("#bd-add", name)
        page.wait_for_function(
            "() => document.querySelectorAll('#bd-suggest .setrow').length > 0",
            timeout=30000)
        page.locator("#bd-suggest .setrow").first.click()
        page.wait_for_timeout(400)
    page.click("#bd-count")          # убрать фокус с поля ввода
    page.wait_for_timeout(200)

    page.keyboard.press("ArrowDown")
    page.wait_for_timeout(300)
    check("↓ ставит курсор на первую карту",
          page.locator("#bd-cards .kcursor").count() == 1,
          "%d" % page.locator("#bd-cards .kcursor").count())
    page.keyboard.press("ArrowDown")
    page.wait_for_timeout(200)
    check("и переходит к следующей",
          page.evaluate("() => bdCursor") == 1,
          "курсор %s" % page.evaluate("() => bdCursor"))

    # Количество читаем у карты под курсором: порядок на экране и порядок в
    # bdDeck.cards -- разные вещи, и индексом одно за другое не выдать.
    qty_before = page.evaluate("() => bdCursorCard().quantity")
    page.keyboard.press("+")
    page.wait_for_function(
        "(n) => bdCursorCard() && bdCursorCard().quantity === n + 1", arg=qty_before,
        timeout=20000)
    check("«+» увеличивает количество",
          page.evaluate("() => bdCursorCard().quantity") == qty_before + 1,
          "было %d" % qty_before)
    page.keyboard.press("-")
    page.wait_for_function(
        "(n) => bdCursorCard() && bdCursorCard().quantity === n",
        arg=qty_before, timeout=20000)
    check("«−» уменьшает обратно",
          page.evaluate("() => bdCursorCard().quantity") == qty_before)

    count_before = page.evaluate("() => bdDeck.cards.length")
    page.keyboard.press("Delete")
    page.wait_for_function(
        "(n) => bdDeck.cards.length === n - 1", arg=count_before, timeout=20000)
    check("Del убирает карту из колоды",
          page.evaluate("() => bdDeck.cards.length") == count_before - 1)

    page.keyboard.press("/")
    page.wait_for_timeout(250)
    check("«/» уводит в фильтр по колоде, а не в поиск карт",
          page.evaluate("() => document.activeElement.id") == "bd-filter",
          page.evaluate("() => document.activeElement.id"))

    print()
    print("=== cleanup ===")
    left = sweep(page)
    page.wait_for_timeout(300)
    check("тестовые колода и папка удалены", left == 0, "осталось: %d" % left)

    print()
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    page.screenshot(path="tests/ui_comfort.png")
    browser.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL COMFORT CHECKS PASSED")
