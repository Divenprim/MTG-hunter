"""Browser check: плейтест -- рука, поле, тапы, розыгрыши.

Просьба была «давай плейтест добавим с рукой, колодой, тапами и розыгрышами,
ну прямо как в archidekt». Голдфишинг рядом отвечает на другой вопрос -- он
про тысячу раздач и проценты. Здесь одна партия, которую человек играет
руками.

Проверяется то, что делает эту партию непротиворечивой: карта не размножается
и не пропадает при переходах между зонами, тап и новый ход работают, «отменить»
действительно возвращает предыдущее состояние.

Сценарий ничего не меняет в колодах: он только раздаёт и двигает карты в
браузере.

    .venv/Scripts/python.exe tests/ui_playtest.py
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = "http://127.0.0.1:8765"
DECK = "UI Плейтест"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def get(path):
    return json.load(urllib.request.urlopen(BASE + path))


SETUP = """async (name) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name === name)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
  const made = await fetch('/api/decks', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: name, format: 'modern'})}).then(r => r.json());
  await fetch('/api/decks/' + made.deck.id + '/cards', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cards: [
      {name: 'Forest', quantity: 24, section: 'main'},
      {name: 'Fog', quantity: 20, section: 'main'},
      {name: 'Arboreal Grazer', quantity: 16, section: 'main'}]})});
  return made.deck.id;
}"""

CLEAN = """async (name) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name === name)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
}"""

COUNTS = """() => ({
  hand: ptState.zones.hand.length,
  field: ptState.zones.field.length,
  grave: ptState.zones.grave.length,
  exile: ptState.zones.exile.length,
  library: ptState.zones.library.length,
  turn: ptState.turn,
  life: ptState.life,
  total: Object.values(ptState.zones).reduce((n, z) => n + z.length, 0),
  tapped: ptState.zones.field.filter(c => c.tapped).length,
  dom: document.querySelectorAll('.pthand .ptcard').length,
})"""

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1150}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")
    deck_id = page.evaluate(SETUP, DECK)

    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(700)
    page.evaluate("(id) => bdOpen(id)", deck_id)
    page.wait_for_timeout(1500)

    print("=== раздача ===")
    page.evaluate("""() => {
      document.querySelector('#bd-actions [data-act="playtest"]').click();
    }""")
    page.wait_for_selector("#pt-body .pthand .ptcard", timeout=60000)
    st = page.evaluate(COUNTS)
    check("в руке семь карт", st["hand"] == 7, str(st["hand"]))
    check("и столько же на экране", st["dom"] == 7, str(st["dom"]))
    check("в библиотеке остальные 53", st["library"] == 53, str(st["library"]))
    check("карт всего ровно 60", st["total"] == 60, str(st["total"]))

    print()
    print("=== розыгрыш и тап ===")
    page.evaluate("""() => document.querySelector('.pthand .ptcard').click()""")
    page.wait_for_function("() => ptState.zones.field.length === 1", timeout=20000)
    st = page.evaluate(COUNTS)
    check("карта из руки легла на поле",
          st["field"] == 1 and st["hand"] == 6,
          "поле %d, рука %d" % (st["field"], st["hand"]))
    check("и ниоткуда не взялась лишняя", st["total"] == 60, str(st["total"]))

    page.evaluate("""() => document.querySelector('.ptfield .ptcard').click()""")
    page.wait_for_function("""() => ptState.zones.field.some(c => c.tapped)""",
                           timeout=20000)
    check("нажатие по карте на поле тапает её", True)
    check("и это видно", page.locator(".ptfield .ptcard.tapped").count() == 1)
    page.evaluate("""() => document.querySelector('.ptfield .ptcard').click()""")
    page.wait_for_function("""() => !ptState.zones.field.some(c => c.tapped)""",
                           timeout=20000)
    check("повторное нажатие разворачивает", True)

    print()
    print("=== новый ход ===")
    page.evaluate("""() => document.querySelector('.ptfield .ptcard').click()""")
    page.wait_for_timeout(300)
    before = page.evaluate(COUNTS)
    page.evaluate("""() => document.querySelector('[data-act="turn"]').click()""")
    page.wait_for_function("(n) => ptState.turn === n + 1", arg=before["turn"],
                           timeout=20000)
    st = page.evaluate(COUNTS)
    check("ход прибавился", st["turn"] == before["turn"] + 1)
    check("карта взята", st["hand"] == before["hand"] + 1,
          "было %d, стало %d" % (before["hand"], st["hand"]))
    check("всё развернулось", st["tapped"] == 0)
    check("карт по-прежнему 60", st["total"] == 60, str(st["total"]))

    print()
    print("=== отменить ===")
    page.evaluate("""() => document.querySelector('[data-act="undo"]').click()""")
    page.wait_for_function("(n) => ptState.turn === n", arg=before["turn"],
                           timeout=20000)
    back = page.evaluate(COUNTS)
    check("состояние вернулось целиком",
          back["turn"] == before["turn"] and back["hand"] == before["hand"]
          and back["tapped"] == before["tapped"],
          "ход %d, рука %d, тапнутых %d" % (back["turn"], back["hand"],
                                            back["tapped"]))

    print()
    print("=== меню карты на поле ===")
    page.evaluate("""() => {
      const card = document.querySelector('.ptfield .ptcard');
      card.dispatchEvent(new MouseEvent('contextmenu',
        {bubbles: true, cancelable: true, clientX: 400, clientY: 300}));
    }""")
    page.wait_for_selector(".cardmenu", timeout=20000)
    items = page.text_content(".cardmenu") or ""
    for want in ("В кладбище", "Изгнать", "Наверх колоды", "Вниз колоды",
                 "Открыть карту", "Жетон +1"):
        check("в меню есть «%s»" % want, want in items)

    page.evaluate("""() => {
      [...document.querySelectorAll('.cmitem')]
        .find(b => b.textContent.indexOf('В кладбище') === 0).click();
    }""")
    page.wait_for_function("() => ptState.zones.grave.length === 1", timeout=20000)
    st = page.evaluate(COUNTS)
    check("карта ушла в кладбище", st["grave"] == 1 and st["field"] == 0,
          "кладбище %d, поле %d" % (st["grave"], st["field"]))
    check("и опять ничего не пропало", st["total"] == 60, str(st["total"]))

    print()
    print("=== стопки и жизни ===")
    page.evaluate("""() => {
      document.querySelector('[data-open-pile="library"]').click();
    }""")
    page.wait_for_selector(".ptlook", timeout=20000)
    check("библиотеку можно посмотреть по порядку",
          page.locator(".ptlook .ptcard").count()
          == page.evaluate("() => ptState.zones.library.length"))
    page.evaluate("""() => document.querySelector('[data-closelook]').click()""")
    page.wait_for_timeout(300)
    check("просмотр закрывается", page.locator(".ptlook").count() == 0)

    life = page.evaluate("() => ptState.life")
    page.evaluate("""() => document.querySelector('[data-life="-1"]').click()""")
    page.wait_for_function("(n) => ptState.life === n - 1", arg=life, timeout=20000)
    check("жизни считаются", page.evaluate("() => ptState.life") == life - 1)

    print()
    print("=== мулиган ===")
    page.evaluate("""() => document.querySelector('[data-act="mulligan"]').click()""")
    page.wait_for_function("() => ptState.hand_size === 6", timeout=20000)
    st = page.evaluate(COUNTS)
    check("сдана новая рука из семи", st["hand"] == 7, str(st["hand"]))
    check("а убрать нужно одну — это лондонский мулиган",
          page.evaluate("() => ptState.hand_size") == 6)
    check("карт всё ещё 60", st["total"] == 60, str(st["total"]))

    print()
    print("=== уборка ===")
    page.evaluate("() => ptClose()")
    check("окно закрылось", page.is_hidden("#pt-overlay"))
    page.evaluate(CLEAN, DECK)
    check("своя колода удалена",
          not [d for d in get("/api/decks")["decks"] if d["name"] == DECK])
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
