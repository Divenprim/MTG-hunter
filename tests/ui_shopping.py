"""Browser check: «Что купить первым».

Вопрос, на который до сих пор не отвечал никто: деньги одни, а колод десять.
«Чего не хватает» считает по одной колоде, и карта, нужная трём колодам,
стоит там вперемешку с картой для одной.

Что закрепляется:

  * порядок -- то, что двигает больше колод, выше; то, что достраивает
    колоду целиком, выше всего;
  * карта без известной цены не всплывает как «дешёвая» и не врёт суммой;
  * базовые земли не занимают верх списка: на живых колодах первыми тремя
    строками шли Forest, Swamp и Island, и ради них список никто не
    открывает;
  * список не ходит в topdeck: он считается по уже известным ценам.

Проверка заводит свои колоды и убирает их за собой.

    MTGH_UI_BASE=http://127.0.0.1:8773 .venv/Scripts/python.exe tests/ui_shopping.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8773")
MARK = "ПРОВЕРКА покупки"
FAIL = []


def ok(cond, label, extra=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", label,
                          "" if not extra else " — " + str(extra)))
    if not cond:
        FAIL.append(label)


MAKE = """async (payload) => {
  const out = [];
  for (const d of payload) {
    const made = await fetch('/api/decks', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: d.name, format: 'modern'}),
    }).then((r) => r.json());
    if (!made.deck) return {error: JSON.stringify(made).slice(0, 160)};
    await fetch('/api/decks/' + made.deck.id + '/cards', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cards: d.cards}),
    });
    out.push(made.deck.id);
  }
  return {ids: out};
}"""

DROP = """async (ids) => {
  for (const id of ids) await fetch('/api/decks/' + id, {method: 'DELETE'});
  return true;
}"""

ROWS = """() => [...document.querySelectorAll('#buy-body .buyrow')].map((r) => ({
  name: (r.querySelector('.buyname b') || {}).textContent || '',
  count: (r.querySelector('.buycount') || {}).textContent || '',
  price: (r.querySelector('.buyprice') || {}).textContent || '',
  where: (r.querySelector('.buywhere') || {}).textContent || '',
  finishes: !!r.querySelector('.buyfinish'),
}))"""

# Одна карта нужна трём колодам, другая -- одной. Третья достраивает колоду
# целиком. Базовая земля есть у всех троих.
DECKS = [
    {"name": MARK + " 1", "cards": [
        {"name": "Lightning Bolt", "quantity": 4},
        {"name": "Forest", "quantity": 10},
        {"name": "Thoughtseize", "quantity": 2}]},
    {"name": MARK + " 2", "cards": [
        {"name": "Lightning Bolt", "quantity": 4},
        {"name": "Forest", "quantity": 10}]},
    {"name": MARK + " 3", "cards": [
        {"name": "Lightning Bolt", "quantity": 4},
        {"name": "Forest", "quantity": 10}]},
]

print("=== что купить первым ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    asked = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console",
            lambda m: errors.append(m.text) if m.type == "error" else None)
    page.on("request", lambda r: asked.append(r.url))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(800)

    made = page.evaluate(MAKE, DECKS)
    ids = made.get("ids") or []
    ok(len(ids) == 3, "колоды проверки заведены", made.get("error", ""))

    try:
        page.click('.tab[data-tab="collection"]')
        page.wait_for_timeout(600)
        page.click('#coll-tabs [data-coll="buy"]')
        page.wait_for_function(
            "() => document.querySelectorAll('#buy-body .buyrow').length > 0",
            timeout=120000)
        page.wait_for_timeout(300)

        rows = page.evaluate(ROWS)
        ok(len(rows) > 0, "список посчитан", "строк: %s" % len(rows))

        names = [r["name"] for r in rows]
        print("      первые пять: " + ", ".join(names[:5]))

        print("--- порядок")
        if "Lightning Bolt" in names and "Thoughtseize" in names:
            ok(names.index("Lightning Bolt") < names.index("Thoughtseize"),
               "карта для трёх колод выше карты для одной",
               "Bolt на %d, Thoughtseize на %d"
               % (names.index("Lightning Bolt"), names.index("Thoughtseize")))
        else:
            ok(False, "обе проверочные карты в списке", names[:6])

        bolt = next((r for r in rows if r["name"] == "Lightning Bolt"), None)
        if bolt:
            ok("12" in bolt["count"], "сложены копии всех трёх колод",
               bolt["count"].strip())
            ok(bolt["where"].count("ПРОВЕРКА") >= 3,
               "видно, кому карта нужна", bolt["where"][:70])

        print("--- базовые земли")
        ok("Forest" not in names,
           "базовая земля не занимает верх списка",
           "Forest на месте %s" % (names.index("Forest") if "Forest" in names
                                   else "—"))
        summary = page.text_content("#buy-summary") or ""
        ok("базовых земель" in summary,
           "но про них сказано отдельно", " ".join(summary.split())[-80:])

        print("--- цены")
        nameless = [r for r in rows if "не спрашивали" in r["price"]]
        if nameless:
            first_nameless = names.index(nameless[0]["name"])
            priced = [i for i, r in enumerate(rows) if "₽" in r["price"]]
            ok(not priced or first_nameless > priced[0],
               "карта без цены не выдаётся за дешёвую",
               "без цены на %d" % first_nameless)
        ok("₽" in summary, "в сводке есть сумма", " ".join(summary.split())[:90])

        print("--- наружу не ходим")
        ok(not [u for u in asked if "topdeck" in u],
           "список не спрашивает topdeck",
           "; ".join(u for u in asked if "topdeck" in u)[:80])

        print("--- базовые земли по просьбе показываются")
        page.check("#buy-basics")
        page.wait_for_timeout(1500)
        names2 = [r["name"] for r in page.evaluate(ROWS)]
        ok("Forest" in names2, "с флажком земли появляются",
           "строк: %s" % len(names2))
        page.uncheck("#buy-basics")
        page.wait_for_timeout(1200)

        print("--- а что лишнее")
        # Коллекция песочницы своя; проверяем не числа, а то, что счёт
        # считается, отвечает про запас и не зовёт topdeck.
        page.evaluate("() => { document.querySelector('#buy-spare').open = true;"
                      " document.querySelector('#buy-spare')"
                      ".dispatchEvent(new Event('toggle')); }")
        # Ждём с оговоркой: если блок не наполнился, проверка должна
        # сказать «FAIL», а не свалиться с чужим стеком.
        try:
            page.wait_for_function(
                "() => { const b = document.querySelector('#spare-body');"
                " return b && !/считаю/.test(b.textContent) &&"
                " b.textContent.trim().length > 0; }", timeout=60000)
        except Exception as exc:                      # noqa: BLE001
            ok(False, "блок «что лишнее» наполнился",
               str(exc).splitlines()[0][:70])
        spare = page.evaluate("""() => ({
          rows: document.querySelectorAll('#spare-body .buyrow').length,
          text: (document.querySelector('#spare-body').textContent || '').trim(),
          head: (document.querySelector('#spare-summary').textContent || '').trim(),
        })""")
        ok(spare["rows"] > 0 or "Лишнего нет" in spare["text"],
           "лишнее посчитано", spare["text"][:70])
        if spare["rows"]:
            page.select_option("#spare-keep", "2")
            page.wait_for_timeout(1500)
            kept = page.evaluate(
                "() => document.querySelectorAll('#spare-body .buyrow').length")
            ok(kept <= spare["rows"],
               "с запасом лишнего становится не больше",
               "было %s, стало %s" % (spare["rows"], kept))
        ok(not [u for u in asked if "topdeck" in u],
           "лишнее тоже не спрашивает topdeck")

        ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))
    finally:
        page.evaluate(DROP, ids)
        left = page.evaluate(
            """async (mark) => {
                 const r = await fetch('/api/decks').then((x) => x.json());
                 return (r.decks || []).filter(
                   (d) => (d.name || '').indexOf(mark) === 0).length;
               }""", MARK)
        ok(left == 0, "колоды проверки убраны", "осталось: %s" % left)
        browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
