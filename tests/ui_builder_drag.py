"""Browser check: перетаскивание карт между колонками билдера.

Жалоба была короткой: «драг анд дроп не работает в билдере». Он и правда не
работал -- ровно в том виде, в котором билдер открывается: колонки по типу
карт считаются из самих карт, перетаскивание там выключено, а объяснение
пряталось строчкой мелкого текста под колонками.

Теперь проверяется три вещи:
  * в раскладке «по типу» видна кнопка, которая переключает на категории;
  * в раскладке «по категориям» карты действительно перетаскиваются и
    категория сохраняется на сервере;
  * колода, которую ещё не раскладывали, показывает колонки по типам, а не
    одну кучу «без категории» -- тащить было некуда, и это выглядело поломкой.

Создаёт свою колоду и удаляет её за собой.

    .venv/Scripts/python.exe tests/ui_builder_drag.py
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
DECK_NAME = "UI Перетаскивание"
CARDS = ["Sol Ring", "Cultivate", "Lightning Bolt", "Birds of Paradise"]
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
    print("=== по типу: перетаскивания нет, но сказано куда идти ===")
    page.select_option("#bd-view", "columns")
    page.select_option("#bd-group", "type")
    page.wait_for_timeout(800)
    check("карты не помечены как перетаскиваемые",
          page.locator('#bd-cards .stackcard[draggable="true"]').count() == 0)
    check("подсказка предлагает кнопку, а не совет",
          page.locator("#bd-cards .colhint button[data-tocategory]").count() == 1)

    page.locator("#bd-cards .colhint button[data-tocategory]").click()
    page.wait_for_timeout(800)
    check("кнопка переключает на категории",
          page.eval_on_selector("#bd-group", "el => el.value") == "category")

    print()
    print("=== по категориям: колонки по типам, и они тянутся ===")
    columns = page.eval_on_selector_all(
        "#bd-cards .bdcolumn[data-group]", "els => els.map(e => e.dataset.group)")
    check("нераспределённая колода разложена по типам, а не в одну кучу",
          "без категории" not in columns, ", ".join(columns))
    check("карты помечены как перетаскиваемые",
          page.locator('#bd-cards .stackcard[draggable="true"]').count() == len(CARDS),
          "%d из %d" % (page.locator('#bd-cards .stackcard[draggable="true"]').count(),
                        len(CARDS)))

    # Тащим первую карту из её колонки в чужую.
    source = page.locator("#bd-cards .bdcolumn[data-group] .stackcard").first
    name = source.get_attribute("title")
    home = page.eval_on_selector_all(
        "#bd-cards .bdcolumn[data-group]",
        """(els, n) => {
             const own = els.find(e => e.querySelector('.stackcard[title="' + n + '"]'));
             return own ? own.dataset.group : '';
           }""", name)
    target_name = next(c for c in columns if c != home)
    target = page.locator('#bd-cards .bdcolumn[data-group="%s"]' % target_name)
    source.drag_to(target)
    page.wait_for_timeout(1200)

    filed = page.evaluate("""async (name) => {
      const r = await fetch('/api/decks/' + bdDeck.id).then(x => x.json());
      const card = (r.deck.cards || []).find(c => c.name === name);
      return card ? (card.category || '') : null;
    }""", name)
    check("карта переехала в другую колонку: %s -> %s" % (home, target_name),
          filed == target_name, "на сервере: %r" % filed)
    check("и это видно в колонке",
          page.locator('#bd-cards .bdcolumn[data-group="%s"] .stackcard[title="%s"]'
                       % (target_name, name)).count() == 1)

    print()
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))

    left = sweep(page)
    check("тестовая колода удалена", left == 0)
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
