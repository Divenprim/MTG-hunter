"""Browser check: ход цен, названная цена и «дёшево вообще».

Замеры цен программа копила давно, а показывала из них одно число в одном
окне -- «70 ₽ (было 90)». Проверяется то, что из них наконец сделано:

  * **список изменений по всем ценам сразу** -- под оценкой коллекции,
    подешевевшее вперёд;
  * **цена, по которой человек готов взять карту**: назвал -- и дальше
    следит программа, а не память. Пришла -- сказано «ваша цена» и
    «Дождались»; не пришла -- сказано, сколько сверху;
  * **коридор, в котором цена ходила**: «дешевле, чем когда-либо видели»
    против «обычная для неё цена». Три замера -- условие, а не
    украшение: по двум точкам виден не ход цены, а то, что её спросили
    дважды, и тогда в строке пусто.

Наружу сценарий не ходит: цены в песочнице выдуманные, тему продавца
отдаёт обезличенный образец из tests/data.

    MTGH_UI_BASE=http://127.0.0.1:8773 .venv/Scripts/python.exe tests/ui_prices.py
"""

import os

from playwright.sync_api import sync_playwright

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
FOLDER = "UI Цены"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label +
          (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def skip(label, why):
    """Проверять нечего -- и это не провал.

    Всё в этом сценарии растёт из накопленных замеров цены. В песочнице
    они есть, в свежей копии (сборка релиза) -- ни одного, и требовать
    там «подешевело на столько-то» значит требовать прошлого, которого
    не было. Пропуск называется вслух, чтобы его не приняли за проверку.
    """
    print("  --    " + label + " -- " + why)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1150}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")

    # Своя папка: чужие трогать нельзя, а цель по цене живёт у карточки.
    page.evaluate("""async (name) => {
      const doc = await fetch('/api/favourites').then(r => r.json());
      for (const f of doc.favourites.folders.filter(f => f.name === name)) {
        await fetch('/api/favourites/folders/' + f.id, {method: 'DELETE'});
      }
    }""", FOLDER)

    print("=== что изменилось в ценах ===")
    moves = page.evaluate("() => fetch('/api/prices/moves').then(r => r.json())")
    digest = moves["digest"]
    HAVE_MOVES = digest["cheaper"] + digest["dearer"] > 0
    check("маршрут движений отвечает", "digest" in moves and "goals" in moves,
          "подешевело %s, подорожало %s" % (digest["cheaper"], digest["dearer"]))

    if not HAVE_MOVES:
        skip("ход цен", "в этой копии цену ни разу не спрашивали дважды")
    else:
        check("у каждой строки есть «было» и «стало»",
              all(m["prev_rub_min"] and m["rub_min"] for m in moves["moves"][:5]),
              str([(m["prev_rub_min"], m["rub_min"]) for m in moves["moves"][:3]]))
        check("подешевевшее стоит вперёд", moves["moves"][0]["move"] < 0,
              "первое движение: %s" % moves["moves"][0]["move"])

        page.click('.tab[data-tab="collection"]')
        page.wait_for_selector("#coll-moves:not([hidden])", timeout=60000)
        said = " ".join((page.text_content("#coll-moves") or "").split())
        check("блок виден в учёте коллекции", bool(said), said[:90])
        check("сказано, сколько подешевело и подорожало",
              "подешевело" in said and "подорожало" in said, said[:120])
        check("сказано, что наружу ничего не спрашивается",
              "наружу" in said, said[:160])
        rows = page.locator("#coll-moves .moverow").count()
        check("строки изменений показаны", rows > 0, "строк: %d" % rows)

    if not HAVE_MOVES:
        # Без цен проверять цель не на чем: «дождались» без цены не бывает.
        skip("цена, по которой готов взять", "записанных цен нет")
        skip("дёшево сегодня или дёшево вообще", "замеров нет")
        real = [e for e in errors if "favicon" not in e.lower()]
        check("ошибок в консоли нет", not real, "; ".join(real[:2]))
        browser.close()
        print()
        print("ИТОГ: %s" % ("всё сошлось" if not FAIL
                            else "не сошлось: " + ", ".join(FAIL)))
        raise SystemExit(1 if FAIL else 0)

    print()
    print("=== на какой день эти цены ===")
    # Сумма в рублях собиралась по одной карте в разные дни, и до сих пор
    # стояла на экране как сегодняшняя. Возраст снимка -- часть ответа.
    page.click('.tab[data-tab="collection"]')
    page.wait_for_selector("#coll-worth:not([hidden])", timeout=60000)
    worth = " ".join((page.text_content("#coll-worth") or "").split())
    if "по замерам на" not in worth:
        skip("возраст цен", "рублёвых цен в этой копии нет")
    else:
        check("сказано, на какой день посчитана сумма в рублях",
              "эта сумма — по замерам на" in worth,
              worth[worth.find("эта сумма"):][:110])
        check("возраст назван словами, а не отметкой времени",
              ("назад" in worth or "сегодня" in worth or "вчера" in worth)
              and "T" not in worth.split("по замерам на")[1][:40],
              worth.split("по замерам на")[1][:60])

    # Очередь дополнения: ступени названы поимённо, и среди них -- та, что
    # набирает замеры для коридора.
    queue = page.evaluate("() => fetch('/api/prices/auto').then(r => r.json())")
    check("очередь считает карты с коротким замером",
          "thin" in queue, "ступени: %s" % sorted(
              k for k in ("unknown", "unsplit", "stale", "thin") if k in queue))
    if queue.get("running"):
        skip("ступени очереди на экране", "дополнение сейчас идёт")
    elif not queue.get("thin"):
        skip("ступени очереди на экране", "карт с коротким замером нет")
    else:
        check("про них сказано на экране",
              "замеров меньше трёх" in worth,
              worth[worth.find("замеров меньше"):][:90])

    print()
    print("=== цена, по которой готов взять ===")
    # Карта с известной ценой: цель ставится вокруг неё, иначе проверять
    # нечего -- «дождались» без цены не бывает.
    known = page.evaluate("""async () => {
      const m = await fetch('/api/prices/moves').then(r => r.json());
      return (m.moves[0] || {});
    }""")
    name, rub = known.get("display_name"), known.get("rub_min")
    check("нашлась карта с записанной ценой", bool(name and rub),
          "%s — %s ₽" % (name, rub))

    folder_id = page.evaluate("""async ([folder, card]) => {
      const mk = await fetch('/api/favourites/folders', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: folder})}).then(r => r.json());
      const id = mk.favourites.folders.filter(f => f.name === folder)[0].id;
      await fetch('/api/favourites/folders/' + id + '/cards', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: card, quantity: 1})});
      return id;
    }""", [FOLDER, name])
    check("папка с картой заведена", bool(folder_id), str(folder_id))

    # Папка заведена запросом, а список папок на экране нарисован раньше:
    # перечитываем страницу, иначе кликать не по чему.
    page.reload(wait_until="networkidle")
    page.click('.tab[data-tab="favourites"]')
    page.wait_for_selector('#fav-folders .favfolder[data-id="%s"]' % folder_id,
                           timeout=30000)
    page.click('#fav-folders .favfolder[data-id="%s"]' % folder_id)
    page.wait_for_timeout(400)
    check("поле «готов за» есть у карточки",
          page.locator("#fav-cards [data-target]").count() > 0)
    check("пока цель не названа, показана нынешняя цена",
          "₽" in (page.text_content("#fav-cards .favgoal") or ""),
          " ".join((page.text_content("#fav-cards .favgoal") or "").split())[:60])

    # Цель выше нынешней цены -- значит цена уже пришла.
    page.fill("#fav-cards [data-target]", str(int(rub) + 100))
    page.keyboard.press("Tab")
    page.wait_for_timeout(900)
    said = " ".join((page.text_content("#fav-cards .favgoal") or "").split())
    check("цена ниже названной помечена словами", "ваша цена" in said, said[:80])
    check("пометка видна и глазом",
          page.locator("#fav-cards .favgoal.hit").count() > 0)

    state = page.evaluate("() => fetch('/api/favourites').then(r => r.json())")
    hit = [g["name"] for g in (state.get("goals") or {}).get("hit", [])]
    check("карта попала в «дождались»", name in hit, str(hit[:3]))

    page.click('.tab[data-tab="collection"]')
    page.wait_for_timeout(900)
    said = " ".join((page.text_content("#coll-moves") or "").split())
    check("в учёте коллекции сказано «Дождались»", "Дождались" in said,
          said[:140])

    # Цель ниже цены -- ждём дальше, и сказано, сколько сверху.
    page.click('.tab[data-tab="favourites"]')
    page.wait_for_timeout(400)
    page.fill("#fav-cards [data-target]", str(max(1, int(rub) // 3)))
    page.keyboard.press("Tab")
    page.wait_for_timeout(900)
    said = " ".join((page.text_content("#fav-cards .favgoal") or "").split())
    check("пока дороже -- показана нынешняя цена, без обещаний",
          "сейчас" in said and "ваша цена" not in said, said[:80])

    page.fill("#fav-cards [data-target]", "")
    page.keyboard.press("Tab")
    page.wait_for_timeout(900)
    left = page.evaluate("""async ([folder]) => {
      const doc = await fetch('/api/favourites').then(r => r.json());
      const f = doc.favourites.folders.filter(x => x.name === folder)[0];
      return (f.cards[0] || {}).target;
    }""", [FOLDER])
    check("пустое поле снимает цель", not left, "осталось: %s" % left)

    print()
    print("=== дёшево сегодня или дёшево вообще ===")
    found = page.evaluate("""async () => {
      const r = await fetch('/api/hunt/restock', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({sellers: ['https://topdeck.ru/forums/topic/999001/'],
                              sources: ['fav', 'decks'], limit: 1})})
        .then(x => x.json());
      return (r.sellers[0] || {}).found || [];
    }""")
    check("склад продавца прочитан", len(found) > 0, "находок: %d" % len(found))
    # У карт этого образца замеров может не быть вовсе -- и тогда коридора
    # не должно быть тоже. Молчание здесь и есть правильный ответ.
    loud = [f for f in found
            if (f.get("band") or {}) and not (f.get("band") or {}).get("points")]
    check("без замеров коридор не выдумывается", not loud,
          str([f["want"] for f in loud][:3]))

    # А там, где замеры есть, коридор посчитан: карта с шестью замерами
    # лежит в избранном, и ответ про неё приходит вместе с целями.
    band = page.evaluate("""async ([id, card]) => {
      await fetch('/api/favourites/folders/' + id + '/cards', {method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({name: card, quantity: 1})});
      const doc = await fetch('/api/favourites').then(r => r.json());
      const mine = doc.favourites.folders.filter(f => f.id === id)[0];
      const row = mine.cards.filter(c => c.name === card)[0];
      // Цель нужна, чтобы карта попала в ответ про цели: коридор едет
      // вместе с ней.
      await fetch('/api/favourites/folders/' + id + '/cards/' + row.id,
        {method: 'PATCH', headers: {'Content-Type': 'application/json'},
         body: JSON.stringify({target: 1})});
      const after = await fetch('/api/favourites').then(r => r.json());
      const all = Object.values(after.goals)
        .filter(v => Array.isArray(v)).flat()
        .filter(g => g && g.name === card);
      return (all[0] || {}).band || {};
    }""", [folder_id, "Counterspell"])
    check("у карты с замерами коридор посчитан",
          (band.get("points") or 0) >= 3 and band.get("low"),
          "от %s до %s по %s замерам" % (band.get("low"), band.get("high"),
                                         band.get("points")))

    # И то же самое глазами, в строке находки.
    words = page.evaluate("""(rows) => {
      const data = {wants: 1, sellers: [{url: 'https://topdeck.ru/forums/topic/999001/',
                                         lines: 10, found: rows}]};
      restockRender(data, new Map([[data.sellers[0].url, 'ПРОВЕРКА-Склад']]));
      return [...document.querySelectorAll('#hunt-restock-box .restockrow')]
        .map(r => r.textContent || '');
    }""", [
        {"want": "Дешевле обычного", "price": 100, "verdict": "unknown",
         "line": "1 Дешевле обычного 100",
         "band": {"verdict": "cheap", "low": 170, "high": 220, "points": 5}},
        {"want": "Обычная для неё", "price": 190, "verdict": "unknown",
         "line": "1 Обычная для неё 190",
         "band": {"verdict": "usual", "low": 170, "high": 220, "points": 5}},
        {"want": "Без замеров", "price": 190, "verdict": "unknown",
         "line": "1 Без замеров 190", "band": {}},
    ])
    text = " ".join(" ".join(words).split())
    check("«дешевле, чем когда-либо видели» сказано словами",
          "дешевле, чем когда-либо видели" in text, text[:100])
    check("обычная цена названа обычной, с коридором",
          "обычная для неё цена" in text and "от 170 ₽ до 220 ₽" in text,
          text[100:220])
    check("без замеров про историю не говорится ничего",
          "Без замеров" in text
          and "замер" not in words[2].lower().replace("без замеров", ""),
          words[2][:80] if len(words) > 2 else "")

    print()
    page.evaluate("""async (folder) => {
      const doc = await fetch('/api/favourites').then(r => r.json());
      for (const f of doc.favourites.folders.filter(f => f.name === folder)) {
        await fetch('/api/favourites/folders/' + f.id, {method: 'DELETE'});
      }
    }""", FOLDER)
    check("за собой убрано", True)

    real = [e for e in errors if "favicon" not in e.lower()]
    check("ошибок в консоли нет", not real, "; ".join(real[:2]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё сошлось" if not FAIL else "не сошлось: " + ", ".join(FAIL)))
raise SystemExit(1 if FAIL else 0)
