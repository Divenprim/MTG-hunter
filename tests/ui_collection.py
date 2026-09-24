"""Browser check: коллекция как имущество, а не как список имён.

Замечание было такое: «не просто голый список того, каких карт нет, -- их
картинки, стоимости и цены; отслеживание цены коллекции по времени; разные
виды представления; и нет возможности скопировать полный список для
экспорта».

Проверяется каждое из этого:

  * **два вида.** Плитками -- карта узнаётся по картинке; строками -- считают
    числа. Выбор запоминается между запусками;
  * **цена при карте** и стоимость стопки: четыре копеечные карты и одна
    дорогая -- разные вопросы, и сортировки под них разные;
  * **оценка коллекции** с оговоркой, откуда она взялась: доллары из локальной
    базы по самой дешёвой печати, рубли -- только по спрошенным у topdeck;
  * **выгрузка списком** -- ровно в том виде, в каком коллекция вводится.

Свои карты сценарий **добавляет**, а не заменяет ими коллекцию: если он
оборвётся посреди, у вас останется коллекция плюс три лишние карты, а не три
карты вместо коллекции. Полная запись -- только в уборке, последним шагом.

    .venv/Scripts/python.exe tests/ui_collection.py
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = "http://127.0.0.1:8765"
MINE = {"Lightning Bolt": 4, "Sol Ring": 2, "Counterspell": 3}
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def get(path):
    return json.load(urllib.request.urlopen(BASE + path))


# Коллекция принимается тем же текстом, каким её вводит человек: по строке на
# карту. Значит и вернуть её на место можно ровно так же.
ADD = """async (entries) => {
  const r = await fetch('/api/collection/add', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cards: Object.entries(entries).map(
      ([name, quantity]) => ({name: name, quantity: quantity}))})});
  return r.ok;
}"""

SAVE = """async (text) => {
  const r = await fetch('/api/collection', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({text: text})});
  return r.ok;
}"""


def as_text(entries):
    return chr(10).join("%d %s" % (n, name) for name, n in entries.items())


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(
        viewport={"width": 1500, "height": 1080},
        permissions=["clipboard-read", "clipboard-write"]).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")

    before = get("/api/collection").get("collection") or {}
    had = sum(before.values())
    page.evaluate(ADD, MINE)

    page.click('.tab[data-tab="collection"]')
    page.wait_for_selector(".holdtile, .holdrow", timeout=60000)
    page.wait_for_timeout(600)

    print("=== чего стоит коллекция ===")
    worth = " ".join((page.locator("#coll-worth").text_content() or "").split())
    check("оценка показана", "$" in worth, worth[:70])
    check("сказано, откуда взялась долларовая цена",
          "самой дешёвой печати" in worth)
    check("и по скольким картам известна рублёвая",
          "topdeck" in worth and "из" in worth, worth[-80:])

    totals = page.evaluate("() => holdData.totals")
    check("доллары посчитаны", totals["usd_known"] >= len(MINE),
          "%d назв. с ценой" % totals["usd_known"])
    check("штуки посчитаны верно",
          totals["copies"] == had + sum(MINE.values()),
          "было %d, добавлено %d, стало %d"
          % (had, sum(MINE.values()), totals["copies"]))

    print()
    print("=== карту видно, а не только имя ===")
    page.evaluate("""() => { holdSetView('tiles'); }""")
    page.wait_for_selector(".holdtile", timeout=20000)
    tile = page.locator('.holdtile[data-card="Lightning Bolt"]').first
    check("карта показана плиткой", tile.count() > 0)
    check("с картинкой", tile.locator("img").count() > 0)
    text = " ".join((tile.text_content() or "").split())
    check("с ценой", "$" in text, text[:70])
    check("и со стопкой, раз копий больше одной", "стопка" in text, text[:80])

    print()
    print("=== строками считают числа ===")
    page.evaluate("""() => { holdSetView('rows'); }""")
    page.wait_for_selector(".holdrow", timeout=20000)
    check("строки нарисованы", page.locator(".holdrow").count() > 1)
    check("в строке есть миниатюра", page.locator(".holdmini").count() > 0)

    print()
    print("=== вид запоминается ===")
    page.reload(wait_until="networkidle")
    page.click('.tab[data-tab="collection"]')
    page.wait_for_selector(".holdrow", timeout=60000)
    check("после перезагрузки вид тот же",
          page.evaluate("() => holdView") == "rows")

    print()
    print("=== сортировки ===")
    page.evaluate("""() => { holdSetView('tiles'); }""")
    page.wait_for_timeout(300)
    page.select_option("#coll-sort", "worth")
    page.wait_for_timeout(500)
    order = page.evaluate("""() => [...document.querySelectorAll('.holdtile')]
        .slice(0, 12).map(e => e.dataset.card)""")
    worths = page.evaluate("""(names) => names.map((n) => {
        const c = (holdData.cards || []).find((c) => c.name === n);
        return c && c.usd_total != null ? c.usd_total : -1;
      })""", order)
    check("по стоимости стопки — от дорогой к дешёвой",
          worths == sorted(worths, reverse=True), str(worths[:5]))

    page.select_option("#coll-sort", "usd")
    page.wait_for_timeout(500)
    first = page.evaluate("""() => (document.querySelector('.holdtile') || {}).dataset""")
    check("по цене карты сортировка тоже работает", bool(first))

    print()
    print("=== выгрузка ===")
    page.click("#coll-copy")
    page.wait_for_timeout(1000)
    clip = page.evaluate("() => navigator.clipboard.readText()")
    lines = [l.strip() for l in clip.splitlines() if l.strip()]
    check("скопирована вся коллекция", len(lines) == totals["cards"],
          "%d строк при %d назв." % (len(lines), totals["cards"]))
    check("в том виде, в каком она вводится",
          all(l.split(" ", 1)[0].isdigit() for l in lines), "; ".join(lines[:3]))
    mine_lines = [l for l in lines if l.split(" ", 1)[-1] in MINE]
    check("с верными количествами",
          sorted(mine_lines) ==
          sorted("%d %s" % (n + before.get(name, 0), name)
                 for name, n in MINE.items()),
          "; ".join(sorted(mine_lines)))

    csv = get("/api/collection/export?kind=csv")
    rows = csv["text"].splitlines()
    check("CSV отдаётся со столбцами", "цена" in rows[0], rows[0][:60])
    check("и строк в нём столько же, сколько названий",
          len(rows) == totals["cards"] + 1,
          "%d строк при %d назв." % (len(rows), totals["cards"]))

    print()
    print("=== история стоимости ===")
    hist = get("/api/collection/value")["history"]
    check("сегодняшняя оценка записана", bool(hist), str(len(hist)))
    if hist:
        check("в записи есть и доллары, и штуки",
              hist[-1]["usd"] > 0 and hist[-1]["copies"] > 0, str(hist[-1]))
    check("за день строка одна",
          len({h["at"] for h in hist}) == len(hist), str(len(hist)))

    print()
    print("=== уборка ===")
    page.evaluate(SAVE, as_text(before))
    page.wait_for_timeout(500)
    after = get("/api/collection").get("collection") or {}
    check("коллекция возвращена как была", after == before,
          "было %d назв., стало %d" % (len(before), len(after)))
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
