"""Browser check: панели идут за колодой, а не показывают вчерашнюю.

Жалоба: «поле форматы и доработка не меняется при переключении колод». Разбор
оставался от прежней колоды и молчал об этом — то есть отвечал на вопрос,
которого ему не задавали.

Такое же нашлось ещё в трёх местах: голдфишинг оставлял руку, сданную из другой
колоды; окно комбо — заголовок и список прежней; предложка держала в памяти
ответ про прежнего командира и показывала его молча. Плюс обратное: карты можно
править в «Версиях», а билдер этого не замечал.

Проверяется два разных случая, потому что и чинятся они по-разному:

  * **другая колода** — панели перечитываются под неё, закрытые забывают старую;
  * **та же колода, другой состав** — открытый разбор и открытое окно комбо
    пересчитываются, не теряя того, что человек уже раскрыл.

Сценарий заводит две свои колоды и удаляет их в конце.

    .venv/Scripts/python.exe tests/ui_follow.py
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = "http://127.0.0.1:8765"
A = "UI Следом А"
B = "UI Следом Б"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def get(path):
    return json.load(urllib.request.urlopen(BASE + path))


SETUP = """async (args) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name.indexOf('UI Следом') === 0)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
  const ids = {};
  for (const [name, fmt, cards] of args) {
    const made = await fetch('/api/decks', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name, format: fmt})}).then(r => r.json());
    await fetch('/api/decks/' + made.deck.id + '/cards', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cards: cards.map(
        (c) => ({name: c[0], quantity: c[1], section: 'main'}))})});
    ids[name] = made.deck.id;
  }
  return ids;
}"""

CLEAN = """async () => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name.indexOf('UI Следом') === 0)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
}"""

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1100}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")
    ids = page.evaluate(SETUP, [
        # В А мешают карты вне пула пионера, в Б — нет: разбор у них разный.
        [A, "modern", [["Ethereal Haze", 4], ["Isochron Scepter", 1]]],
        [B, "modern", [["Fog", 4], ["Llanowar Elves", 4]]],
    ])

    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(700)
    page.evaluate("(id) => bdOpen(id)", ids[A])
    page.wait_for_timeout(1500)

    print("=== другая колода: разбор форматов ===")
    page.evaluate("() => fmtOpen()")
    page.wait_for_selector("#bd-formats .fmtchip", timeout=30000)
    page.click('#bd-formats .fmtchip[data-fmt="pioneer"]')
    page.wait_for_selector("#bd-formats .fmtblock", timeout=20000)
    blocked_a = page.locator("#bd-formats .fmtblock").count()
    check("на колоде А что-то мешает в пионере", blocked_a > 0, str(blocked_a))

    page.evaluate("(id) => bdOpen(id)", ids[B])
    page.wait_for_function("""(id) => fmtState && fmtState.deckId === id
      && !document.getElementById('bd-formats').hidden""",
      arg=ids[B], timeout=30000)
    check("разбор пересчитался под новую колоду",
          page.evaluate("() => fmtState.deckId") == ids[B])
    check("и это разбор именно её",
          page.locator("#bd-formats .fmtblock").count() != blocked_a
          or "Правила формата" in (page.text_content("#bd-formats") or ""),
          "мешающих было %d, стало %d" % (
              blocked_a, page.locator("#bd-formats .fmtblock").count()))

    print()
    print("=== закрытая панель не хранит чужое ===")
    page.evaluate("() => { fmtPanel().hidden = true; }")
    page.evaluate("(id) => bdOpen(id)", ids[A])
    page.wait_for_timeout(1200)
    check("закрытая панель забыла прежнюю колоду",
          page.evaluate("() => fmtState") is None)

    print()
    print("=== другая колода: окно комбо ===")
    page.evaluate("() => cbOpen()")
    page.wait_for_selector("#cb-body .cbcombo, #cb-body .meta", timeout=90000)
    page.evaluate("(id) => bdOpen(id)", ids[B])
    page.wait_for_function("""(name) => (document.getElementById('cb-title')
      .textContent || '').indexOf(name) >= 0""", arg=B, timeout=60000)
    check("заголовок окна комбо — про новую колоду",
          B in page.text_content("#cb-title"),
          page.text_content("#cb-title"))
    check("и данные тоже",
          page.evaluate("() => cbData && cbData.deck_name") == B)
    page.evaluate("() => cbClose()")

    print()
    print("=== другая колода: голдфишинг ===")
    page.evaluate("(id) => bdOpen(id)", ids[A])
    page.wait_for_timeout(1000)
    page.evaluate("""() => {
      const b = document.querySelector('#bd-actions [data-act="goldfish"]');
      if (b) b.click();
    }""")
    page.wait_for_timeout(1500)
    check("голдфишинг открылся на колоде А",
          page.evaluate("() => gfDeck && gfDeck.name") == A)
    page.evaluate("(id) => bdOpen(id)", ids[B])
    page.wait_for_timeout(1500)
    check("и перешёл на новую колоду",
          page.evaluate("() => gfDeck && gfDeck.name") == B,
          str(page.evaluate("() => gfDeck && gfDeck.name")))
    page.evaluate("""() => { document.getElementById('gf-overlay').hidden = true; }""")

    print()
    print("=== тот же дек, другой состав ===")
    page.evaluate("(id) => bdOpen(id)", ids[A])
    page.wait_for_timeout(1200)
    page.evaluate("() => fmtOpen()")
    page.wait_for_selector("#bd-formats .fmtchip", timeout=30000)
    page.click('#bd-formats .fmtchip[data-fmt="pioneer"]')
    page.wait_for_selector("#bd-formats .fmtblock", timeout=20000)
    before = page.locator("#bd-formats .fmtblock").count()

    # Убираем мешающую карту прямо из колоды -- разбор обязан это заметить.
    page.evaluate("""async () => {
      const card = bdDeck.cards.find((c) => c.name === 'Ethereal Haze');
      await bdCall('/api/decks/' + bdDeck.id + '/cards/' + card.id,
                   {method: 'DELETE'});
    }""")
    page.wait_for_function("""(n) => document
      .querySelectorAll('#bd-formats .fmtblock').length < n""",
      arg=before, timeout=30000)
    check("разбор пересчитался после правки колоды",
          page.locator("#bd-formats .fmtblock").count() < before,
          "было %d, стало %d" % (
              before, page.locator("#bd-formats .fmtblock").count()))
    check("и выбранный формат не сбросился",
          page.evaluate("() => fmtState.open") == "pioneer")

    print()
    print("=== план переделки переживает правку и честно стареет ===")
    page.click("[data-adapt]")
    page.wait_for_selector(".fmtplan, .fmtvariant .good", timeout=90000)
    check("план посчитан", bool(page.evaluate("() => fmtState.plan")))
    page.evaluate("""async () => {
      await bdCall('/api/decks/' + bdDeck.id + '/cards', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cards: [
          {name: 'Llanowar Elves', quantity: 1, section: 'main'}]}),
      });
    }""")
    page.wait_for_function("""() => fmtState && fmtState.plan
      && fmtState.plan.stale === true""", timeout=30000)
    check("план не исчез после правки колоды",
          bool(page.evaluate("() => fmtState.plan")))
    check("и помечен устаревшим",
          "уже не точен" in (page.text_content("#bd-formats") or ""))
    check("кнопка «завести вариант» на месте",
          page.locator("[data-variant]").count() == 1)

    print()
    print("=== правки из «Версий» видны в билдере ===")
    page.evaluate("""async () => {
      await fetch('/api/decks/' + bdDeck.id + '/cards', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cards: [
          {name: 'Llanowar Elves', quantity: 3, section: 'main'}]})});
    }""")
    page.click('.tab[data-tab="family"]')
    page.wait_for_timeout(900)
    page.click('.tab[data-tab="builder"]')
    page.wait_for_function("""() => (bdDeck.cards || [])
      .some((c) => c.name === 'Llanowar Elves')""", timeout=30000)
    check("возврат на вкладку перечитывает открытую колоду", True)

    print()
    print("=== уборка ===")
    page.evaluate(CLEAN)
    check("свои колоды удалены",
          not [d for d in get("/api/decks")["decks"]
               if d["name"].startswith("UI Следом")])
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
