"""Browser check: меню по правой кнопке и количество в любом виде.

Жалоба: «как мне убрать один фог». В списке количество меняется кнопками в
строке, а в стопках и плитках -- ничем, при том что стопки это вид по
умолчанию. Теперь по правой кнопке открывается меню, где наверху счётчик: он
меняет количество и не закрывает меню, потому что убрать три копии из четырёх
-- это три нажатия подряд.

На планшете правой кнопки нет, а долгое нажатие занято перетаскиванием, поэтому
у карточки есть кнопка «…» -- то же меню.

Свою колоду сценарий создаёт и удаляет.

    .venv/Scripts/python.exe tests/ui_cardmenu.py
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = "http://127.0.0.1:8765"
DECK = "UI Меню"
CARDS = [("Fog", 4), ("Sol Ring", 1)]
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def get(path):
    return json.load(urllib.request.urlopen(BASE + path))


SETUP = """async (args) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name === args.name)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
  const made = await fetch('/api/decks', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: args.name, format: 'modern'})}).then(r => r.json());
  await fetch('/api/decks/' + made.deck.id + '/cards', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cards: args.cards.map(
      (c) => ({name: c[0], quantity: c[1], section: 'main'}))})});
  return made.deck.id;
}"""

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1400, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")
    deck_id = page.evaluate(SETUP, {"name": DECK, "cards": CARDS})

    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(600)
    page.evaluate("(id) => bdOpen(id)", deck_id)
    page.wait_for_timeout(1200)
    page.select_option("#bd-view", "columns")
    page.wait_for_selector("#bd-cards .stackcard", timeout=20000)

    def qty_of(name):
        return page.evaluate("""(name) => {
          const card = (bdDeck.cards || []).find(c => c.name === name);
          return card ? card.quantity : 0;
        }""", name)

    print("=== правой кнопкой по карте в стопке ===")
    page.click('#bd-cards .stackcard[title="Fog"]', button="right")
    page.wait_for_selector(".cardmenu", timeout=20000)
    check("меню открылось прямо в стопочном виде",
          page.locator(".cardmenu").count() == 1)
    # Имя в меню русское, если оно у карты есть: Fog -- «Туман».
    title = page.text_content(".cmtitle") or ""
    check("в заголовке карта и её секция",
          ("Fog" in title or "Туман" in title) and "Основная" in title,
          title[:40])
    check("счётчик показывает нынешнее количество",
          (page.text_content(".cmcount b") or "").strip() == "4")

    print()
    print("=== счётчик убирает по одной и не закрывается ===")
    page.click('.cmcount [data-step="-1"]')
    page.wait_for_function("""() => ((bdDeck.cards || [])
      .find(c => c.name === 'Fog') || {}).quantity === 3""", timeout=20000)
    check("одна копия убралась", qty_of("Fog") == 3)
    check("меню осталось открытым", page.locator(".cardmenu").count() == 1)
    check("и число в нём обновилось",
          (page.text_content(".cmcount b") or "").strip() == "3")

    page.click('.cmcount [data-step="-1"]')
    page.wait_for_function("""() => ((bdDeck.cards || [])
      .find(c => c.name === 'Fog') || {}).quantity === 2""", timeout=20000)
    page.click('.cmcount [data-step="1"]')
    page.wait_for_function("""() => ((bdDeck.cards || [])
      .find(c => c.name === 'Fog') || {}).quantity === 3""", timeout=20000)
    check("плюс тоже работает", qty_of("Fog") == 3)

    print()
    print("=== разовые действия закрывают меню ===")
    page.evaluate("""() => {
      [...document.querySelectorAll('.cmitem')]
        .find(b => b.textContent.indexOf('В «возможно»') === 0).click();
    }""")
    page.wait_for_function("""() => ((bdDeck.cards || [])
      .find(c => c.name === 'Fog') || {}).section === 'maybe'""", timeout=20000)
    check("карта ушла в «возможно»", True)
    check("меню закрылось", page.locator(".cardmenu").count() == 0)

    print()
    print("=== кнопка «…» вместо правой кнопки ===")
    page.select_option("#bd-view", "grid")
    page.wait_for_selector("#bd-cards .gcard", timeout=20000)
    page.evaluate("""() => {
      const card = [...document.querySelectorAll('#bd-cards .gcard')]
        .find(c => c.title === 'Sol Ring');
      card.querySelector('.cardmore').click();
    }""")
    page.wait_for_selector(".cardmenu", timeout=20000)
    check("меню открывается и кнопкой", page.locator(".cardmenu").count() == 1)
    check("и это та самая карта",
          "Sol Ring" in (page.text_content(".cmtitle") or "")
          or "Кольцо" in (page.text_content(".cmtitle") or ""),
          (page.text_content(".cmtitle") or "")[:40])

    page.evaluate("""() => {
      [...document.querySelectorAll('.cmitem')]
        .find(b => b.textContent.indexOf('Убрать из колоды') === 0).click();
    }""")
    page.wait_for_function("""() => !(bdDeck.cards || [])
      .some(c => c.name === 'Sol Ring')""", timeout=20000)
    check("«убрать» и правда убирает", qty_of("Sol Ring") == 0)

    print()
    print("=== обычное меню браузера не мешает ===")
    page.select_option("#bd-view", "rows")
    page.wait_for_selector("#bd-cards .bdrow", timeout=20000)
    prevented = page.evaluate("""() => {
      const row = document.querySelector('#bd-cards .bdrow');
      const ev = new MouseEvent('contextmenu',
        {bubbles: true, cancelable: true, clientX: 100, clientY: 100});
      row.dispatchEvent(ev);
      return ev.defaultPrevented;
    }""")
    check("на карте своё меню, а не браузерное", prevented)
    page.click("body", position={"x": 5, "y": 5})

    print()
    print("=== уборка ===")
    page.evaluate("""async (name) => {
      const list = await fetch('/api/decks').then(r => r.json());
      for (const d of list.decks.filter(d => d.name === name)) {
        await fetch('/api/decks/' + d.id, {method: 'DELETE'});
      }
    }""", DECK)
    check("своя колода удалена",
          not [d for d in get("/api/decks")["decks"] if d["name"] == DECK])
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
