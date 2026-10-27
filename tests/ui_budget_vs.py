"""Browser check: деньги, сравнение с соседом и сайдборд против формата.

Три вопроса, на которые программа до сих пор не отвечала:

  * **«есть пять тысяч -- что брать».** Список покупок на сорок пять тысяч
    целиком не покупают, и порядок строк отвечает на другой вопрос;
  * **«чем мой список отличается от вот этого».** Список соседей давал
    ссылку на чужой сайт -- дальше человек сверял семьдесят пять строк
    глазами, и вторая половина разницы («чего нет у них») терялась совсем;
  * **«на что в этом формате вообще отвечают в сайде».** Семь общих
    вопросов одинаковы для модерна и паупера; колода с сорока пятью картами
    дискарда получала «без ответа 7 из 7».

Наружу сценарий не ходит: выборка читается из кеша песочницы, цены в ней
выдуманные, продавцы начинаются с «ПРОВЕРКА».

    MTGH_UI_BASE=http://127.0.0.1:8773 .venv/Scripts/python.exe tests/ui_budget_vs.py
"""

import os
from playwright.sync_api import sync_playwright

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
DECK_NAME = "UI Деньги"
# Те же карты, что и в проверке выборки: под них в кеше песочницы уже лежат
# чужие колоды, и спрашивать Archidekt заново незачем.
MAIN = [("Ethereal Haze", 4), ("Arboreal Grazer", 4), ("Fog", 4),
        ("Growth Spiral", 4), ("Explore", 3), ("Island", 10),
        # Карта не из этого архетипа -- нарочно: без неё «чего нет у них»
        # оказывается пустым, и вторая половина сравнения не проверяется.
        ("Spore Frog", 2)]
