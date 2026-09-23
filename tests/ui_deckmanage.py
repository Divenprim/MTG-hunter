"""Browser check: управление колодами и картами.

Три жалобы, каждая своя проверка.

**Ветки одного замысла стояли в списке как разные колоды.** Четыре строки
«turbo fog», «turbo fog 2», «turbo fog (вариант)» выглядели как четыре разные
колоды, хотя это одна. Теперь колоды одного семейства свёрнуты в группу.

**Список шёл подряд, без порядка и поиска.** Теперь есть и то и другое.

**Карту нельзя было отложить.** Сменить секцию можно было только удалив карту и
заведя заново, а «возможно» -- это место, куда карту убирают из колоды, не
выбрасывая. Теперь секция меняется одним нажатием в строке, а отмеченные карты
переносятся или убираются разом.

Свои колоды сценарий создаёт и удаляет.

    .venv/Scripts/python.exe tests/ui_deckmanage.py
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = "http://127.0.0.1:8765"
FAMILY = "UI Управление"
NAMES = ["UI Управление — раз", "UI Управление — два", "UI Управление — одиночка"]
CARDS = [("Lightning Bolt", 4), ("Sol Ring", 1), ("Fog", 3), ("Counterspell", 2)]
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def get(path):
    return json.load(urllib.request.urlopen(BASE + path))


SETUP = """async (args) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name.indexOf('UI Управление') === 0)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
  const mk = async (name, family) => {
    const made = await fetch('/api/decks', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name, format: 'modern'})}).then(r => r.json());
    await fetch('/api/decks/' + made.deck.id + '/cards', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cards: args.cards.map(
        (c) => ({name: c[0], quantity: c[1], section: 'main'}))})});
    if (family) {
      await fetch('/api/decks/' + made.deck.id, {method: 'PATCH',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({family: family})});
    }
    return made.deck.id;
  };
  return [await mk(args.names[0], args.family),
          await mk(args.names[1], args.family),
          await mk(args.names[2], '')];
}"""

CLEAN = """async () => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name.indexOf('UI Управление') === 0)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
}"""

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")
    ids = page.evaluate(SETUP, {"family": FAMILY, "names": NAMES, "cards": CARDS})

    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(700)
    page.fill("#bd-decksearch", "UI Управление")
    page.wait_for_timeout(400)

    print("=== список колод ===")
    check("семейство свёрнуто в одну группу",
          page.locator('.bdfamily[data-family="%s"]' % FAMILY).count() == 1)
    check("внутри группы оба исполнения",
          page.locator('.bdfamily[data-family="%s"] .bddeck' % FAMILY).count() == 2)
    check("одиночная колода осталась строкой",
          page.locator("#bd-decks > .bddeck").count() == 1)

    page.click('.bdfamily[data-family="%s"] .fhead' % FAMILY)
    page.wait_for_timeout(300)
    check("группа сворачивается",
          page.locator('.bdfamily[data-family="%s"] .bddeck' % FAMILY).count() == 0)
    page.click('.bdfamily[data-family="%s"] .fhead' % FAMILY)
    page.wait_for_timeout(300)

    page.select_option("#bd-decksort", "name")
    page.wait_for_timeout(300)
    # Порядок проверяется по верхнему уровню: группа стоит там, где стояло бы
    # её первое исполнение, а внутри неё свой порядок. Сравнивать вперемешку
    # нельзя -- это разные уровни списка.
    top = page.evaluate("""() => [...document.querySelectorAll('#bd-decks > *')]
      .map(e => e.classList.contains('bdfamily')
        ? e.querySelector('.fhead b').textContent.trim()
        : (e.querySelector('.nm') || {}).textContent.trim())
      .filter(Boolean)""")
    inside = page.eval_on_selector_all(
        '.bdfamily[data-family="%s"] .bddeck .nm' % FAMILY,
        "els => els.map(e => e.textContent.trim())")
    check("порядок верхнего уровня по имени", top == sorted(top), ", ".join(top))
    check("и внутри семейства тоже", inside == sorted(inside), ", ".join(inside))

    page.fill("#bd-decksearch", "одиночка")
    page.wait_for_timeout(400)
    check("поиск отбирает по имени",
          page.locator("#bd-decks .bddeck").count() == 1,
          "%d" % page.locator("#bd-decks .bddeck").count())
    page.fill("#bd-decksearch", "UI Управление")
    page.wait_for_timeout(400)

    print()
    print("=== секция карты одним нажатием ===")
    page.evaluate("(id) => bdOpen(id)", ids[0])
    page.wait_for_timeout(900)
    page.select_option("#bd-view", "rows")
    page.wait_for_selector("#bd-cards .bdrow", timeout=20000)

    def section_of(name):
        return page.evaluate("""(name) => {
          const card = (bdDeck.cards || []).find(c => c.name === name);
          return card ? card.section : null;
        }""", name)

    page.evaluate("""() => {
      const row = [...document.querySelectorAll('#bd-cards .bdrow')]
        .find(r => r.querySelector('.nm').textContent.indexOf('Fog') === 0);
      row.querySelector('[data-sect="side"]').click();
    }""")
    page.wait_for_function("""() => ((bdDeck.cards || [])
      .find(c => c.name === 'Fog') || {}).section === 'side'""", timeout=20000)
    check("карта уходит в сайдборд одним нажатием", section_of("Fog") == "side")

    page.evaluate("""() => {
      const row = [...document.querySelectorAll('#bd-cards .bdrow')]
        .find(r => r.querySelector('.nm').textContent.indexOf('Fog') === 0);
      row.querySelector('[data-sect="maybe"]').click();
    }""")
    page.wait_for_function("""() => ((bdDeck.cards || [])
      .find(c => c.name === 'Fog') || {}).section === 'maybe'""", timeout=20000)
    check("и дальше в «возможно» — тоже одним", section_of("Fog") == "maybe")

    print()
    print("=== отмеченные карты разом ===")
    page.evaluate("""() => {
      [...document.querySelectorAll('#bd-cards .bdrow')]
        .filter(r => ['Lightning Bolt', 'Counterspell'].some(
          n => r.querySelector('.nm').textContent.indexOf(n) === 0))
        .forEach(r => r.querySelector('.pick').click());
    }""")
    page.wait_for_selector("#bd-bulk:not([hidden])", timeout=20000)
    check("полоса действий появилась, когда есть что делать",
          "отмечено: 2" in (page.text_content("#bd-bulk") or ""),
          (page.text_content("#bd-bulk") or "")[:40])

    page.click('#bd-bulk [data-bulk="side"]')
    page.wait_for_function("""() => ['Lightning Bolt', 'Counterspell'].every(
      n => ((bdDeck.cards || []).find(c => c.name === n) || {}).section === 'side')""",
                           timeout=20000)
    check("обе карты переехали разом",
          section_of("Lightning Bolt") == "side" and section_of("Counterspell") == "side")
    check("и отметки снялись",
          page.locator("#bd-bulk[hidden]").count() == 1)

    print()
    print("=== уборка ===")
    page.evaluate(CLEAN)
    left = [d for d in get("/api/decks")["decks"] if d["name"].startswith("UI Управление")]
    check("свои колоды удалены", not left, str([d["name"] for d in left]))
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
