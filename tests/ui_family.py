"""Browser check: вкладка «Версии» — матрица исполнений, модули, ответвления.

Проверяется то, ради чего она есть: два исполнения одного замысла лежат рядом,
их общее видно без чтения, ячейку можно править на месте, отмеченные строки
собираются в кусок колоды и кладутся в другое исполнение целиком.

Свои колоды сценарий создаёт и удаляет, чужого не трогает.

    .venv/Scripts/python.exe tests/ui_family.py
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = "http://127.0.0.1:8765"
FAMILY = "UI Замысел"
A_NAME = "UI Замысел — первый"
B_NAME = "UI Замысел — второй"
# Общее ядро, и по одной своей карте у каждого. Counterspell -- ответная карта:
# она обязана попасть в кандидаты в сайдборд.
CORE = [("Lightning Bolt", 4), ("Sol Ring", 1)]
ONLY_A = [("Fog", 4)]
ONLY_B = [("Counterspell", 3)]
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def get(path):
    return json.load(urllib.request.urlopen(BASE + path))


SETUP = """async (args) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name.indexOf('UI Замысел') === 0)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
  const mk = async (name, cards) => {
    const made = await fetch('/api/decks', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name, format: 'modern'})}).then(r => r.json());
    await fetch('/api/decks/' + made.deck.id + '/cards', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cards: cards.map(
        (c) => ({name: c[0], quantity: c[1], section: 'main'}))})});
    await fetch('/api/decks/' + made.deck.id, {method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({family: args.family})});
    return made.deck.id;
  };
  const a = await mk(args.a, args.core.concat(args.onlyA));
  const b = await mk(args.b, args.core.concat(args.onlyB));
  return [a, b];
}"""

CLEAN = """async () => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name.indexOf('UI Замысел') === 0)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
  const mods = await fetch('/api/modules').then(r => r.json());
  for (const m of mods.modules.filter(m => m.name.indexOf('UI Модуль') === 0)) {
    await fetch('/api/modules/' + m.id, {method: 'DELETE'});
  }
}"""

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1100}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("dialog", lambda d: d.accept("UI Замысел — третий"))
    page.goto(BASE, wait_until="networkidle")

    ids = page.evaluate(SETUP, {"family": FAMILY, "a": A_NAME, "b": B_NAME,
                                "core": CORE, "onlyA": ONLY_A, "onlyB": ONLY_B})

    page.click('.tab[data-tab="family"]')
    page.wait_for_selector("#fam-side .famrow", timeout=20000)
    page.click('[data-family="%s"]' % FAMILY)
    page.wait_for_selector(".famline", timeout=20000)

    print("=== матрица ===")
    check("оба исполнения показаны рядом",
          page.locator(".famvar").count() == 2,
          "%d" % page.locator(".famvar").count())

    def group_rows(title):
        return page.evaluate("""(title) => {
          const group = [...document.querySelectorAll('.famgroup')]
            .find(g => (g.querySelector('h4') || {}).textContent.indexOf(title) === 0);
          if (!group) return [];
          return [...group.querySelectorAll('.famname b')].map(e => e.textContent);
        }""", title)

    core = group_rows("Ядро")
    check("в ядре ровно общее", set(core) == {"Lightning Bolt", "Sol Ring"},
          ", ".join(core))
    flex = group_rows("Сменные")
    check("в сменных ровно своё", set(flex) == {"Fog", "Counterspell"},
          ", ".join(flex))
    check("ответная карта помечена в сайдборд",
          page.evaluate("""() => {
            const row = [...document.querySelectorAll('.famline')]
              .find(r => r.querySelector('.famname b').textContent === 'Counterspell');
            return !!row && row.classList.contains('side');
          }"""))

    print()
    print("=== правка прямо из матрицы ===")
    before = len([c for c in get("/api/decks/%s" % ids[0])["deck"]["cards"]
                  if c["name"] == "Fog"])
    page.evaluate("""() => {
      const row = [...document.querySelectorAll('.famline')]
        .find(r => r.querySelector('.famname b').textContent === 'Counterspell');
      row.querySelectorAll('.famcell')[0].querySelector('.famplus').click();
    }""")
    page.wait_for_function("""() => {
      const row = [...document.querySelectorAll('.famline')]
        .find(r => r.querySelector('.famname b').textContent === 'Counterspell');
      return row && row.querySelectorAll('.famcell')[0]
        .querySelector('b').textContent === '1';
    }""", timeout=20000)
    cards = get("/api/decks/%s" % ids[0])["deck"]["cards"]
    check("плюс в ячейке правда кладёт карту в колоду",
          any(c["name"] == "Counterspell" for c in cards))
    check("и карта переехала в ядро",
          "Counterspell" in group_rows("Ядро"), ", ".join(group_rows("Ядро")))

    page.evaluate("""() => {
      const row = [...document.querySelectorAll('.famline')]
        .find(r => r.querySelector('.famname b').textContent === 'Counterspell');
      row.querySelectorAll('.famcell')[0].querySelector('.famminus').click();
    }""")
    page.wait_for_timeout(1500)
    cards = get("/api/decks/%s" % ids[0])["deck"]["cards"]
    check("минус убирает её обратно",
          not any(c["name"] == "Counterspell" for c in cards))

    print()
    print("=== модуль ===")
    page.evaluate("""() => {
      [...document.querySelectorAll('.famline')]
        .filter(r => ['Lightning Bolt', 'Sol Ring']
          .indexOf(r.querySelector('.famname b').textContent) >= 0)
        .forEach(r => r.querySelector('input[data-row]').click());
    }""")
    page.fill("#fam-modname", "UI Модуль")
    page.click("#fam-make")
    page.wait_for_selector("#fam-modules .modrow", timeout=20000)
    check("модуль собрался", page.locator("#fam-modules .modrow").count() == 1)
    module = get("/api/modules")["modules"][0]
    check("в модуле те самые карты",
          {c["name"] for c in module["cards"]} == {"Lightning Bolt", "Sol Ring"},
          str([c["name"] for c in module["cards"]]))

    print()
    print("=== ответвление ===")
    page.evaluate("""(id) => {
      document.querySelector('[data-branch="' + id + '"]').click();
    }""", ids[0])
    page.wait_for_function("""() => document.querySelectorAll('.famvar').length === 3""",
                           timeout=30000)
    check("ответвление встало в то же семейство",
          page.locator(".famvar").count() == 3)
    branched = [d for d in get("/api/decks")["decks"]
                if d["name"] == "UI Замысел — третий"]
    check("и это отдельная колода с теми же картами",
          bool(branched) and branched[0]["cards"] == sum(q for _n, q in CORE + ONLY_A),
          str(branched and branched[0]["cards"]))

    print()
    print("=== уборка ===")
    page.evaluate(CLEAN)
    left = [d for d in get("/api/decks")["decks"] if d["name"].startswith("UI Замысел")]
    check("свои колоды удалены", not left, str([d["name"] for d in left]))
    check("модуль удалён",
          not [m for m in get("/api/modules")["modules"]
               if m["name"].startswith("UI Модуль")])
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
