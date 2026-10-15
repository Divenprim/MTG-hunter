"""Browser check: предложка не спрашивает командира у колоды модерна.

С его слов: «что добавить спрашивает у меня имя командира, хотя я хочу
спросить что добавить в дечку модерна».

Проверяется: окно открывается сразу на вкладке «По смыслу колоды», она сама
читает колоду, показывает темы и карты по ним, и каждую можно положить в
колоду или отправить в охоту. Командирская предложка осталась на своей
вкладке — для командирской колоды окно открывается на ней.

    MTGH_UI_BASE=http://127.0.0.1:8773 .venv/Scripts/python.exe tests/ui_ideas.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
FAIL = []
DECK = "ПРОБА смысл колоды"
CARDS = [("Fog", 4), ("Haze of Pollen", 4), ("Root Snare", 4),
         ("Blunt the Assault", 2), ("Forest", 10), ("Growth Spiral", 3)]


def ok(cond, label, extra=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", label,
                          "" if not extra else " — " + str(extra)))
    if not cond:
        FAIL.append(label)


def here(page, selector):
    return page.evaluate("(s) => !!document.querySelector(s)", selector)


SETUP = """async (args) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name === args.name)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
  const made = await fetch('/api/decks', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: args.name, format: 'pioneer'})}).then(r => r.json());
  await fetch('/api/decks/' + made.deck.id + '/cards', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cards: args.cards.map(
      (c) => ({name: c[0], quantity: c[1], section: 'main'}))})});
  return made.deck.id;
}"""

CLEAN = """async (name) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name === name)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
}"""

print("=== что добавить в колоду ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(1500)

    deck_id = page.evaluate(SETUP, {"name": DECK, "cards": CARDS})
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(1000)
    page.evaluate("(id) => bdOpen(id)", deck_id)
    page.wait_for_timeout(2500)

    page.evaluate("""() => {
      const b = document.querySelector('[data-act=recommend]');
      if (b) b.click();
    }""")
    page.wait_for_timeout(6000)

    ok(page.evaluate("() => !document.querySelector('#rec-overlay').hidden"),
       "окно предложки открылось")
    active = page.evaluate("""() => {
      const b = document.querySelector('#rec-tabs .subtab.active');
      return b ? b.dataset.rectab : null;
    }""")
    ok(active == "ideas",
       "и сразу на вкладке «по смыслу колоды», а не на командирской", active)

    asks = page.evaluate("""() => {
      const f = document.querySelector('#rec-commander');
      return !!f && f.offsetParent !== null;
    }""")
    ok(not asks, "имя командира у колоды пионера не спрашивается")

    body = page.evaluate(
        "() => (document.querySelector('#ideas-body') || {}).textContent || ''")
    ok("командир" not in body.lower(),
       "и в тексте вкладки про командира ни слова", body[:80])

    labels = page.evaluate("""() => [...document.querySelectorAll('#ideas-body h3')]
        .map((h) => h.textContent.trim())""")
    ok(bool(labels), "темы колоды прочитаны", labels[:4])
    ok(any("уман" in t for t in labels),
       "и туманная колода опознана как туманная", labels[:4])

    picks = page.evaluate(
        "() => document.querySelectorAll('#ideas-body .ideacard').length")
    ok(picks > 0, "по темам предложены карты", picks)

    meta = page.evaluate(
        "() => (document.querySelector('#ideas-meta') || {}).textContent || ''")
    ok("пионер" in meta.lower() or "pioneer" in meta.lower(),
       "сказано, для какого формата подбирали", meta[:90])

    # ---------------------------------------------- предложенное кладётся
    first = page.evaluate("""() => {
      const b = document.querySelector('#ideas-body [data-idea-deck]');
      return b ? b.dataset.ideaDeck : null;
    }""")
    ok(bool(first), "у карточки есть «+ в колоду»", first)
    if first:
        page.evaluate("""() => {
          const b = document.querySelector('#ideas-body [data-idea-deck]');
          if (b) b.click();
        }""")
        page.wait_for_timeout(2500)
        inside = page.evaluate("""async (args) => {
          const r = await fetch('/api/decks/' + args.id).then(x => x.json());
          const cards = r.deck.entries || r.deck.cards || [];
          return cards.some((c) => c.name === args.name);
        }""", {"id": deck_id, "name": first})
        ok(inside, "и она действительно попадает в колоду", first)

    # ---------------------------------------------- порядок «подешевле»
    page.select_option("#ideas-order", "cheap")
    page.wait_for_timeout(6000)
    ok(page.evaluate(
        "() => document.querySelectorAll('#ideas-body .ideacard').length") > 0,
       "порядок «сперва дешёвые» тоже даёт карты")

    ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))
    page.evaluate("() => recClose()")
    page.evaluate(CLEAN, DECK)
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
