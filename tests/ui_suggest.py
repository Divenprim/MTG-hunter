"""Browser check: предложенную карту можно прочесть и положить в колоду.

Четыре жалобы, и все про одно -- программа советует карты, но советом ничего
нельзя сделать:

  * «карты предложений не расширяются, чтобы их можно было прочитать» --
    плитка шириной 72 px, по которой не видно ни текста, ни цены;
  * «карты комбо в колоду нельзя добавить ни в сайдборд, ни в дечку, ни в
    избранное, только в охоту»;
  * «предложка комбо не сообщает, карты легальны в выбранном формате или нет»;
  * «одну дечку делить на версии под разные форматы с доработкой карт».

Сценарий заводит свою колоду и в конце её удаляет. Колода нарочно собрана из
карт, которые не проходят в пионер: на них и проверяется разбор.

    .venv/Scripts/python.exe tests/ui_suggest.py
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = "http://127.0.0.1:8765"
DECK = "UI Предложения"
# Ethereal Haze и Demonic Consultation в пионер не проходят, Thassa's Oracle
# проходит -- и вместе с Consultation составляет комбо, известное Spellbook.
CARDS = [("Ethereal Haze", 4), ("Thassa's Oracle", 1),
         ("Demonic Consultation", 1), ("Fog", 4)]
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def get(path):
    return json.load(urllib.request.urlopen(BASE + path))


SETUP = """async (args) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name.indexOf(args.name) === 0)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
  const made = await fetch('/api/decks', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: args.name, format: 'modern'})}).then(r => r.json());
  await fetch('/api/decks/' + made.deck.id + '/cards', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cards: args.cards.map(
      (c) => ({name: c[0], quantity: c[1], section: 'main'}))})});
  return made.deck.id;
}"""

CLEAN = """async (name) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name.indexOf(name) === 0)) {
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
    deck_id = page.evaluate(SETUP, {"name": DECK, "cards": CARDS})

    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(600)
    page.evaluate("(id) => bdOpen(id)", deck_id)
    page.wait_for_timeout(1200)

    print("=== разбор по форматам ===")
    page.evaluate("() => fmtOpen()")
    page.wait_for_selector(".fmtchip", timeout=30000)
    page.click('.fmtchip[data-fmt="pioneer"]')
    page.wait_for_selector(".fmtblock", timeout=20000)
    check("в пионере видно, что мешает",
          page.locator(".fmtblock").count() >= 2,
          str(page.locator(".fmtblock").count()) + " карт")

    print()
    print("=== предложенную карту можно прочитать ===")
    page.click('.fmtblock [data-replace="Ethereal Haze"]')
    page.wait_for_selector(".fmtcard", timeout=40000)
    check("замены подобрались", page.locator(".fmtcard").count() > 0)

    # Назначение карты -- то, из чего она состоит: у каждого дела видно, сколько
    # таких карт есть в пуле формата.
    jobs = page.eval_on_selector_all(
        ".fmtjobs .jobchip", "els => els.map(e => e.textContent)")
    check("сказано, что карта делает", len(jobs) > 0, "; ".join(jobs[:4]))
    # Ethereal Haze -- это туман; замена одним туманом покрывает его целиком.
    body = page.evaluate("""() => {
      const block = document.querySelector('[data-replace="Ethereal Haze"]')
        .closest('.fmtblock');
      return block.textContent;
    }""")
    check("у замены написано, что она покрывает",
          "делает всё то же" in body or "не делает:" in body,
          body[-80:].replace(chr(10), " "))

    print()
    print("=== отбор по назначению кнопками ===")
    def block_text():
        return page.evaluate("""() => document
          .querySelector('[data-replace="Ethereal Haze"]')
          .closest('.fmtblock').textContent""")

    shown = page.locator(".fmtcard").count()
    check("сначала показано шесть", shown <= 6, str(shown))
    check("и сказано, сколько всего нашлось",
          "показано" in block_text(), block_text()[-40:])

    # «Показать ещё» -- пока отбор не сужен: без него кандидатов сотня.
    page.evaluate("""() => document.querySelector('[data-more-repl]').click()""")
    page.wait_for_function("""() => {
      const r = fmtState.repl['Ethereal Haze'];
      return r && !r.loading && (r.cards || []).length > 6;
    }""", timeout=30000)
    grown = page.evaluate("() => fmtState.repl['Ethereal Haze'].cards.length")
    check("«показать ещё» и правда показывает больше",
          grown > shown, "было %d, стало %d" % (shown, grown))

    page.evaluate("""() => {
      const block = document.querySelector('[data-replace="Ethereal Haze"]')
        .closest('.fmtblock');
      block.querySelector('.jobchip[data-job="fog"]').click();
    }""")
    page.wait_for_function("""() => {
      const r = fmtState.repl['Ethereal Haze'];
      return r && !r.loading && (r.require || []).indexOf('fog') >= 0;
    }""", timeout=30000)
    repl = page.evaluate("() => fmtState.repl['Ethereal Haze']")
    check("отбор по назначению применился",
          (repl.get("require") or []) == ["fog"], str(repl.get("require")))
    check("и остались только туманы",
          all(not any(m["slug"] == "fog" for m in c["misses"])
              for c in repl["cards"]),
          ", ".join(c["name"] for c in repl["cards"][:4]))
    check("кнопка отбора подсвечена",
          page.locator(".jobchip.on").count() == 1)

    check("отобранных меньше, чем было всего",
          (repl.get("total") or 0) < grown or len(repl["cards"]) <= grown,
          "всего с отбором: %s" % repl.get("total"))

    page.evaluate("""() => {
      document.querySelector('[data-jobclear]').click();
    }""")
    page.wait_for_function("""() => {
      const r = fmtState.repl['Ethereal Haze'];
      return r && !r.loading && !(r.require || []).length;
    }""", timeout=30000)
    check("отбор снимается", not page.locator(".jobchip.on").count())

    # Список всё равно упрётся в панель -- поэтому рядом выход в общий поиск,
    # где тот же язык запросов: otag -- это назначение.
    page.evaluate("""() => document.querySelector('[data-search-repl]').click()""")
    page.wait_for_timeout(1200)
    check("«все такие карты в поиске» уводит в поиск с готовым запросом",
          "otag:" in (page.input_value("#search-q") or ""),
          page.input_value("#search-q"))
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(600)

    print()
    print("=== предложенную карту можно прочитать ===")
    first = page.locator(".fmtcard").first
    suggested = first.get_attribute("data-open")
    first.click()
    page.wait_for_selector("#overlay .cardview", timeout=20000)
    body = page.text_content("#modal-body") or ""
    check("плитка открывает окно карты", not page.is_hidden("#overlay"))
    check("и это та самая карта", suggested.split(" //")[0] in body,
          (suggested or "")[:30])
    check("в окне есть текст правил", bool(page.locator("#modal-body .rules").count()))
    check("и легальность по форматам",
          bool(page.locator("#modal-body .legal .chip").count()))

    print()
    print("=== из окна карты она кладётся в колоду ===")
    check("в окне есть кнопки «в колоду»",
          page.locator("#modal-body .add-deck").count() == 3)
    page.click('#modal-body .add-deck[data-section="side"]')
    page.wait_for_function("""(name) => (bdDeck.cards || []).some(
      (c) => c.name === name && c.section === 'side')""",
      arg=suggested, timeout=20000)
    check("карта легла в сайдборд", True)
    page.click("#modal-close")

    print()
    print("=== меню предложения ===")
    page.wait_for_selector(".fmtcard", timeout=20000)
    page.evaluate("""() => {
      document.querySelectorAll('.fmtcard [data-suggest]')[1].click();
    }""")
    page.wait_for_selector(".cardmenu", timeout=20000)
    items = page.text_content(".cardmenu") or ""
    for want in ("Открыть карту", "В основную колоду", "В сайдборд",
                 "В «возможно»", "В избранное", "В охоту"):
        check("в меню есть «%s»" % want, want in items)
    check("и «поставить вместо» той карты, у которой меню открыли",
          "Поставить вместо" in items)

    page.evaluate("""() => {
      [...document.querySelectorAll('.cmitem')]
        .find(b => b.textContent.indexOf('В «возможно»') === 0).click();
    }""")
    page.wait_for_function("""() => (bdDeck.cards || []).some(
      (c) => c.section === 'maybe')""", timeout=20000)
    check("«возможно» и правда наполняется", True)

    print()
    print("=== вариант колоды под другой формат ===")
    page.evaluate("() => fmtLoad(true)")
    # Формат называется явно. Раньше сценарий полагался на то, что открытым
    # остался пионер, выбранный в начале; иногда раскрытым оказывался модерн --
    # собственный формат колоды, -- и переделывать было нечего: план не
    # появлялся, а сценарий ждал его целую минуту и падал.
    page.wait_for_selector(".fmtchip", timeout=20000)
    page.evaluate("() => { fmtState.open = 'pioneer'; fmtRender(); }")
    page.wait_for_selector('[data-adapt]', timeout=20000)
    label = page.locator("[data-adapt]").first.text_content() or ""
    check("переделка предлагается именно в пионер", "ионер" in label, label[:60])
    page.click("[data-adapt]")
    page.wait_for_selector(".fmtplan, .fmtvariant .good", timeout=60000)
    plan = page.evaluate("() => fmtState.plan")
    check("план посчитан для пионера", plan and plan["format"] == "pioneer",
          str((plan or {}).get("format")))
    check("в плане есть замены", bool((plan or {}).get("swaps")),
          str(len((plan or {}).get("swaps") or [])) + " шт.")
    check("кнопка завести вариант появилась",
          page.locator("[data-variant]").count() == 1)
    # Главный вопрос к переделке: переживёт ли её то, чем колода выигрывает.
    check("сказано, чем колода выигрывает",
          "Чем выигрывает" in (page.text_content("#bd-formats") or ""))
    check("и что станет с замыслом после переделки",
          page.locator(".fmtintent").count() == 1,
          str((plan or {}).get("intent")))
    # Способы выиграть показаны числами -- и до, и после переделки.
    check("способы выиграть посчитаны числами",
          page.locator(".fmtwin .routechip").count() > 0,
          str(page.locator(".fmtwin .routechip").count()))
    check("и видно, что с ними станет",
          page.locator(".fmtroutes.was .routechip").count() > 0)

    before = len(get("/api/decks")["decks"])
    page.click("[data-variant]")
    page.wait_for_function("""(n) => bdDecks.length > n""", arg=before, timeout=60000)
    decks = get("/api/decks")["decks"]
    mine = [d for d in decks if d["name"].startswith(DECK)]
    variant = [d for d in mine if d["id"] != deck_id]
    check("вариант заведён отдельной колодой", len(variant) == 1,
          "; ".join(d["name"] for d in mine))

    if variant:
        v = variant[0]
        src = [d for d in mine if d["id"] == deck_id][0]
        check("у варианта формат того формата", v["format"] == "pioneer", v["format"])
        check("обе колоды в одном семействе",
              bool(v.get("family")) and v.get("family") == src.get("family"),
              str(v.get("family")))
        vd = get("/api/decks/" + v["id"])["deck"]
        names = {c["name"] for c in vd["cards"] if c["section"] in ("main", "side")}
        check("мешавшая карта из колоды ушла", "Ethereal Haze" not in names)
        check("а в исходной колоде она осталась",
              any(c["name"] == "Ethereal Haze"
                  for c in get("/api/decks/" + deck_id)["deck"]["cards"]))
        left = get("/api/decks/" + v["id"] + "/formats")
        pioneer = [f for f in left["formats"] if f["format"] == "pioneer"][0]
        check("вариант в пионере чище исходной колоды",
              pioneer["blocked_copies"] == 0,
              "мешает копий: %d" % pioneer["blocked_copies"])

    print()
    print("=== комбо: легальность и что с картой делать ===")
    page.evaluate("(id) => bdOpen(id)", deck_id)
    page.wait_for_timeout(800)
    page.evaluate("() => cbOpen()")
    page.wait_for_selector("#cb-body .cbcombo, #cb-body .meta", timeout=90000)
    combos = page.locator("#cb-body .cbcombo").count()
    check("комбо в колоде нашлись", combos > 0, str(combos))

    if combos:
        meta = page.text_content("#cb-meta") or ""
        check("сказано, по какому формату считается легальность",
              "легальность по формату" in meta, meta[-60:])
        check("карта вне пула помечена",
              page.locator("#cb-body .cbcard.illegal").count() > 0)
        check("и у комбо написано, сколько таких",
              "вне пула" in (page.text_content("#cb-body") or ""))

        page.evaluate("""() => {
          document.querySelector('#cb-body .cbcard [data-cb="menu"]').click();
        }""")
        page.wait_for_selector(".cardmenu", timeout=20000)
        items = page.text_content(".cardmenu") or ""
        check("у карты комбо есть меню с колодой и избранным",
              "В сайдборд" in items and "В избранное" in items and
              "В охоту" in items)
        page.keyboard.press("Escape")

        page.evaluate("""() => {
          document.querySelector('#cb-body .cbcard b').click();
        }""")
        page.wait_for_selector("#overlay .cardview", timeout=20000)
        check("карта комбо открывается целиком", not page.is_hidden("#overlay"))
        # Окно карты зовут из окна комбо -- и оно должно оказаться НАД ним, а не
        # под. Раньше все оверлеи стояли на одном уровне, и карта открывалась в
        # никуда: нажать в ней было нечего.
        on_top = page.evaluate("""() => {
          const btn = document.getElementById('modal-close');
          const r = btn.getBoundingClientRect();
          const at = document.elementFromPoint(r.x + r.width / 2, r.y + r.height / 2);
          return !!at && (at === btn || btn.contains(at));
        }""")
        check("и оказывается поверх окна комбо, а не под ним", on_top)
        page.click("#modal-close")

        # Отбор по легальности: комбо с картой вне пула прячется.
        shown = page.locator("#cb-body .cbcombo").count()
        page.evaluate("() => document.getElementById('cb-legal').click()")
        page.wait_for_timeout(400)
        check("отбор «только легальные» убирает лишние комбо",
              page.locator("#cb-body .cbcombo").count() < shown,
              "было %d, стало %d" % (shown, page.locator("#cb-body .cbcombo").count()))
        page.evaluate("() => document.getElementById('cb-legal').click()")
    page.evaluate("() => cbClose()")

    print()
    print("=== уборка ===")
    page.evaluate(CLEAN, DECK)
    check("свои колоды удалены",
          not [d for d in get("/api/decks")["decks"] if d["name"].startswith(DECK)])
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
