"""Browser check: сайдборд в нехватках и в покупках, цена по версиям.

До сих пор сайдборда не видел никто: «нехватки» считали мейн, покупки
складывали его копии в общий счёт молча, а цена лежала одним числом на имя
-- и по «700 ₽» было не понять, убитая это копия, фойл или обычная карта.

Что должно быть на экране:

  * в «Нехватках» -- разговор про сайд: сколько слотов занято, на что
    ответа нет и чем его закрыть, кнопкой «+ в сайд», а не «+ в колоду»;
  * в «Что купить первым» -- пометка «только в сайд» и флажок, который
    убирает сайдборды из счёта;
  * в окне карты -- что именно записано: печать, фойл, состояние.

Наружу не ходит: в песочнице topdeck подменён выдумкой.

    MTGH_UI_BASE=http://127.0.0.1:8773 .venv/Scripts/python.exe tests/ui_sideboard.py
"""

import os
from playwright.sync_api import sync_playwright

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
DECK_NAME = "UI Сайд"
MAIN = [("Lightning Bolt", 4), ("Monastery Swiftspear", 4), ("Mountain", 20)]
SIDE = [("Smash to Smithereens", 3)]
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

    page.click('.tab[data-tab="builder"]')
    page.wait_for_function(
        "() => document.querySelector('#panel-builder.active') !== null",
        timeout=20000)
    page.evaluate("(id) => bdOpen(id)", deck_id)
    page.wait_for_function(
        "() => !document.querySelector('#bd-editor').hidden", timeout=20000)
    page.wait_for_timeout(500)

    print()
    print("=== сайдборд в нехватках ===")
    page.click('#bd-actions button[data-act="gaps"]')
    page.wait_for_function(
        "() => document.querySelector('.gapwrap-side') !== null", timeout=60000)
    side = " ".join(
        (page.locator(".gapwrap-side").text_content() or "").split())
    check("сказано, сколько слотов занято", "Занято 3 из 15" in side,
          side[:70])
    check("сказано, на что ответа нет", "Без ответа:" in side, side[:120])
    check("объяснено, зачем это вообще",
          "второй и третьей партии" in side, side[:200])

    data = page.evaluate("() => (gapData && gapData.sideboard) || {}")
    blocks = {b["key"]: b for b in (data.get("blocks") or [])}
    check("ответ, который есть, засчитан",
          blocks.get("artifact", {}).get("in_side") == 3,
          "против артефактов: %s" % blocks.get("artifact", {}).get("in_side"))
    check("на остальное предложены карты",
          any(b.get("candidates") for b in blocks.values()),
          "вопросов без ответа: %s" % data.get("missing"))

    print()
    print("=== кнопка кладёт карту именно в сайд ===")
    add = page.locator(".gapwrap-side .gapadd").first
    name = add.evaluate("(b) => b.dataset.add")
    check("кнопка зовётся «+ в сайд»",
          "в сайд" in (add.text_content() or ""), add.text_content())
    add.click()
    page.wait_for_timeout(1200)
    where = page.evaluate("""async ([id, card]) => {
      const r = await fetch('/api/decks/' + id).then(x => x.json());
      const row = (r.deck.cards || []).find((c) => c.name === card);
      return row ? row.section : 'нет';
    }""", [deck_id, name])
    check("карта легла в сайдборд", where == "side", "%s → %s" % (name, where))

    print()
    print("=== сайд в покупках ===")
    page.click('.tab[data-tab="collection"]')
    page.wait_for_timeout(400)
    page.click('#coll-tabs [data-coll="buy"]')
    page.wait_for_function(
        "() => document.querySelector('#buy-body').textContent.indexOf('считаю') < 0",
        timeout=60000)
    rows = page.evaluate("() => (buyData && buyData.cards) || []")
    side_rows = [r for r in rows if r.get("side")]
    check("покупки знают про сайдборд", bool(side_rows),
          "строк с сайдом: %d" % len(side_rows))
    if side_rows:
        check("видно, сколько копий уходит в сайд",
              any(r["side_only"] for r in side_rows),
              str([r["name"] for r in side_rows if r["side_only"]][:3]))
    body = " ".join((page.locator("#buy-summary").text_content() or "").split())
    check("в итоге сказано про сайдборды", "в сайдборды" in body, body[:140])
    check("пометка видна в строке",
          page.locator(".buyside").count() > 0,
          "пометок: %d" % page.locator(".buyside").count())

    before = len(rows)
    page.check("#buy-noside")
    page.wait_for_function(
        "() => document.querySelector('#buy-body').textContent.indexOf('считаю') < 0",
        timeout=60000)
    page.wait_for_timeout(400)
    after = page.evaluate("() => (buyData && buyData.cards) || []")
    check("флажок убирает сайдборды из счёта",
          not any(r.get("side") for r in after),
          "было %d строк, стало %d" % (before, len(after)))
    page.uncheck("#buy-noside")

    print()
    print("=== цена чего именно ===")
    WANT = ["Lightning Bolt", "Monastery Swiftspear", "Smash to Smithereens",
            "Mountain"]
    asked = page.evaluate("""async (names) => {
      const r = await fetch('/api/prices', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({names: names, only_missing: false})
      }).then(x => x.json());
      return r.report || {};
    }""", WANT)
    check("цены узнаны (в песочнице — выдуманные)",
          (asked.get("updated") or 0) > 0, str(asked)[:80])

    tracks = {}
    for one in WANT:
        tracks[one] = page.evaluate("""async (name) => {
          return await fetch('/api/prices/history?name=' +
            encodeURIComponent(name)).then(x => x.json());
        }""", one)
    split = {k: (t.get("variants") or []) for k, t in tracks.items()}
    check("цена разложена по версиям",
          any(len(v) > 1 for v in split.values()),
          str({k: len(v) for k, v in split.items()}))
    # Фойл стоит дороже и версия у него своя: смешать их -- это и есть
    # «экономия 3990».
    foiled = [k for k, v in split.items() if any(x["foil"] for x in v)]
    check("фойл отделён от обычной", bool(foiled), str(foiled))
    if foiled:
        rows = split[foiled[0]]
        foil = [x for x in rows if x["foil"]][0]
        plain = [x for x in rows if not x["foil"]]
        check("фойл не задаёт цену обычной копии",
              bool(plain) and tracks[foiled[0]]["current"]["rub_plain"]
              == min(x["rub_min"] for x in plain),
              "фойл %s, обычная %s" % (foil["rub_min"],
                                       tracks[foiled[0]]["current"]["rub_plain"]))
    shown = foiled[0] if foiled else WANT[0]
    page.evaluate("(n) => openCardByName(n)", shown)
    page.wait_for_function(
        "() => !document.querySelector('#overlay').hidden", timeout=20000)
    page.wait_for_timeout(1200)
    check("в окне карты есть разбор по версиям",
          page.locator(".pricevars").count() > 0)
    if page.locator(".pricevars").count():
        page.locator(".pricevars summary").first.click()
        page.wait_for_timeout(200)
        text = " ".join(
            (page.locator(".pricevars").first.text_content() or "").split())
        check("версии подписаны", "фойл" in text, text[:120])
        page.screenshot(path="tests/ui_sideboard_price.png")
    page.keyboard.press("Escape")

    print()
    print("=== уборка ===")
    left = sweep(page)
    check("своя колода удалена", left == 0, "осталось: %d" % left)
    check("без ошибок в консоли", not errors, "; ".join(errors[:3]))
    browser.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL SIDEBOARD CHECKS PASSED")
