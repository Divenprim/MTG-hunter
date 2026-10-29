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
    want: (r.querySelector('.rwant') || {}).textContent || '',
    price: (r.querySelector('.price') || {}).textContent || '',
    market: (r.querySelector('.rmarket') || {}).textContent || '',
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
                   says: (r.querySelector('.rmarket') || {}).textContent || ''}))""")
        wrong = [p["says"][:50] for p in pricey
                 if p["pricey"] != ("дороже рынка" in p["says"])]
        ok(not wrong, "дорогое помечено дорогим",
           "; ".join(wrong[:2]))

        print("--- каждый случай назван своим именем")
        # Своими числами, потому что в настоящем складе может не оказаться
        # ни одной сравнимой позиции, а проверить надо все исходы. Это та
        # же функция, что рисует настоящие находки.
        three = page.evaluate("""() => {
          const data = {wants: 6, note: 'проверка',
            versions: {priced: 10, split: 4}, sellers: [{
            url: 'https://topdeck.ru/forums/topic/999001/', lines: 40,
            found: [
              {want: 'Находка', price: 90, median: 150, market_min: 120,
               market_offers: 40, verdict: 'below-floor', cheaper_by: 25,
               line: '1 Находка 90'},
              {want: 'Обычная', price: 130, median: 150, market_min: 120,
               market_offers: 40, verdict: 'in-range', cheaper_by: null,
               line: '1 Обычная 130'},
              {want: 'Дорогая', price: 300, median: 150, market_min: 120,
               market_offers: 40, verdict: 'above', cheaper_by: -100,
               line: '1 Дорогая 300'},
              {want: 'Фойла', price: 16000, median: 5000, market_min: 4000,
               market_offers: 12, verdict: 'incomparable', cheaper_by: null,
               foil: true, set_code: 'mps', condition: 'NM',
               why: 'фойл — в наших ценах он смешан с обычными',
               line: '1 Фойла MPS Foil 16000'},
              {want: 'Разнобой', price: 15, median: 400, market_min: 10,
               market_offers: 247, verdict: 'incomparable', cheaper_by: null,
               why: 'цены по этому имени слишком разные',
               line: '1 Разнобой 15'},
              {want: 'Неизвестная', price: 500, median: null,
               market_min: null, verdict: 'unknown', cheaper_by: null,
               line: '1 Неизвестная 500'},
            ]}]};
          const names = new Map([[data.sellers[0].url, 'ПРОВЕРКА-Склад']]);
          restockRender(data, names);
          const box = document.querySelector('#hunt-restock-box');
          return {
            head: (box.querySelector('h4') || {}).textContent || '',
            said: box.textContent || '',
            rows: [...box.querySelectorAll('.restockrow')].map((r) => ({
              want: (r.querySelector('.rwant') || {}).textContent || '',
              says: (r.querySelector('.rmarket') || {}).textContent || '',
              all: (r.textContent || ''),
              pricey: r.classList.contains('pricey'),
            })),
          };
        }""")
        by = {}
        for r in three["rows"]:
            by[r["want"].split()[0]] = r
        ok("дешевле всего, что видели, на 25%" in by.get("Находка", {}).get("all", ""),
           "находка названа находкой", by.get("Находка", {}).get("all", "")[:70])
        ok("обычная цена" in by.get("Обычная", {}).get("all", ""),
           "обычная цена так и названа", by.get("Обычная", {}).get("all", "")[:60])
        ok("дороже рынка на 100%" in by.get("Дорогая", {}).get("all", "")
           and by.get("Дорогая", {}).get("pricey"),
           "дорогая названа дорогой и приглушена",
           by.get("Дорогая", {}).get("all", "")[:60])
        ok("фойл" in by.get("Фойла", {}).get("all", ""),
           "фойл не сравнивается, и сказано почему",
           by.get("Фойла", {}).get("all", "")[:80])
        ok("слишком разные" in by.get("Разнобой", {}).get("all", ""),
           "разнобой цен не выдаётся за выгоду",
           by.get("Разнобой", {}).get("all", "")[:80])
        ok("ещё не знаем" in by.get("Неизвестная", {}).get("all", ""),
           "про неизвестную цену сказано честно",
           by.get("Неизвестная", {}).get("all", "")[:60])
        ok("на рынке от 120 ₽" in by.get("Находка", {}).get("all", "")
           and "40 объявл." in by.get("Находка", {}).get("all", ""),
           "видно, из чего сложена рыночная цена",
           by.get("Находка", {}).get("all", "")[:80])
        ok("дешевле всего виденного: 1" in three["head"],
           "в заголовке склада считаются только честные находки",
           three["head"])

        # Сравнение по имени смешивает фойл с убитой копией, и на экране
        # оно выглядит так же уверенно, как честное. Счёт таких строк --
        # единственное место, где разница названа.
        said = " ".join(three["said"].split())
        ok("Строк, сравненных по имени, а не по версии: 6" in said,
           "сказано, сколько строк сравнено грубо",
           said[said.find("Строк, сравненных"):][:90])
        ok("Таких цен 6 из 10" in said,
           "сказано, сколько цен ещё не разобрано и чем это лечится",
           said[said.find("Таких цен"):][:120])
        ok("дополнять цены понемногу" in said,
           "названо, что для этого включить",
           said[said.find("включите"):][:90])

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
