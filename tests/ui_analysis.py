"""Browser check: разбор колоды -- сила, соль, цена, командирский бракет.

Проверяется не «похоже ли число на правду», а то, ради чего раздел вообще
сделан:

  * **ни одного числа без слагаемых.** Балл, который нельзя развернуть, нельзя
    и оспорить -- он выглядит одинаково убедительно и когда посчитан, и когда
    выдуман. Поэтому сценарий разворачивает слагаемые и сверяет их сумму с
    самим баллом прямо на экране;
  * **соль названа тем, чем является.** Это про то, насколько колода портит
    игру другим, по нашим меркам, а не про силу, и рядом обязаны стоять карты,
    которые её набрали;
  * **чужие правила названы и датированы.** Бракеты и Game Changers придумали
    не мы, они меняются -- и в ответе должно быть видно, чьи это правила и
    когда сняты;
  * **сила и соль не связаны.** Контроль с удалением и контрмагией солёным
    быть не должен, иначе солёной окажется любая играющая колода.

Сценарий заводит свои колоды и удаляет их в конце.

    .venv/Scripts/python.exe tests/ui_analysis.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
STAX = "UI Разбор стакс"
CONTROL = "UI Разбор контроль"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


MAKE = """async ([name, fmt, cards]) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name === name)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
  const made = await fetch('/api/decks', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: name, format: fmt})}).then(r => r.json());
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

# Колода, которую трудно назвать приятной: снос земель, замки, налоги.
STAX_CARDS = [
    {"name": "Armageddon", "quantity": 1, "section": "main"},
    {"name": "Winter Orb", "quantity": 1, "section": "main"},
    {"name": "Smokestack", "quantity": 1, "section": "main"},
    {"name": "Ghostly Prison", "quantity": 1, "section": "main"},
    {"name": "Thalia, Guardian of Thraben", "quantity": 1, "section": "main"},
    {"name": "Demonic Tutor", "quantity": 1, "section": "main"},
    {"name": "Sol Ring", "quantity": 1, "section": "main"},
    {"name": "Plains", "quantity": 34, "section": "main"},
]

# Колода, которая играет, но никому не мешает жить: удаление и контрмагия.
CONTROL_CARDS = [
    {"name": "Counterspell", "quantity": 4, "section": "main"},
    {"name": "Swords to Plowshares", "quantity": 4, "section": "main"},
    {"name": "Wrath of God", "quantity": 3, "section": "main"},
    {"name": "Brainstorm", "quantity": 4, "section": "main"},
    {"name": "Island", "quantity": 12, "section": "main"},
    {"name": "Plains", "quantity": 11, "section": "main"},
]


def sums(page, key):
    return page.evaluate(
        """(key) => {
            const box = document.querySelector('.anscore[data-score="' + key + '"]');
            const value = parseInt(box.querySelector('.anvalue').textContent, 10);
            const parts = [...box.querySelectorAll('.anparts .anadds')]
                .map((e) => parseInt(e.textContent, 10));
            return {value: value, sum: parts.reduce((a, b) => a + b, 0),
                    parts: parts.length};
        }""", key)


def open_parts(page, key):
    page.evaluate(
        """(key) => {
            const box = document.querySelector('.anscore[data-score="' + key + '"]');
            const btn = box.querySelector('.antoggle');
            if (btn && box.querySelector('.anparts').hidden) btn.click();
        }""", key)
    page.wait_for_timeout(250)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1200}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")

    stax_id = page.evaluate(MAKE, [STAX, "commander", STAX_CARDS])
    control_id = page.evaluate(MAKE, [CONTROL, "legacy", CONTROL_CARDS])

    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(700)
    page.evaluate("(id) => bdOpen(id)", stax_id)
    page.wait_for_timeout(1500)

    print("=== разбор открывается ===")
    page.evaluate("""() => {
      document.querySelector('#bd-actions [data-act="analysis"]').click();
    }""")
    page.wait_for_selector(".anscore", timeout=60000)
    check("раздел посчитался", page.locator(".anscore").count() >= 3)

    print()
    print("=== ни одного числа без слагаемых ===")
    for key, label in (("power", "сила"), ("salt", "соль")):
        open_parts(page, key)
        got = sums(page, key)
        check("у «%s» есть слагаемые" % label, got["parts"] > 0)
        check("и они сходятся с баллом (%s)" % label,
              got["sum"] == got["value"],
              "балл %d, слагаемых на %d" % (got["value"], got["sum"]))

    print()
    print("=== соль с доказательствами ===")
    salt_cards = page.evaluate(
        """() => [...document.querySelectorAll(
            '.anscore[data-score="salt"] .anparts .anlink')].map(e => e.textContent)""")
    check("видно, какие карты её набрали", len(salt_cards) > 0,
          ", ".join(salt_cards[:3]))
    said = page.evaluate(
        """() => document.querySelector('.anscore[data-score="salt"]').textContent""")
    check("и сказано, что это не про силу", "портит игру другим" in said)

    print()
    print("=== командирский бракет ===")
    bracket = page.evaluate("() => document.querySelector('.anbracket').textContent")
    check("бракет назван", "B" in bracket and "—" in bracket)
    check("снос земель помешал низким бракетам",
          "уничтожение земель" in bracket, bracket[:60])
    check("правила названы и датированы",
          "Scryfall" in bracket and "Spellbook" in bracket)
    check("про cEDH сказано честно",
          "cEDH" in bracket and "намерение" in bracket)

    print()
    print("=== цена и соль на доллар ===")
    money = page.evaluate("() => document.querySelector('.anmoney').textContent")
    check("методика цены названа", "дешёвая печать" in money, money[:70])
    check("покрытие показано", "% карт" in money)

    print()
    print("=== карты наибольшего влияния ===")
    pull = page.evaluate(
        """() => [...document.querySelectorAll('.animpact .anpull li')].length""")
    check("список влияния не пуст", pull > 0, "%d строк" % pull)

    print()
    print("=== колода, которая никому не мешает ===")
    page.evaluate("(id) => bdOpen(id)", control_id)
    page.wait_for_timeout(1800)
    page.wait_for_selector(".anscore", timeout=60000)
    salt = page.evaluate(
        """() => parseInt(document.querySelector(
            '.anscore[data-score="salt"] .anvalue').textContent, 10)""")
    check("удаление и контрмагия не делают колоду солёной", salt == 0, str(salt))
    no_bracket = page.evaluate("() => document.querySelector('.anbracket').textContent")
    check("в легаси бракета нет и сказано почему",
          "только в Commander" in no_bracket, no_bracket[:70])

    page.evaluate(DROP, STAX)
    page.evaluate(DROP, CONTROL)

    print()
    check("нет ошибок в консоли", not errors, "; ".join(errors[:2]))
    browser.close()

print()
if FAIL:
    print("НЕ СОШЛОСЬ: " + "; ".join(FAIL))
    raise SystemExit(1)
print("ИТОГ: всё хорошо")
