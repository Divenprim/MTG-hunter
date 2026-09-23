"""Browser check: группа исполнений целиком -- спеки, руки, покупки.

Запрос был такой: «хочу проанализировать группу дечек, свою группу турбофог для
пионера и модерна, посмотреть их спеки, посмотреть стартовые руки в сравнении
одновременно и в итоге кинуть в охоту сразу всё необходимое количество карт для
формирования этих колод».

Матрица в «Версиях» отвечала только на вопрос «какие карты общие». Здесь
проверяются три остальных:

  * **спеки рядом** -- земли, доля земель, средняя мана, кривая, цена, чего не
    хватает, и по кнопке -- прогонка стартовых рук для каждой;
  * **руки рядом** -- по руке каждому исполнению одной раздачей, земли видны
    сразу, мулиган -- это та же раздача на карту меньше;
  * **покупки на всю группу** -- и их два разных ответа: «пусть лежат
    собранными одновременно» (общие карты считаются дважды) и «играю по
    очереди» (общие карты кочуют). Итог уходит в охоту одной кнопкой.

Сценарий заводит своё семейство из двух колод и удаляет их в конце. Список
охоты он не трогает: проверяет, что карты в него попали, и возвращает как было.

    .venv/Scripts/python.exe tests/ui_group.py
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = "http://127.0.0.1:8765"
FAMILY = "UI Группа"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def get(path):
    return json.load(urllib.request.urlopen(BASE + path))


# Две колоды одного замысла: общий «Туман» и разные добавки. На «Тумане» и
# видно разницу между двумя ответами про покупки.
SETUP = """async (args) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => (d.family || '') === args.family
                                      || d.name.indexOf(args.family) === 0)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
  const ids = [];
  for (const [name, fmt, cards] of args.decks) {
    const made = await fetch('/api/decks', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name: name, format: fmt})}).then(r => r.json());
    await fetch('/api/decks/' + made.deck.id, {method: 'PATCH',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({family: args.family})});
    await fetch('/api/decks/' + made.deck.id + '/cards', {method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({cards: cards.map(
        (c) => ({name: c[0], quantity: c[1], section: c[2] || 'main'}))})});
    ids.push(made.deck.id);
  }
  return ids;
}"""

CLEAN = """async (family) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => (d.family || '') === family
                                      || d.name.indexOf(family) === 0)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
}"""

DECKS = [
    ["UI Группа — Пионер", "pioneer",
     [["Fog", 4], ["Root Snare", 4], ["Forest", 20]]],
    ["UI Группа — Модерн", "modern",
     [["Fog", 4], ["Ethereal Haze", 4], ["Forest", 20], ["Darkness", 2, "side"]]],
]

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1100}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")
    page.evaluate(SETUP, {"family": FAMILY, "decks": DECKS})

    # Список охоты возвращаем в конце как был: он принадлежит человеку.
    hunt_before = page.evaluate("() => $('#hunt-wants').value")

    print("=== группа открывается из списка колод ===")
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(1000)
    page.click('#bd-decks .bdfamily[data-family="%s"] [data-famopen]' % FAMILY)
    page.wait_for_selector("#fam-main .famvar", timeout=30000)
    check("кнопка «группа» в списке колод уводит в «Версии»",
          page.evaluate("() => document.querySelector('.tab.active').dataset.tab")
          == "family")
    check("и открывает нужное семейство",
          page.evaluate("() => famName") == FAMILY,
          str(page.evaluate("() => famName")))

    print()
    print("=== группа открыта ===")
    check("исполнений в группе два",
          page.locator("#fam-main .famvar").count() == 2)
    check("полоса групповых вопросов появилась",
          not page.is_hidden("#fam-groupbar"))

    print()
    print("=== спеки рядом ===")
    page.click('#fam-groupbar [data-group="specs"]')
    page.wait_for_selector("#fam-group .fgtable", timeout=30000)
    rows = page.locator("#fam-group .fgtable tbody tr").count()
    check("в таблице строка на исполнение", rows == 2, str(rows))
    specs = page.evaluate("() => fgSpecs")
    lands = sorted(d["lands"] for d in specs["decks"])
    check("земли посчитаны", lands == [20, 20], str(lands))
    check("кривая нарисована",
          page.locator("#fam-group .fgcurve i").count() > 0)
    check("видно, чего не хватает",
          all(d["missing_copies"] > 0 for d in specs["decks"]))

    page.click("#fam-group [data-fgsim]")
    page.wait_for_function("() => fgSim && (fgSim.runs || []).length === 2",
                           timeout=60000)
    keepable = [r["goldfish"]["keepable_pct"] for r in
                page.evaluate("() => fgSim")["runs"]]
    check("прогонка добавила цифры про старт", all(k > 0 for k in keepable),
          "; ".join("%.0f%%" % k for k in keepable))

    print()
    print("=== руки рядом ===")
    page.click('#fam-groupbar [data-group="hands"]')
    page.wait_for_selector("#fam-group .fghand", timeout=30000)
    check("руки сданы обоим исполнениям",
          page.locator("#fam-group .fghand").count() == 2)
    cards = page.locator("#fam-group .fgcard").count()
    check("по семь карт в каждой", cards == 14, str(cards))
    first = page.evaluate("() => fgHands.hands[0].hand.map(c => c.name)")

    page.click("#fam-group [data-fgdeal]")
    page.wait_for_function("""(names) => {
      const now = (((fgHands || {}).hands || [])[0] || {}).hand || [];
      return now.length && JSON.stringify(now.map(c => c.name)) !== JSON.stringify(names);
    }""", arg=first, timeout=30000)
    check("«сдать заново» сдаёт другую руку", True)

    page.select_option("#fg-handsize", "6")
    page.wait_for_function("() => fgHands && fgHands.hand_size === 6", timeout=30000)
    check("мулиган — та же раздача на карту меньше",
          page.locator("#fam-group .fgcard").count() == 12,
          str(page.locator("#fam-group .fgcard").count()))

    print()
    print("=== покупки на всю группу ===")
    page.click('#fam-groupbar [data-group="buy"]')
    page.wait_for_selector("#fam-group .fgmodes", timeout=30000)
    page.click('#fam-group [data-fgmode="together"]')
    page.wait_for_function("() => fgBuy && fgBuy.mode === 'together'", timeout=30000)
    together = page.evaluate("() => fgBuy")
    fog = [r for r in together["rows"] if r["name"] == "Fog"][0]
    check("«все сразу» складывает общие карты", fog["needed"] == 8,
          "Туманов нужно %d" % fog["needed"])
    check("и карта помечена общей", fog["shared"])

    page.click('#fam-group [data-fgmode="byturn"]')
    page.wait_for_function("() => fgBuy && fgBuy.mode === 'byturn'", timeout=30000)
    byturn = page.evaluate("() => fgBuy")
    fog2 = [r for r in byturn["rows"] if r["name"] == "Fog"][0]
    check("«по очереди» берёт наибольшее", fog2["needed"] == 4,
          "Туманов нужно %d" % fog2["needed"])
    check("копий в сумме меньше",
          byturn["totals"]["copies"] < together["totals"]["copies"],
          "%d против %d" % (byturn["totals"]["copies"],
                            together["totals"]["copies"]))
    check("показан и второй ответ, чтобы было из чего выбирать",
          "все сразу" in (page.text_content("#fam-group") or ""))
    check("сайдборд тоже покупается",
          "Darkness" in [r["name"] for r in byturn["rows"]])
    check("базовые земли не в счёте по умолчанию",
          "Forest" not in [r["name"] for r in byturn["buy"]],
          "; ".join(r["name"] for r in byturn["buy"][:4]))
    check("но о них сказано",
          byturn["totals"]["basic_copies"] > 0 and
          "Базовых земель" in (page.text_content("#fam-group") or ""),
          "%s шт." % byturn["totals"]["basic_copies"])

    page.evaluate("() => document.getElementById('fg-basics').click()")
    page.wait_for_function("() => fgBuy && fgBuy.basics === true", timeout=30000)
    check("галочка возвращает их в список",
          "Forest" in [r["name"] for r in page.evaluate("() => fgBuy.buy")])
    page.evaluate("() => document.getElementById('fg-basics').click()")
    page.wait_for_function("() => fgBuy && fgBuy.basics === false", timeout=30000)
    byturn = page.evaluate("() => fgBuy")

    print()
    print("=== всё недостающее в охоту ===")
    page.click("#fam-group [data-fghunt]")
    page.wait_for_timeout(800)
    hunt = page.evaluate("() => $('#hunt-wants').value")
    lines = [l for l in hunt.split("\n") if l.strip()]
    wanted = {r["name"]: r["missing"] for r in byturn["buy"]}
    check("список охоты пополнился", len(lines) >= len(wanted),
          "%d строк на %d названий" % (len(lines), len(wanted)))
    check("количество совпадает с недостающим",
          any(l.strip() == "4 Fog" for l in lines),
          "; ".join(lines[:3]))
    check("базовые земли в охоту не ушли",
          not any(l.strip().endswith("Forest") for l in lines),
          "; ".join(lines[:4]))
    check("сайдбордная карта тоже в списке",
          any("Darkness" in l for l in lines))

    print()
    print("=== уборка ===")
    page.evaluate("""(text) => {
      $('#hunt-wants').value = text;
      store.set('hunt', text);
    }""", hunt_before)
    check("список охоты возвращён как был",
          page.evaluate("() => $('#hunt-wants').value") == hunt_before)
    page.evaluate(CLEAN, FAMILY)
    check("свои колоды удалены",
          not [d for d in get("/api/decks")["decks"]
               if (d.get("family") or "") == FAMILY])
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
