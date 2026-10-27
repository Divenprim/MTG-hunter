"""Browser check: выборка по архетипу, копии и сайдборд.

Проверяется то, ради чего выборка переписана. У 60-карточной колоды выборка
по формату отвечала не про неё: «весь модерн» -- это все архетипы разом, и
соседями 8-Rack оказывались эльфы. Теперь колоду опознают её собственные
карты, и у Archidekt спрашиваются колоды, где эти карты стоят.

Что должно быть на экране:

  * отметки карт -- с подсказкой, какие отмечены и почему;
  * возраст списков сказан вслух: по просмотрам наверх лезут колоды
    позапрошлого сезона, и числа по ним стоят другого;
  * «по сколько копий» -- вопрос, которого в программе не было вовсе;
  * «что держат в сайде» -- пятнадцать карт, которых не видел ни один
    список «чего не хватает».

Наружу сценарий не ходит: кнопку «собрать выборку» он не нажимает, а читает
то, что уже лежит в кеше песочницы.

    MTGH_UI_BASE=http://127.0.0.1:8773 .venv/Scripts/python.exe tests/ui_sample_cards.py
"""

import os
from playwright.sync_api import sync_playwright

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
DECK_NAME = "UI Архетип"
# Карты подобраны под выборку, уже лежащую в кеше: две первые -- те самые,
# по которым она собрана.
MAIN = [("Ethereal Haze", 4), ("Arboreal Grazer", 4), ("Fog", 4),
        ("Growth Spiral", 4), ("Explore", 3), ("Island", 10)]
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

    print("=== колода, по которой спрашиваем ===")
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

    page.click('.tab[data-tab="builder"]')
    page.wait_for_function(
        "() => document.querySelector('#panel-builder.active') !== null",
        timeout=20000)
    page.evaluate("(id) => bdOpen(id)", deck_id)
    page.wait_for_function(
        "() => !document.querySelector('#bd-editor').hidden", timeout=20000)
    page.wait_for_timeout(600)

    print()
    print("=== вкладка «Под ваш состав» ===")
    page.dispatch_event('#bd-actions button[data-act="recommend"]', "click")
    page.wait_for_function(
        "() => !document.querySelector('#rec-overlay').hidden", timeout=20000)
    page.locator('#rec-tabs [data-rectab="cooccur"]').click()
    page.wait_for_function(
        "() => document.querySelector('.cochips') !== null", timeout=30000)

    chips = page.evaluate("""() => [...document.querySelectorAll('.chiprow .chip')]
        .map((b) => ({name: b.dataset.sign, on: b.classList.contains('on')}))""")
    check("карты колоды предложены как отметки", len(chips) >= 4,
          "%d чипов" % len(chips))
    picked = [c["name"] for c in chips if c["on"]]
    check("две отмечены по догадке", len(picked) == 2, str(picked))
    hint = " ".join((page.locator(".cochips").text_content() or "").split())
    check("сказано, что это догадка", "по догадке" in hint, hint[:90])
    check("сказано, что без отметок берётся весь формат",
          "весь формат" in hint, hint[:140])

    print()
    print("=== отметки совпали с тем, что лежит в кеше ===")
    page.wait_for_function(
        "() => coState && coState.kind === 'cards'", timeout=30000)
    state = page.evaluate("() => coState")
    check("выборка спрашивается по картам", state.get("kind") == "cards",
          str(state.get("kind")))
    check("карты выборки -- отмеченные",
          sorted(state.get("cards") or []) == sorted(picked),
          "%s / %s" % (state.get("cards"), picked))
    check("колоды в кеше найдены", (state.get("decks") or 0) > 0,
          "колод: %s" % state.get("decks"))

    if state.get("decks"):
        page.wait_for_function(
            "() => document.querySelector('#rec-cooccur-body')"
            ".textContent.indexOf('считаю') < 0", timeout=60000)
        body = " ".join(
            (page.locator("#rec-cooccur-body").text_content() or "").split())

        print()
        print("=== про выборку сказано честно ===")
        check("возраст списков назван", "самому старому" in body, body[:120])
        check("отсев до скачивания объяснён",
              "Не скачивалось вовсе" in body, body[:200])
        check("сказано, у скольких известен сайд",
              "Сайдборд известен" in body, body[:260])

        print()
        print("=== по сколько копий ===")
        copies = page.evaluate(
            "() => (coData && coData.copies && coData.copies.cards) || []")
        check("вопрос про копии задан", "По сколько копий" in body, body[:60])
        check("строки о копиях есть", len(copies) > 0, str(copies[:2]))
        if copies:
            row = copies[0]
            check("сказано и ваше число, и обычное",
                  row["mine"] != row["usual"],
                  "%s: у вас %s, обычно %s" % (row["name"], row["mine"],
                                               row["usual"]))
            check("кнопка добора показывает, сколько брать",
                  page.locator("[data-copies]").count() > 0
                  or row["diff"] < 0,
                  "кнопок: %d" % page.locator("[data-copies]").count())

        print()
        print("=== что держат в сайде ===")
        side = page.evaluate(
            "() => (coData && coData.side) || {}")
        check("сайдборд соседей посчитан", (side.get("known") or 0) > 0,
              "колод с сайдом: %s" % side.get("known"))
        check("строки сайда есть", len(side.get("cards") or []) > 0,
              str((side.get("cards") or [])[:2]))
        check("карта из вашего сайда помечена как ваша",
              any(c["mine"] for c in (side.get("cards") or [])),
              str([c["name"] for c in (side.get("cards") or []) if c["mine"]]))

        page.screenshot(path="tests/ui_sample_cards.png", full_page=True)
        # Новые блоки лежат ниже списка подсказок -- прокручиваем панель,
        # иначе на снимке их не видно и смотреть будет не на что.
        page.evaluate("""() => { const b = document.querySelector('#rec-cooccur-body');
            b.scrollTop = b.scrollHeight; }""")
        page.wait_for_timeout(300)
        spill = page.evaluate("""() => {
          const modal = document.querySelector('#rec-modal').getBoundingClientRect();
          const body = document.querySelector('#rec-cooccur-body').getBoundingClientRect();
          return Math.round(body.bottom - modal.bottom);
        }""")
        check("содержимое не вылезает за окно", spill <= 2,
              "на %d px ниже окна" % spill)
        page.screenshot(path="tests/ui_sample_cards_tail.png")

        print()
        print("=== на чём посчитано ===")
        near = page.evaluate("() => (coData && coData.neighbours) || []")
        check("соседи названы поимённо", len(near) > 0, "%d колод" % len(near))
        if near:
            check("у соседа есть ссылка на Archidekt",
                  near[0]["url"].startswith("https://archidekt.com/decks/"),
                  near[0]["url"])
            check("сказано, сколько карт общих", near[0]["shared"] > 0,
                  "общих: %s из %s" % (near[0]["shared"], near[0]["cards"]))
        check("список соседей свёрнут, а не вываливается",
              page.locator(".conear").count() == 1
              and not page.locator(".conear").first.evaluate("(e) => e.open"))

        print()
        print("=== обновление выборки ===")
        check("кнопка «Обновить» есть",
              page.locator("#rec-sample-refresh").count() == 1)
        # Нажимать её целиком нельзя: следом она идёт качать с Archidekt, а
        # сценарию наружу ходить незачем. Проверяем саму чистку -- она
        # никуда не ходит.
        # Те же карты, что отмечены на экране: без них чистилась бы выборка
        # по формату -- другая, пустая, и проверка бы ничего не значила.
        got = page.evaluate("""async (id) => {
          return await fetch('/api/cooccur/refresh', {method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({deck_id: id, cards: coPicked})
          }).then(r => r.json());
        }""", deck_id)
        check("обновление отвечает, что выброшено",
              "dropped" in got and "undated" in got,
              "выброшено %s, без даты %s" % (got.get("dropped"),
                                             got.get("undated")))
        check("свежие колоды остались",
              (got.get("decks") or 0) > 0, "колод: %s" % got.get("decks"))
        check("выборка после чистки читается как прежде",
              page.evaluate("""async (id) => {
                const s = await fetch('/api/cooccur/status?deck_id=' + id +
                  '&cards=' + encodeURIComponent(coPicked.join('|')))
                  .then(r => r.json());
                return s.decks;
              }""", deck_id) == got.get("decks"))

        print()
        print("=== снятие отметок возвращает к формату ===")
        page.locator("[data-sign-clear]").first.click()
        page.wait_for_function(
            "() => coState && coState.kind === 'format'", timeout=30000)
        check("без отметок выборка идёт по формату",
              page.evaluate("() => coState.kind") == "format")

    print()
    print("=== уборка ===")
    page.locator("#rec-close").click()
    page.wait_for_timeout(300)
    left = sweep(page)
    check("своя колода удалена, чужие не тронуты", left == 0,
          "осталось с этим именем: %d" % left)

    print()
    check("без ошибок в консоли", not errors, "; ".join(errors[:3]))
    browser.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL ARCHETYPE CHECKS PASSED")
