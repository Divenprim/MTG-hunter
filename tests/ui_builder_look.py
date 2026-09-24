"""Browser check: билдер — командир, ширина колонок, качество картинок.

Три претензии, каждая своя проверка.

**Командира не назначить.** Единственным способом было удалить карту и
добавить заново, выбрав «в командиры» в выпадашке добавления. Теперь у каждой
карты стоит корона, прежний командир возвращается в колоду, и командиров
всегда ровно один.

**Колонки шире экрана.** Раньше ряд колонок уезжал в горизонтальную прокрутку.
Теперь они переносятся на следующую строку, и страница не становится шире окна.

**Картинки в низком качестве.** В стопках и плитках бралась картинка small
(146 px) и растягивалась на колонку в 240–280 px. Теперь берётся normal
(488 px).

Создаёт свою колоду и удаляет её за собой.

    .venv/Scripts/python.exe tests/ui_builder_look.py
"""

import os
from playwright.sync_api import sync_playwright

# Куда стучаться. По умолчанию -- обычный запуск; MTGH_UI_BASE нужна,
# когда на этом порту уже работает другая копия программы (скажем,
# запущенная по https для планшета).
BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
DECK_NAME = "UI Вид билдера"
CARDS = ["Tiamat", "Sol Ring", "Cultivate", "Lightning Bolt", "Counterspell",
         "Swords to Plowshares", "Birds of Paradise", "Dragon Tempest",
         "Arcane Signet", "Rhystic Study"]
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
      return (await fetch('/api/decks').then(x => x.json()))
        .decks.filter(d => d.name === name).length;
    }""", DECK_NAME)


def crown_click(page, card_name):
    """Нажать корону у карты по имени.

    Через dispatchEvent, а не click(): список перерисовывается после каждой
    правки, и обычный клик воюет с заменой узла под курсором.
    """
    page.evaluate("""(name) => {
      const row = [...document.querySelectorAll('#bd-cards .bdrow')]
        .find(r => r.textContent.includes(name));
      if (!row) throw new Error('нет строки: ' + name);
      const crown = row.querySelector('.crown');
      if (!crown) throw new Error('нет короны у: ' + name);
      crown.dispatchEvent(new MouseEvent('click', {bubbles: true}));
    }""", card_name)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")
    sweep(page)

    page.click('.tab[data-tab="builder"]')
    page.wait_for_function(
        "() => document.querySelector('#panel-builder.active') !== null", timeout=20000)
    page.wait_for_timeout(600)
    page.fill("#bd-newdeck", DECK_NAME)
    page.press("#bd-newdeck", "Enter")
    page.wait_for_function(
        "() => !document.querySelector('#bd-editor').hidden", timeout=20000)
    page.select_option("#bd-view", "rows")
    page.select_option("#bd-section", "main")
    for name in CARDS:
        page.fill("#bd-add", name)
        page.wait_for_function(
            "() => document.querySelectorAll('#bd-suggest .setrow').length > 0",
            timeout=30000)
        page.locator("#bd-suggest .setrow").first.click()
        page.wait_for_timeout(350)
    check("колода собрана", page.locator("#bd-cards .bdrow").count() == len(CARDS),
          "%d строк" % page.locator("#bd-cards .bdrow").count())

    print()
    print("=== командира можно назначить ===")
    check("корона стоит у каждой карты",
          page.locator("#bd-cards .crown").count() == len(CARDS))

    crown_click(page, "Tiamat")
    page.wait_for_function(
        "() => bdDeck.cards.some(c => c.section === 'commander')", timeout=20000)
    check("карта стала командиром",
          page.evaluate(
              "() => (bdDeck.cards.find(c => c.section === 'commander') || {}).name")
          == "Tiamat")
    check("и показана отдельной картой, а не колонкой",
          page.locator("#bd-cards .bdcommander .cmdcard").count() == 1)

    # Назначаем другого: прежний обязан вернуться в колоду, а не пропасть.
    page.wait_for_timeout(600)
    crown_click(page, "Sol Ring")
    page.wait_for_function(
        "() => (bdDeck.cards.find(c => c.section === 'commander') || {}).name === 'Sol Ring'",
        timeout=20000)
    check("командир всегда один",
          page.evaluate(
              "() => bdDeck.cards.filter(c => c.section === 'commander').length") == 1)
    check("прежний вернулся в колоду, а не пропал",
          page.evaluate(
              "() => (bdDeck.cards.find(c => c.name === 'Tiamat') || {}).section") == "main")

    # И обратно: командира можно снять.
    page.wait_for_timeout(600)
    page.locator("#bd-cards .bdcommander button[data-commander]").click()
    page.wait_for_function(
        "() => bdDeck.cards.every(c => c.section !== 'commander')", timeout=20000)
    check("командира можно вернуть в колоду",
          page.locator("#bd-cards .bdcommander").count() == 0)

    page.wait_for_timeout(500)
    crown_click(page, "Tiamat")
    page.wait_for_function(
        "() => (bdDeck.cards.find(c => c.section === 'commander') || {}).name === 'Tiamat'",
        timeout=20000)

    print()
    print("=== колонки не шире экрана ===")
    page.select_option("#bd-view", "columns")
    page.select_option("#bd-group", "type")
    page.wait_for_timeout(1200)
    geo = page.evaluate("""() => {
      const box = document.querySelector('#bd-cards');
      const cols = [...document.querySelectorAll('#bd-cards .bdcolumn')];
      const tops = new Set(cols.map(c => Math.round(c.getBoundingClientRect().top)));
      const right = cols.length
        ? Math.max(...cols.map(c => c.getBoundingClientRect().right)) : 0;
      return {
        columns: cols.length,
        rows: tops.size,
        boxRight: Math.round(box.getBoundingClientRect().right),
        colRight: Math.round(right),
        scrolls: box.scrollWidth > box.clientWidth + 2,
        pageWider: document.body.scrollWidth > window.innerWidth + 2,
      };
    }""")
    print("      %s" % geo)
    check("колонок больше одной", geo["columns"] > 1, str(geo["columns"]))
    check("горизонтальной прокрутки нет", geo["scrolls"] is False)
    check("страница не шире окна", geo["pageWider"] is False)
    check("колонки не вылезают за свою область",
          geo["colRight"] <= geo["boxRight"] + 1,
          "правый край %s против %s" % (geo["colRight"], geo["boxRight"]))
    check("не влезшие переносятся на следующий ряд", geo["rows"] >= 1,
          "рядов %s" % geo["rows"])

    print()
    print("=== картинки нормального качества ===")
    page.wait_for_function(
        """() => {
          const i = document.querySelector('#bd-cards .stackcard img');
          return i && i.complete && i.naturalWidth > 0;
        }""", timeout=30000)
    img = page.evaluate("""() => {
      const i = document.querySelector('#bd-cards .stackcard img');
      return {natural: i.naturalWidth,
              shown: Math.round(i.getBoundingClientRect().width),
              src: (i.currentSrc || i.src)};
    }""")
    print("      исходник %s px, отрисован %s px" % (img["natural"], img["shown"]))
    check("берётся normal, а не small", img["natural"] >= 488, str(img["natural"]))
    check("картинка не растянута сверх исходника",
          img["shown"] <= img["natural"], "%s > %s" % (img["shown"], img["natural"]))
    check("это картинка карты", "cards.scryfall.io" in img["src"], img["src"][:60])

    print()
    print("=== cleanup ===")
    left = sweep(page)
    check("тестовая колода удалена", left == 0, "осталось: %d" % left)

    print()
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    page.screenshot(path="tests/ui_builder_look.png")
    browser.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL BUILDER-LOOK CHECKS PASSED")
