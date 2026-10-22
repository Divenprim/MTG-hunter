"""Browser check: «Что ещё есть у этих продавцов».

Посылка стоит одинаково, одна в ней карта или двадцать. Если продавец уже
в плане, всё остальное нужное у него приедет без второй пересылки -- ради
этого и кнопка. Проверяется вся дорожка целиком, потому что каждый её кусок
уже однажды подводил:

  * позицию плана кладёт `PlanItem.as_dict()` в поле `offer`. Первая версия
    искала `candidate` и на плане из десяти частников честно отвечала «в
    плане одни магазины»;
  * в добор идут только частники: у магазина ссылка ведёт на товар, а не на
    склад, и читать там нечего;
  * искомое имя topdeck оборачивает в <b>, и сырая строка показала бы
    человеку теги -- это уже было однажды;
  * «дешевле рынка» считается против медианы из уже собранных цен, и если
    цены ещё не собраны, так и должно быть сказано, а не «−0%».

Запросы к topdeck уходят только по нажатию. Поэтому сценарий требует
песочницу, где клиент topdeck подменён: наружу он не ходит, тему продавца
отдаёт обезличенным образцом из tests/data.

    MTGH_UI_BASE=http://127.0.0.1:8773 .venv/Scripts/python.exe tests/ui_restock.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8773")
DECK = "ПРОВЕРКА добор"
# Эти карты есть в образце склада -- значит доборе им и находиться.
WANTS = ["Dark Ritual", "Blood Moon", "Entomb", "Grim Monolith", "Memory Jar"]
FAIL = []


def ok(cond, label, extra=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", label,
                          "" if not extra else " — " + str(extra)))
    if not cond:
        FAIL.append(label)


MAKE_DECK = """async (payload) => {
  const made = await fetch('/api/decks', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: payload.name, format: 'commander'}),
  }).then((r) => r.json());
  if (!made.deck) return {error: JSON.stringify(made).slice(0, 200)};
  await fetch('/api/decks/' + made.deck.id + '/cards', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cards: payload.cards.map(
      (n) => ({name: n, quantity: 1}))}),
  });
  return {id: made.deck.id};
}"""

DROP_DECK = """async (id) => {
  await fetch('/api/decks/' + id, {method: 'DELETE'});
  return true;
}"""

BOX = """() => {
  const box = document.querySelector('#hunt-restock-box');
  const rows = [...box.querySelectorAll('.restockrow')].map((r) => ({
    want: (r.querySelector('b') || {}).textContent || '',
    price: (r.querySelector('.price') || {}).textContent || '',
    market: (r.querySelector('.meta') || {}).textContent || '',
    line: (r.querySelector('.rawline') || {}).textContent || '',
    add: !!r.querySelector('[data-restock-add]'),
  }));
  return {text: (box.textContent || '').trim().slice(0, 160),
          sellers: box.querySelectorAll('.restockbox').length,
          rows: rows};
}"""

print("=== что ещё есть у продавцов из плана ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console",
            lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(800)

    # Добор ищет то, что нужно по колодам и избранному и чего нет в
    # коллекции, -- а не то, что было в строке охоты. Поэтому колода.
    made = page.evaluate(MAKE_DECK, {"name": DECK, "cards": WANTS})
    ok(bool(made.get("id")), "колода проверки заведена", made.get("error", ""))
    deck_id = made.get("id")

    try:
        page.click('.tab[data-tab="hunt"]')
        page.wait_for_timeout(400)
        page.fill("#hunt-wants", "\n".join("1 " + n for n in WANTS))
        page.uncheck("#f-collection")
        page.click("#hunt-btn")
        page.wait_for_function(
            "() => document.querySelectorAll('#hunt-plan .lot').length > 0",
            timeout=300000)
        page.wait_for_timeout(600)

        lots = page.evaluate(
            "() => document.querySelectorAll('#hunt-plan .lot').length")
        ok(lots > 0, "план охоты собран", "лотов: %s" % lots)

        print("--- кнопка видна и знает, к кому идти")
        shown = page.evaluate(
            "() => { const b = document.querySelector('#hunt-restock');"
            " return b && b.offsetParent !== null; }")
        ok(shown, "кнопка «Что ещё есть у этих продавцов» на месте")
        sellers = page.evaluate("() => restockSellers()")
        ok(len(sellers) > 0, "в плане нашлись частники с темой на topdeck",
           "складов: %s" % len(sellers))
        ok(all(s["url"].startswith("https://topdeck.ru/") for s in sellers),
           "в добор идут только ссылки на topdeck",
           "; ".join(s["url"] for s in sellers[:2]))
        ok(len({s["url"] for s in sellers}) == len(sellers),
           "один продавец — один запрос, без повторов",
           "ссылок %s" % len(sellers))

        print("--- добор")
        page.click("#hunt-restock")
        page.wait_for_function(
            "() => { const b = document.querySelector('#hunt-restock-box');"
            " return b && !/ищ[уе]м/i.test(b.textContent) &&"
            " b.textContent.trim().length > 0; }", timeout=300000)
        page.wait_for_timeout(400)

        got = page.evaluate(BOX)
        ok(got["sellers"] > 0, "показаны склады с находками",
           got["text"][:120])
        ok(len(got["rows"]) > 0, "находки перечислены",
           "строк: %s" % len(got["rows"]))

        if got["rows"]:
            row = got["rows"][0]
            print("      первая находка: %s · %s · %s"
                  % (row["want"].strip(), row["price"].strip(),
                     row["line"].strip()[:40]))
            ok(row["want"].strip() in WANTS,
               "найдено именно то, что мы ищем", row["want"])
            ok("<" not in row["line"] and ">" not in row["line"],
               "строка склада показана без тегов", row["line"][:60])
            ok(row["add"], "у находки есть «+ в охоту»")
            ok(bool(row["price"].strip()), "цена показана или названа невидимой",
               row["price"])
            ok(bool(row["market"].strip()),
               "про рыночную цену сказано прямо", row["market"][:60])

        print("--- выгода названа своим именем")
        # «−-2029%»: карта в двадцать раз дороже рынка, подписанная скидкой.
        # Знак у выгоды бывает обоих видов, и минус перед минусом -- ровно то,
        # за чем сюда и приходят.
        bad = [r["market"] for r in got["rows"] if "−-" in r["market"]
               or "--" in r["market"]]
        ok(not bad, "нет «минуса перед минусом»", "; ".join(bad[:2]))
        pricey = page.evaluate(
            """() => [...document.querySelectorAll('#hunt-restock-box .restockrow')]
                 .map((r) => ({
                   pricey: r.classList.contains('pricey'),
                   says: (r.querySelector('.meta') || {}).textContent || ''}))""")
        wrong = [p["says"][:50] for p in pricey
                 if p["pricey"] != ("дороже на" in p["says"])]
        ok(not wrong, "дорогое помечено дорогим, дешёвое — выгодой",
           "; ".join(wrong[:2]))
        cheap = [p for p in pricey if "дешевле на" in p["says"]]
        over = [p for p in pricey if "дороже на" in p["says"]]
        print("      выгодных: %d, дороже рынка: %d, из них помечено: %d"
              % (len(cheap), len(over),
                 len([p for p in over if p["pricey"]])))

        print("--- все три случая разом")
        # В настоящем складе может не оказаться ни одной выгодной позиции, а
        # проверить надо и её, и «как на рынке», и «цены не знаем». Поэтому
        # отрисовка зовётся напрямую на подложенных числах: это именно та
        # функция, что рисует настоящие находки.
        three = page.evaluate("""() => {
          const data = {wants: 3, note: 'проверка', sellers: [{
            url: 'https://topdeck.ru/forums/topic/999001/', lines: 40,
            found: [
              {want: 'Дешёвая', price: 300, median: 1000, cheaper_by: 70,
               line: '1 Дешёвая 300'},
              {want: 'Дорогая', price: 2000, median: 1000, cheaper_by: -100,
               line: '1 Дорогая 2000'},
              {want: 'Ровно', price: 1000, median: 1000, cheaper_by: 0,
               line: '1 Ровно 1000'},
              {want: 'Неизвестная', price: 500, median: null,
               cheaper_by: null, line: '1 Неизвестная 500'},
            ]}]};
          const names = new Map([[data.sellers[0].url, 'ПРОВЕРКА-Склад']]);
          restockRender(data, names);
          const box = document.querySelector('#hunt-restock-box');
          return {
            head: (box.querySelector('h4') || {}).textContent || '',
            rows: [...box.querySelectorAll('.restockrow')].map((r) => ({
              want: (r.querySelector('b') || {}).textContent || '',
              says: (r.querySelector('.meta') || {}).textContent || '',
              pricey: r.classList.contains('pricey'),
            })),
          };
        }""")
        by = {r["want"]: r for r in three["rows"]}
        ok("дешевле на 70%" in by.get("Дешёвая", {}).get("says", ""),
           "выгодная подписана выгодой", by.get("Дешёвая", {}).get("says", ""))
        ok("дороже на 100%" in by.get("Дорогая", {}).get("says", "")
           and by.get("Дорогая", {}).get("pricey"),
           "дорогая названа дорогой и приглушена",
           by.get("Дорогая", {}).get("says", ""))
        ok("как на рынке" in by.get("Ровно", {}).get("says", ""),
           "ровно по рынку — так и сказано", by.get("Ровно", {}).get("says", ""))
        ok("ещё не знаем" in by.get("Неизвестная", {}).get("says", ""),
           "про неизвестную цену сказано честно",
           by.get("Неизвестная", {}).get("says", ""))
        ok("дешевле рынка: 1" in three["head"],
           "в заголовке склада видно, сколько выгодного", three["head"])

        # Вернуть настоящую выдачу: дальше проверяется «+ в охоту».
        page.click("#hunt-restock")
        page.wait_for_function(
            "() => document.querySelectorAll('#hunt-restock-box .restockrow')"
            ".length > 0", timeout=300000)
        page.wait_for_timeout(400)

        print("--- «+ в охоту» добавляет карту")
        before = page.evaluate(
            "() => (document.querySelector('#hunt-wants').value || '')")
        page.click("#hunt-restock-box [data-restock-add]")
        page.wait_for_timeout(600)
        after = page.evaluate(
            "() => (document.querySelector('#hunt-wants').value || '')")
        ok(after != before, "список охоты пополнился",
           "было %d симв., стало %d" % (len(before), len(after)))

        print("--- наружу не ходили лишний раз")
        ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))
    finally:
        if deck_id:
            page.evaluate(DROP_DECK, deck_id)
            left = page.evaluate(
                """async (name) => {
                     const r = await fetch('/api/decks').then((x) => x.json());
                     return (r.decks || []).filter((d) => d.name === name).length;
                   }""", DECK)
            ok(left == 0, "колода проверки убрана", "осталось: %s" % left)
        browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
