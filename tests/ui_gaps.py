"""Browser check: «Чего не хватает» — и кнопка, которая кладёт карту в колоду.

Этот сценарий написан по следам стыдной истории. Панель разбора нехваток
проверялась разовым скриптом, который делал красивый снимок, — и на этом
проверка заканчивалась. Кнопку «+ в колоду» не нажимал никто. Она не работала
вообще: вызов уходил без заголовка `Content-Type`, сервер не мог разобрать
тело и отвечал 422. В таком виде это уехало в релиз и было объявлено главной
новинкой версии.

Отсюда правило, ради которого сценарий и существует: **снимок не нажимает
кнопку**. Если в разделе есть действие, его надо выполнить и проверить
результат на сервере, а не на экране.

Сценарий заводит свою колоду и удаляет её в конце.

    .venv/Scripts/python.exe tests/ui_gaps.py
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
DECK = "UI Нехватки"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def get(path):
    return json.load(urllib.request.urlopen(BASE + path))


# Бесцветная колода: предложения к ней заведомо бесцветные, и на них можно
# проверять кнопку, не гадая, попадёт ли карта в цвета.
CARDS = [
    {"name": "Kaldra Compleat", "quantity": 4, "section": "main"},
    {"name": "Bomat Courier", "quantity": 4, "section": "main"},
    {"name": "Ornithopter", "quantity": 4, "section": "main"},
    {"name": "Wastes", "quantity": 20, "section": "main"},
]

MAKE = """async ([name, cards]) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name === name)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
  const made = await fetch('/api/decks', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: name, format: 'modern'})}).then(r => r.json());
  await fetch('/api/decks/' + made.deck.id + '/cards', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cards: cards})});
  return made.deck.id;
}"""

DROP = """async (name) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name === name)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
}"""


def names_in(deck_id):
    deck = get("/api/decks/" + deck_id)
    deck = deck.get("deck") or deck
    return {(c.get("name") or "") for c in (deck.get("cards") or [])}


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1200}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")

    deck_id = page.evaluate(MAKE, [DECK, CARDS])
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(700)
    page.evaluate("(id) => bdOpen(id)", deck_id)
    page.wait_for_timeout(1500)

    print("=== раздел открывается ===")
    page.evaluate("""() => {
      document.querySelector('#bd-actions [data-act="gaps"]').click();
    }""")
    page.wait_for_selector(".gapwrap", timeout=60000)
    check("раздел посчитался", page.locator(".gapbox").count() > 0)

    print()
    print("=== у каждой нехватки видно, по чему посчитано ===")
    shown = page.evaluate(
        """() => [...document.querySelectorAll('.gapshort')].map((b) => ({
             title: (b.querySelector('h4') || {}).textContent || '',
             counted: b.textContent.indexOf('сосчитано') >= 0
                      || b.textContent.indexOf('ни одной карты') >= 0,
             offers: b.querySelectorAll('.gapadd').length}))""")
    check("нехватки найдены", len(shown) > 0, "%d штук" % len(shown))
    check("у каждой сказано, по чему посчитано",
          all(s["counted"] for s in shown),
          "; ".join(s["title"][:24] for s in shown if not s["counted"]))
    check("и предложены карты",
          any(s["offers"] for s in shown),
          "предложений: %s" % [s["offers"] for s in shown])

    print()
    print("=== кнопка «+ в колоду» ===")
    # Главное в этом сценарии. Проверяется не вид кнопки, а то, что карта
    # правда оказалась в колоде -- по ответу сервера, а не по экрану.
    before = names_in(deck_id)
    picked = page.evaluate(
        """() => { const b = document.querySelector('.gapadd');
                   return b ? b.dataset.add : null; }""")
    check("есть что добавить", bool(picked), str(picked))
    if picked:
        page.evaluate("""() => document.querySelector('.gapadd').click()""")
        page.wait_for_timeout(2500)
        after = names_in(deck_id)
        check("карта попала в колоду", picked in after,
              "было %d карт, стало %d" % (len(before), len(after)))
        check("и это именно та карта", picked not in before and picked in after,
              picked)

    print()
    print("=== панели разбора делят один слот ===")
    # Раньше каждая закрывала только себя, и они копились стопкой: нажал
    # «Разбор» -- видимо ничего не произошло, потому что панель открылась на
    # три тысячи пикселей ниже. Проверяется и то, что открыта ровно одна, и
    # то, что страница к ней прокрутилась.
    page.evaluate("""() => { window.scrollTo(0, 0);
      document.querySelector('#bd-actions [data-act="analysis"]').click(); }""")
    page.wait_for_timeout(2500)
    state = page.evaluate("""() => ({
        open: ['#bd-formats', '#bd-manabase', '#bd-analysis', '#bd-gaps']
                .filter((s) => { const e = document.querySelector(s);
                                 return e && !e.hidden; }),
        lit: [...document.querySelectorAll('#bd-actions button.on')]
                .map((b) => b.dataset.act),
        y: Math.round(window.scrollY)})""")
    check("открыта ровно одна панель", len(state["open"]) == 1,
          ", ".join(state["open"]))
    check("и это та, которую нажали", state["open"] == ["#bd-analysis"],
          str(state["open"]))
    check("кнопка подсвечена", state["lit"] == ["analysis"], str(state["lit"]))
    check("страница прокрутилась к панели", state["y"] > 0,
          "прокрутка %d" % state["y"])

    print()
    print("=== цветная мана, спрятанная в способности ===")
    pips = page.evaluate("""() => {
        const box = document.querySelector('.gapbox');
        return box ? box.textContent : '';
    }""")
    check("Bomat Courier назван вместе со своим цветом",
          "Bomat Courier" in pips and "R" in pips, pips[:70])

    page.evaluate(DROP, DECK)
    print()
    check("нет ошибок в консоли", not errors, "; ".join(errors[:2]))
    browser.close()

print()
if FAIL:
    print("НЕ СОШЛОСЬ: " + "; ".join(FAIL))
    raise SystemExit(1)
print("ИТОГ: всё хорошо")
