"""Browser check: перетаскивание карт в билдере.

Жалоба была короткой: «драг анд дроп не работает». Поводов оказалось три.

**Раскладка по типам.** Билдер открывается с группировкой по типу карт, где
колонки считаются из самих карт и тащить их некуда, а объяснение пряталось
строчкой мелкого текста. Теперь там кнопка «разложить по категориям», а
колода, которую ещё не раскладывали, показывается колонками по типам, а не
одной кучей «без категории».

**Секции.** Карту из сайдборда в основную колоду перетащить было нельзя
вообще: приёмниками были только колонки категорий. Теперь приёмник -- каждая
секция, а на время перетаскивания внизу появляется полоса, чтобы можно было
бросить в сайдборд, которого в колоде пока нет.

**Айпад.** HTML5-перетаскивания в iOS Safari нет вовсе. Механика переписана на
pointer events, поэтому здесь движения указателя, а не drag_to().

Создаёт свою колоду и удаляет её за собой.

    .venv/Scripts/python.exe tests/ui_builder_drag.py
"""

import os
from playwright.sync_api import sync_playwright

# Куда стучаться. По умолчанию -- обычный запуск; MTGH_UI_BASE нужна,
# когда на этом порту уже работает другая копия программы (скажем,
# запущенная по https для планшета).
BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
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


def drag(page, source, target, grab_y=14, watch=None):
    """Потащить указателем: так же, как это делает рука с мышью.

    Возвращает, подсветилась ли цель в середине движения, -- подсветка и есть
    обещание, что бросок сработает.
    """
    src = page.locator(source).first
    src.scroll_into_view_if_needed()
    page.wait_for_timeout(150)
    sb = src.bounding_box()
    page.mouse.move(sb["x"] + sb["width"] / 2, sb["y"] + grab_y)
    page.mouse.down()
    # Порог: пока указатель не отъехал, это нажатие, а не перетаскивание.
    page.mouse.move(sb["x"] + sb["width"] / 2 + 25, sb["y"] + grab_y + 25, steps=5)
    page.wait_for_timeout(120)
    db = page.locator(target).first.bounding_box()
    page.mouse.move(db["x"] + db["width"] / 2, db["y"] + min(30, db["height"] / 2),
                    steps=10)
    page.wait_for_timeout(200)
    lit = page.locator(watch or target).first.evaluate(
        "el => el.classList.contains('dropover')")
    page.mouse.up()
    page.wait_for_timeout(1500)
    return lit


def sections(page):
    return page.evaluate(
        """() => bdDeck.cards.map(c => [(c.card && c.card.name) || c.name, c.section])""")


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
    check("колода собрана", page.locator("#bd-cards .bdrow").count() == len(CARDS))

    print()
    print("=== из основной колоды в сайдборд — через полосу секций ===")
    first = page.locator("#bd-cards .bdrow").first
    moved_name = first.get_attribute("title") or ""
    lit = drag(page, "#bd-cards .bdrow", '#bd-dock .dockzone[data-section="side"]')
    check("полоса секций подсветилась под курсором", lit)
    after = dict(sections(page))
    side = [n for n, s in after.items() if s == "side"]
    check("карта уехала в сайдборд", len(side) == 1, str(side))
    check("остальные остались на месте",
          sum(1 for s in after.values() if s == "main") == len(CARDS) - 1)

    print()
    print("=== и обратно: из сайдборда в основную колоду, броском в секцию ===")
    moved = side[0]
    lit = drag(page,
               '#bd-cards .bdgroup[data-section="side"] .bdrow',
               '#bd-cards .bdgroup[data-section="main"]')
    check("секция подсветилась как приёмник", lit)
    after = dict(sections(page))
    check("карта вернулась в основную колоду", after.get(moved) == "main",
          "%s: %s" % (moved, after.get(moved)))
    check("сайдборд опустел",
          not [n for n, s in after.items() if s == "side"])

    print()
    print("=== по типу: категорий не меняем, но говорим куда идти ===")
    page.select_option("#bd-view", "columns")
    page.select_option("#bd-group", "type")
    page.wait_for_timeout(800)
    check("подсказка предлагает кнопку, а не совет",
          page.locator("#bd-cards .colhint button[data-tocategory]").count() == 1)
    page.locator("#bd-cards .colhint button[data-tocategory]").click()
    page.wait_for_timeout(800)
    check("кнопка переключает на категории",
          page.eval_on_selector("#bd-group", "el => el.value") == "category")

    print()
    print("=== по категориям: колонки по типам, и карта переезжает ===")
    columns = page.eval_on_selector_all(
        "#bd-cards .bdcolumn[data-group]", "els => els.map(e => e.dataset.group)")
    check("нераспределённая колода разложена по типам, а не в одну кучу",
          "без категории" not in columns, ", ".join(columns))

    name = page.locator("#bd-cards .bdcolumn[data-group] .stackcard").first \
        .get_attribute("title")
    home = page.eval_on_selector_all(
        "#bd-cards .bdcolumn[data-group]",
        """(els, n) => {
             const own = els.find(e => e.querySelector('.stackcard[title="' + n + '"]'));
             return own ? own.dataset.group : '';
           }""", name)
    target_name = next(c for c in columns if c != home)
    lit = drag(page, "#bd-cards .bdcolumn[data-group] .stackcard",
               '#bd-cards .bdcolumn[data-group="%s"]' % target_name)
    check("колонка подсветилась под курсором", lit)

    filed = page.evaluate("""async (name) => {
      const r = await fetch('/api/decks/' + bdDeck.id).then(x => x.json());
      const card = (r.deck.cards || []).find(c => c.name === name);
      return card ? (card.category || '') : null;
    }""", name)
    check("карта переехала в другую колонку: %s -> %s" % (home, target_name),
          filed == target_name, "на сервере: %r" % filed)

    print()
    print("=== пальцем: удержание, потом перенос ===")
    # То же самое, но событиями pointer от «пальца»: на айпаде мыши нет,
    # а HTML5-перетаскивания в iOS Safari нет вовсе.
    touched = page.evaluate("""async () => {
      const card = document.querySelector('#bd-cards .stackcard');
      const box = card.getBoundingClientRect();
      const send = (type, x, y) => card.dispatchEvent(new PointerEvent(type, {
        pointerId: 7, pointerType: 'touch', isPrimary: true, bubbles: true,
        clientX: x, clientY: y, button: 0,
      }));
      const sendWin = (type, x, y) => window.dispatchEvent(new PointerEvent(type, {
        pointerId: 7, pointerType: 'touch', isPrimary: true, bubbles: true,
        clientX: x, clientY: y, button: 0,
      }));
      send('pointerdown', box.x + 20, box.y + 10);
      await new Promise(r => setTimeout(r, 400));     // удержание
      const started = document.body.classList.contains('dragging-now');
      const dock = document.querySelector('#bd-dock .dockzone[data-section="side"]');
      const d = dock.getBoundingClientRect();
      sendWin('pointermove', d.x + d.width / 2, d.y + d.height / 2);
      await new Promise(r => setTimeout(r, 100));
      const lit = dock.classList.contains('dropover');
      sendWin('pointerup', d.x + d.width / 2, d.y + d.height / 2);
      await new Promise(r => setTimeout(r, 1200));
      return {started: started, lit: lit};
    }""")
    check("удержание пальцем начинает перенос", touched["started"])
    check("и цель под пальцем подсвечивается", touched["lit"])
    after = dict(sections(page))
    check("карта переехала пальцем",
          len([n for n, s in after.items() if s == "side"]) == 1, str(after))

    print()
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    left = sweep(page)
    check("тестовая колода удалена", left == 0)
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
