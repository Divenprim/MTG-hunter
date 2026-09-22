"""Browser check: коллекция как учёт.

Коллекция перестала быть одним полем со списком. Проверяется то, ради чего она
такой стала: видно, что есть, что занято собранными колодами и что свободно;
видно, в каких колодах карта числится; видно, чего колоде не хватает и почём.

Собранная колода занимает свои карты -- это главное правило, и оно проверяется
прямо: одна и та же карта до и после отметки «собрана».

Свою колоду сценарий создаёт и удаляет, коллекцию возвращает ровно такой, какой
она была.

    .venv/Scripts/python.exe tests/ui_holdings.py
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = "http://127.0.0.1:8765"
DECK_NAME = "UI Учёт"
# Две карты берём в коллекцию, третью -- нет: на ней и видно «не хватает».
CARDS = [("Lightning Bolt", 4), ("Sol Ring", 1), ("Rhystic Study", 1)]
COLLECTION = "4 Lightning Bolt\n1 Sol Ring"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def get(path):
    return json.load(urllib.request.urlopen(BASE + path))


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")

    # Запоминаем коллекцию, чтобы вернуть её в конце ровно такой же.
    saved = get("/api/collection")["collection"]

    made = page.evaluate("""async (args) => {
      // Убираем следы прошлых прогонов.
      const list = await fetch('/api/decks').then(r => r.json());
      for (const d of list.decks.filter(d => d.name === args.name)) {
        await fetch('/api/decks/' + d.id, {method: 'DELETE'});
      }
      const made = await fetch('/api/decks', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: args.name, format: 'commander'})})
        .then(r => r.json());
      const id = made.deck.id;
      await fetch('/api/decks/' + id + '/cards', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cards: args.cards.map(
          ([name, quantity]) => ({name: name, quantity: quantity, section: 'main'}))})});
      await fetch('/api/collection', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: args.collection})});
      return id;
    }""", {"name": DECK_NAME, "cards": CARDS, "collection": COLLECTION})

    page.click('.tab[data-tab="collection"]')
    page.wait_for_selector("#coll-list .holdrow", timeout=20000)

    print("=== все карты ===")
    summary = page.text_content("#coll-summary") or ""
    check("сводка показана", "в коллекции" in summary, summary[:80])

    def row_of(name):
        return page.evaluate("""(name) => {
          const row = [...document.querySelectorAll('#coll-list .holdrow')]
            .find(r => (r.querySelector('.nm') || {}).textContent === name);
          if (!row) return null;
          const nums = [...row.querySelectorAll('.num')].map(e => e.textContent.trim());
          return {owned: nums[0], committed: nums[1], free: nums[2],
                  decks: row.querySelector('span:nth-child(5)').textContent.trim()};
        }""", name)

    bolt = row_of("Lightning Bolt")
    check("карта из коллекции показана", bolt is not None)
    check("видно, сколько есть", bolt and bolt["owned"] == "4", str(bolt))
    check("пока ничего не занято", bolt and bolt["committed"] == "", str(bolt))
    check("всё свободно", bolt and bolt["free"] == "4", str(bolt))
    check("видно, в какой колоде числится",
          bolt and DECK_NAME in bolt["decks"], str(bolt and bolt["decks"]))

    print()
    print("=== колода на бумаге и собранная ===")
    page.click('#coll-tabs [data-coll="decks"]')
    page.wait_for_timeout(300)
    card = page.locator(".deckcard", has_text=DECK_NAME)
    check("колода видна в разборе", card.count() == 1)
    check("видно, чего не хватает",
          "не хватает" in (card.first.text_content() or ""),
          (card.first.text_content() or "")[:90].replace("\n", " "))

    # Главное правило: собранная колода занимает свои карты.
    page.locator('.deckcard [data-built]').first.check()
    page.wait_for_function(
        """() => document.querySelector('#coll-summary').textContent
                 .includes('из них собрано 1')""", timeout=20000)
    page.click('#coll-tabs [data-coll="cards"]')
    page.wait_for_timeout(300)
    bolt = row_of("Lightning Bolt")
    check("после сборки карты заняты", bolt and bolt["committed"] == "4", str(bolt))
    check("и свободных не осталось", bolt and bolt["free"] == "0", str(bolt))

    print()
    print("=== несоответствия ===")
    page.click('#coll-tabs [data-coll="conflicts"]')
    page.wait_for_timeout(300)
    text = page.text_content("#coll-conflicts") or ""
    check("карта, которой нет, но она в собранной колоде, названа",
          "Rhystic Study" in text, text[:100].replace("\n", " "))

    print()
    print("=== уборка ===")
    page.evaluate("""async (args) => {
      const list = await fetch('/api/decks').then(r => r.json());
      for (const d of list.decks.filter(d => d.name === args.name)) {
        await fetch('/api/decks/' + d.id, {method: 'DELETE'});
      }
      const text = Object.entries(args.saved).map(([n, c]) => c + ' ' + n).join('\\n');
      await fetch('/api/collection', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({text: text})});
    }""", {"name": DECK_NAME, "saved": saved})

    left = get("/api/collection")["collection"]
    check("коллекция возвращена как была", left == saved,
          "было %d назв., стало %d" % (len(saved), len(left)))
    check("тестовая колода удалена",
          not [d for d in get("/api/decks")["decks"] if d["name"] == DECK_NAME])
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
