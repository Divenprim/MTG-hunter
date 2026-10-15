"""Browser check: карту можно положить в любую колоду, не уходя с экрана.

С его слов: «при открытии карты через поиск нельзя выбрать, куда её добавить;
нужно выходить, выбирать в других меню вкладки, колоды или ещё что, и только
потом возвращаться и нажимать добавить».

Замер подтвердил: при девяти заведённых колодах окно карты, открытое из
поиска, показывало **ноль** кнопок «в колоду». Строка появлялась только после
того, как колоду откроют в билдере, и только для этой одной колоды. Путь от
«вижу карту» до «она в нужной колоде» выходил в шесть действий: закрыть окно,
уйти в билдер, открыть колоду, вернуться в поиск, снова найти карту, снова её
открыть.

Проверяется ровно это: выбор есть сразу, он работает, и он помнится.

Сценарий заводит свою колоду «ПРОБА …» и убирает её за собой.

    .venv/Scripts/python.exe tests/ui_add_from_card.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
FAIL = []
DECK_A = "ПРОБА окно карты А"
DECK_B = "ПРОБА окно карты Б"


def ok(cond, label, extra=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", label,
                          "" if not extra else " — " + str(extra)))
    if not cond:
        FAIL.append(label)


def here(page, selector):
    """Есть ли элемент. Сценарий, который падает на отсутствующем выборе,
    проверяет одно расхождение из одиннадцати: остальные до прогона не
    доходят."""
    return page.evaluate("(s) => !!document.querySelector(s)", selector)


def value(page, selector):
    return page.evaluate(
        "(s) => { const e = document.querySelector(s); return e ? e.value : null; }",
        selector)


MAKE = """async (names) => {
  const out = [];
  for (const name of names) {
    const made = await fetch('/api/decks', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name, format: 'modern'})}).then(r => r.json());
    out.push(made.deck.id);
  }
  return out;
}"""

CLEAN = """async (names) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => names.indexOf(d.name) >= 0)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
}"""

CARDS = """async (id) => {
  const r = await fetch('/api/decks/' + id).then(x => x.json());
  return (r.deck.entries || r.deck.cards || []).map(
    (e) => e.quantity + '× ' + e.name + ' / ' + e.section);
}"""

print("=== положить карту, не уходя с экрана ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.evaluate(CLEAN, [DECK_A, DECK_B])
    ids = page.evaluate(MAKE, [DECK_A, DECK_B])
    page.wait_for_timeout(600)
    page.reload(wait_until="networkidle")
    page.wait_for_timeout(1200)

    # --------------------------------------------- выбор есть сразу
    page.click('.tab[data-tab="search"]')
    page.fill("#search-q", "Lightning Bolt")
    page.keyboard.press("Enter")
    page.wait_for_timeout(3000)
    page.evaluate("() => document.querySelector('#search-results .card').click()")
    page.wait_for_timeout(2500)

    ok(page.evaluate("() => (typeof bdDeck === 'undefined' || !bdDeck)"),
       "в билдере ничего не открыто — то самое положение")
    ok(page.evaluate("() => !!document.querySelector('#modal-deck')"),
       "выбор колоды есть прямо в окне карты")
    names = page.evaluate("""() => [...document.querySelectorAll('#modal-deck option')]
        .map((o) => o.textContent)""")
    ok(any(DECK_A in n for n in names) and any(DECK_B in n for n in names),
       "в выборе все колоды, а не одна", names[:4])
    ok(page.evaluate(
        "() => document.querySelectorAll('.add-deck').length") == 3,
       "три раздела: основная, сайдборд, под вопросом")

    # --------------------------------------------- кладёт туда, куда сказали
    picked = here(page, "#modal-deck")
    if picked:
        page.select_option("#modal-deck", ids[1])
        page.select_option("#modal-deck-qty", "4")
        page.evaluate("""() => {
          const b = document.querySelector('.add-deck[data-section=side]');
          if (b) b.click();
        }""")
        page.wait_for_timeout(1800)
    got = page.evaluate(CARDS, ids[1])
    ok(any("4×" in g and "Lightning Bolt" in g and "side" in g for g in got),
       "четыре копии легли в сайдборд выбранной колоды", got)
    first = page.evaluate(CARDS, ids[0])
    ok(not first, "в другую колоду ничего не попало", first)

    toast = page.evaluate(
        "() => (document.querySelector('.toast') || {}).textContent || ''")
    ok(DECK_B in toast, "сказано, в какую именно колоду положили", repr(toast))

    # --------------------------------------------- выбор помнится
    page.evaluate("() => closeModal()")
    page.wait_for_timeout(400)
    page.evaluate("() => document.querySelector('#search-results .card').click()")
    page.wait_for_timeout(2000)
    ok(value(page, "#modal-deck") == ids[1],
       "колода осталась выбранной — класть подряд можно не переспрашивая")
    ok(value(page, "#modal-deck-qty") == "4", "и количество тоже")

    # --------------------------- открытая в билдере колода становится главной
    page.evaluate("() => closeModal()")
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(1200)
    page.evaluate("(id) => bdOpen(id)", ids[0])
    page.wait_for_timeout(1800)
    page.click('.tab[data-tab="search"]')
    page.wait_for_timeout(600)
    page.evaluate("() => document.querySelector('#search-results .card').click()")
    page.wait_for_timeout(2000)
    ok(value(page, "#modal-deck") == ids[0],
       "открытая в билдере колода предлагается по умолчанию")

    ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))
    page.evaluate("() => closeModal()")
    page.evaluate(CLEAN, [DECK_A, DECK_B])
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