SIDE = [("Veil of Summer", 2)]
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label +
          (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def sweep(page):
    return page.evaluate("""async (name) => {
      const r = await fetch('/api/decks').then(x => x.json());
      for (const d of r.decks.filter(d => d.name === name)) {
        await fetch('/api/cooccur/cards', {method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({deck_id: d.id, cards: []})});
        await fetch('/api/decks/' + d.id, {method: 'DELETE'});
      }
      const after = await fetch('/api/decks').then(x => x.json());
      return after.decks.filter(d => d.name === name).length;
    }""", DECK_NAME)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1150}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")
    sweep(page)

    deck_id = page.evaluate("""async ([name, main, side]) => {
      const mk = await fetch('/api/decks', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: name, format: 'modern'})}).then(r => r.json());
      const id = (mk.deck || {}).id;
      const cards = main.map(([n, q]) => ({name: n, quantity: q, section: 'main'}))
        .concat(side.map(([n, q]) => ({name: n, quantity: q, section: 'side'})));
      await fetch('/api/decks/' + id + '/cards', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({cards: cards})});
      return id;
    }""", [DECK_NAME, MAIN, SIDE])
    check("колода заведена", bool(deck_id), str(deck_id))

    print()
    print("=== есть столько-то рублей ===")
    page.click('.tab[data-tab="collection"]')
    page.wait_for_timeout(400)
    page.click('#coll-tabs [data-coll="buy"]')
    page.wait_for_function(
        "() => document.querySelector('#buy-body').textContent.indexOf('считаю') < 0",
        timeout=90000)
    before = page.evaluate("() => (buyData && buyData.cards || []).length")
    check("список покупок посчитан", before > 0, "строк: %d" % before)
    check("без бюджета ничего не выбрано",
          not page.evaluate("() => (buyData.budget || {}).rub"),
          str(page.evaluate("() => buyData.budget")))
    totals = page.evaluate("() => buyData.totals")
    check("сказано, у скольких цен нет разбора по версиям",
          "no_split" in totals, "без разбора: %s" % totals.get("no_split"))

    page.fill("#buy-budget", "3000")
    page.wait_for_function(
        "() => (buyData && buyData.budget && buyData.budget.rub) === 3000",
        timeout=90000)
    page.wait_for_timeout(300)
    pick = page.evaluate("() => buyData.budget")
    check("набор под эти деньги подобран", (pick.get("cards") or 0) > 0,
          "%s назв. на %s ₽" % (pick.get("cards"), pick.get("spent")))
    check("в деньги уложились", (pick.get("spent") or 0) <= 3000,
          "потрачено %s из 3000" % pick.get("spent"))
    check("сказано, сколько стоит следующее по списку",
          (pick.get("next_rub") or 0) > 0,
          "следующее: %s ₽" % pick.get("next_rub"))
    marked = page.locator(".buyrow.inbudget").count()
    check("строки набора помечены в самом списке", marked > 0,
          "помечено строк: %d" % marked)
    check("пометка названа словом",
          page.locator(".buytake").count() > 0,
          "пометок «брать»: %d" % page.locator(".buytake").count())
    head = " ".join((page.locator("#buy-summary").text_content() or "").split())
    check("в сводке сказано, что берём и за сколько",
          "берём" in head and "₽" in head, head[-160:])

    # Карта берётся целиком или никак -- иначе «достраивает колоду» ложь.
    cards = page.evaluate("() => buyData.cards")
    taken = [c for c in cards if c.get("in_budget")]
    check("в наборе только карты с известной ценой",
          all(c["price"] for c in taken),
          str([c["name"] for c in taken if not c["price"]][:3]))

    page.fill("#buy-budget", "")
    page.wait_for_function(
        "() => !(buyData && buyData.budget && buyData.budget.rub)",
        timeout=90000)
    check("пустое поле снимает подбор",
          page.locator(".buyrow.inbudget").count() == 0)

    print()
    print("=== сайдборд сверен с чужими сайдбордами ===")
    page.click('.tab[data-tab="builder"]')
    page.wait_for_function(
        "() => document.querySelector('#panel-builder.active') !== null",
        timeout=20000)
    page.evaluate("(id) => bdOpen(id)", deck_id)
    page.wait_for_function(
        "() => !document.querySelector('#bd-editor').hidden", timeout=20000)
    page.wait_for_timeout(400)
    # Выборка по этой колоде -- та, что в кеше: отмечаем её карты, иначе
    # сервер возьмёт формат, а выборки по формату в песочнице нет.
    page.evaluate("""async ([id, cards]) => {
      await fetch('/api/cooccur/cards', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({deck_id: id, cards: cards})});
    }""", [deck_id, ["Arboreal Grazer", "Ethereal Haze"]])

    page.click('#bd-actions button[data-act="gaps"]')
    page.wait_for_function(
        "() => document.querySelector('.gapwrap-side') !== null", timeout=90000)
    side = " ".join((page.locator(".gapwrap-side").text_content() or "").split())
    data = page.evaluate("() => (gapData && gapData.sideboard) || {}")
    check("сайдборды соседей прочитаны",
          (data.get("others") or {}).get("known", 0) > 0,
          "колод с сайдом: %s" % (data.get("others") or {}).get("known"))
    check("это сказано на экране", "Сверено с сайдбордами" in side,
          side[:200])
    blocks = data.get("blocks") or []
    check("у каждого вопроса посчитано, держат ли ответ соседи",
          all("others" in b for b in blocks), "вопросов: %d" % len(blocks))
    check("вопрос, на который отвечают чаще всего, стоит первым",
          bool(blocks) and all(
              (blocks[0]["others"].get("share") or 0)
              >= (b["others"].get("share") or 0)
              for b in blocks if not b["in_side"]),
          str([(b["key"], b["others"].get("share")) for b in blocks[:3]]))
    check("доля соседей показана в строке вопроса",
          page.locator(".gapothers").count() > 0,
          "пометок: %d" % page.locator(".gapothers").count())
    if data.get("by_main"):
        check("ответ из мейна не назван отсутствующим",
              "закрыто мейном" in side, side[:220])

    print()
    print("=== сравнение с одной чужой колодой ===")
    page.dispatch_event('#bd-actions button[data-act="recommend"]', "click")
    page.wait_for_function(
        "() => !document.querySelector('#rec-overlay').hidden", timeout=20000)
    page.locator('#rec-tabs [data-rectab="cooccur"]').click()
    page.wait_for_function(
        "() => document.querySelector('.conear') !== null", timeout=90000)
    page.locator(".conear summary").first.click()
    page.wait_for_timeout(200)
    vs = page.locator("[data-vs]")
    check("у каждого соседа есть кнопка сравнения", vs.count() > 0,
          "кнопок: %d" % vs.count())
    note = " ".join((page.locator("#rec-cooccur-body").text_content() or "").split())
    check("про сравнение с форматом сказано прямо",
          "С форматом сравнить не с чем" in note
          or "Сверено с выборкой по формату" in note,
          note[:200])

    vs.first.click()
    page.wait_for_function(
        "() => document.querySelector('.covs') !== null", timeout=60000)
    page.wait_for_timeout(300)
    body = " ".join((page.locator(".covs").text_content() or "").split())
    check("сказано, сколько карт общих", "Общих карт" in body, body[:120])
    check("показано, чего нет у вас", "Есть у них, нет у вас" in body,
          body[:200])
    # Вторая половина -- то, ради чего это и делалось: карта, которой нет ни
    # у одного соседа, либо находка, либо то, от чего все отказались.
    mine_only = page.evaluate("""() => [...document.querySelectorAll('.covs h4')]
        .map((h) => h.textContent).join(' | ')""")
    check("показано, чего нет у них", "Есть у вас, нет у них" in mine_only,
          mine_only[:160])
    check("про свои карты сказано, играют ли их соседи",
          "ни у одного соседа" in body or "есть у " in body, body[-300:])
    page.screenshot(path="tests/ui_budget_vs.png")

    print()
    print("=== уборка ===")
    page.keyboard.press("Escape")
    left = sweep(page)
    check("своя колода удалена", left == 0, "осталось: %d" % left)
    check("без ошибок в консоли", not errors, "; ".join(errors[:3]))
    browser.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL BUDGET/VS CHECKS PASSED")
