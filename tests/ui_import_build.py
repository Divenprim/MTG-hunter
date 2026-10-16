"""Browser check: принесённую колоду можно собрать, а не только посмотреть.

С его слов: «кнопка импорт колоды вообще полная хуета, она может открыть
колоду из онлайна, но не добавить её в билдер».

Замер подтвердил буквально: вкладка умела загрузить по ссылке, разобрать
список, отфильтровать, добавить выбранное в избранное, отправить в охоту и
скопировать списком — и ни одной кнопки, которая делает из принесённого
колоду. Человек тащил список с archidekt, смотрел на него и уходил ни с чем.

Проверяется: список разбирается, из него собирается колода, она открывается
в билдере, и в ней всё — вместе с сайдбордом. Отдельно — «влить в открытую».

Сценарий заводит свои колоды «ПРОБА …» и убирает их за собой.

    MTGH_UI_BASE=http://127.0.0.1:8773 .venv/Scripts/python.exe tests/ui_import_build.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
FAIL = []
NAME = "ПРОБА из списка"
INTO = "ПРОБА куда вливать"
LIST = "4 Fog\n2 Root Snare\n10 Forest\n\nSideboard\n3 Opt"


def ok(cond, label, extra=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", label,
                          "" if not extra else " — " + str(extra)))
    if not cond:
        FAIL.append(label)


def here(page, selector):
    return page.evaluate("(s) => !!document.querySelector(s)", selector)


CLEAN = """async (names) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => names.indexOf(d.name) >= 0)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
}"""

CARDS = """async (name) => {
  const list = await fetch('/api/decks').then(r => r.json());
  const deck = list.decks.find((d) => d.name === name);
  if (!deck) return null;
  const full = await fetch('/api/decks/' + deck.id).then(r => r.json());
  const cards = full.deck.entries || full.deck.cards || [];
  return {формат: deck.format,
          карты: cards.map((c) => c.quantity + '× ' + c.name + '/' + c.section).sort()};
}"""

print("=== из принесённого списка — своя колода ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(1500)
    page.evaluate(CLEAN, [NAME, INTO])

    # --------------------------------------------------- разобрать список
    page.click('.tab[data-tab="deck"]')
    page.wait_for_timeout(1200)
    page.evaluate("""(text) => {
      const box = document.querySelector('#deck-text');
      box.value = text;
      box.dispatchEvent(new Event('input', {bubbles: true}));
      const details = document.querySelector('#panel-deck details.help');
      if (details) details.open = true;
    }""", LIST)
    page.evaluate("() => document.querySelector('#deck-text-btn').click()")
    page.wait_for_timeout(4000)

    ok(page.evaluate("() => (currentDeck && currentDeck.entries || []).length") > 0,
       "список разобран")
    ok(here(page, "#deck-to-builder"),
       "и есть кнопка «Собрать в билдере» — та, которой раньше не было")

    # --------------------------------------------------- собрать колоду
    if here(page, "#deck-to-builder"):
        page.fill("#deck-build-name", NAME)
        page.evaluate("() => document.querySelector('#deck-to-builder').click()")
        page.wait_for_timeout(5000)

    got = page.evaluate(CARDS, NAME)
    ok(got is not None, "колода появилась в билдере", got)
    if got:
        ok("4× Fog/main" in got["карты"], "основная часть на месте", got["карты"])
        ok(any("Opt/side" in c for c in got["карты"]),
           "и сайдборд не потерялся", got["карты"])
        ok(got["формат"] in ("standard", "pioneer", "modern", "pauper",
                             "legacy", "vintage", "commander"),
           "формат проставлен сам", got["формат"])

    ok(page.evaluate(
        "() => document.querySelector('.tab.active').dataset.tab") == "builder",
       "и программа сразу показала её в билдере")
    ok(page.evaluate("() => (bdDeck || {}).name") == NAME,
       "именно эту колоду, а не какую-то другую",
       page.evaluate("() => (bdDeck || {}).name"))

    # --------------------------------------------- влить в открытую колоду
    page.evaluate("""async (name) => {
      const made = await fetch('/api/decks', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name, format: 'pioneer'})}).then(r => r.json());
      await bdLoadDecks();
      await bdOpen(made.deck.id);
    }""", INTO)
    page.wait_for_timeout(3000)

    page.click('.tab[data-tab="deck"]')
    page.wait_for_timeout(1200)
    ok(here(page, "#deck-into-open"), "есть «Влить в открытую колоду»")
    if here(page, "#deck-into-open"):
        page.evaluate("() => document.querySelector('#deck-into-open').click()")
        page.wait_for_timeout(4000)
    poured = page.evaluate(CARDS, INTO)
    ok(poured is not None and poured["карты"],
       "влилось в ту колоду, что открыта", poured)
    if poured and poured["карты"]:
        ok("4× Fog/main" in poured["карты"],
           "и влилось целиком", poured["карты"][:3])

    ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))
    page.evaluate(CLEAN, [NAME, INTO])
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
