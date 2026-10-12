"""Browser check: учёт показывает своё и показывает его окном.

Три замечания, из которых вырос этот сценарий, все с живых данных:

  * **простыня.** 105 карт на телефоне давали 40 740 px -- сорок восемь
    экранов пролистывания, без страниц, без «показать ещё» и без «наверх».
    Каждая плитка при этом полноразмерная картинка;
  * **чужие карты в учёте.** Таблица строится по объединению коллекции и
    колод, и в ней было 247 строк карт, которых на руках нет, против 87
    своих. Человек видел «подходит 112 назв. из 333» при 87 картах и не
    понимал, откуда числа;
  * **столбцы без объяснения.** «Занято» -- чем занято? Слово «собранная
    колода» нигде не вводилось.

И четвёртое, найденное замером уже в ходе починки: прилипающие строки липли к
`top: 0`, то есть ровно под верхнюю полосу. Строка столбцов в учёте не была
видна никогда -- она вставала на нулевую точку, а полоса кончается на 56-й.

Коллекция здесь только читается: сценарий ничего в ней не меняет.

    .venv/Scripts/python.exe tests/ui_collection_window.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label +
          (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def press(page, selector, label):
    """Нажать, а если нажимать нечего -- сказать это словами.

    Сценарий, падающий трассировкой на `null.click()`, сообщает «что-то не
    так» вместо «вот эта кнопка пропала», и чинить по нему нечего.
    """
    there = page.evaluate("(s) => !!document.querySelector(s)", selector)
    check(label, there, "нет на странице: " + selector)
    if there:
        page.evaluate("(s) => document.querySelector(s).click()", selector)
        page.wait_for_timeout(800)
    return there


STATE = """() => {
    const list = document.querySelector('#coll-list');
    const cards = (holdData && holdData.cards) || [];
    return {
        height: document.documentElement.scrollHeight,
        tiles: list.querySelectorAll('.holdcard').length,
        rows: list.querySelectorAll('.holdrow:not(.head)').length,
        strangers_shown: list.querySelectorAll('.holdcard.ghostly').length,
        counter: (document.querySelector('#coll-found').textContent || '').trim(),
        more: !!list.querySelector('[data-more=step]'),
        all: !!list.querySelector('[data-more=all]'),
        scope: holdOnly,
        total: cards.length,
        mine: cards.filter((c) => c.owned > 0).length,
    };
}"""

STICKY = """() => {
    const bar = document.querySelector('.topbar').getBoundingClientRect();
    const cnt = document.querySelector('#coll-found').getBoundingClientRect();
    const head = document.querySelector('#coll-list .holdrow.head');
    const h = head ? head.getBoundingClientRect() : null;
    return {
        bar: Math.round(bar.bottom),
        counter_top: Math.round(cnt.top),
        counter_hidden: cnt.bottom <= bar.bottom + 1,
        head_top: h ? Math.round(h.top) : null,
        head_hidden: h ? h.bottom <= bar.bottom + 1 : null,
    };
}"""


def open_collection(page):
    page.goto(BASE, wait_until="networkidle")
    page.click('.tab[data-tab="collection"]')
    page.wait_for_timeout(2500)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    errors = []

    print("=== учёт показывает то, что на руках ===")
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    open_collection(page)
    st = page.evaluate(STATE)

    check("по умолчанию показано только своё", st["scope"] == "mine",
          "охват: %s" % st["scope"])
    check("чужих карт на экране нет", st["strangers_shown"] == 0,
          "в данных их %d" % (st["total"] - st["mine"]))
    check("счётчик называет оба числа",
          "показано" in st["counter"] and str(st["mine"]) in st["counter"],
          st["counter"][:90])
    check("про чужие карты сказано вслух, а не умолчано",
          "нужны колодам" in st["counter"] or st["total"] == st["mine"])

    print("=== список растёт по просьбе, а не сразу ===")
    check("показано не всё", st["tiles"] < st["mine"],
          "%d из %d" % (st["tiles"], st["mine"]))
    check("есть «показать ещё» и «показать все»", st["more"] and st["all"])

    press(page, "[data-more=step]", "кнопка «показать ещё» на месте")
    grown = page.evaluate(STATE)
    check("«ещё» добавляет карты", grown["tiles"] > st["tiles"],
          "%d -> %d" % (st["tiles"], grown["tiles"]))

    print("=== переключатель охвата ===")
    press(page, "#coll-found [data-only]", "переключатель охвата на месте")
    wide = page.evaluate(STATE)
    check("по нажатию показываются и чужие", wide["scope"] == "all",
          "охват: %s" % wide["scope"])
    check("окно при этом начинается сначала", wide["tiles"] <= st["tiles"] + 1,
          "плиток %d" % wide["tiles"])
    check("чужие появились", wide["strangers_shown"] > 0,
          "%d на экране" % wide["strangers_shown"])

    press(page, "#coll-found [data-only]", "обратный переключатель на месте")
    page.reload(wait_until="networkidle")
    page.click('.tab[data-tab="collection"]')
    page.wait_for_timeout(2500)
    back = page.evaluate(STATE)
    check("выбор запоминается до следующего открытия", back["scope"] == "mine",
          "охват: %s" % back["scope"])

    print("=== столбцы объяснены ===")
    press(page, "[data-view=rows]", "переключатель вида на месте")
    heads = page.evaluate("""() => Array.from(document.querySelectorAll(
        '#coll-list .holdrow.head > span')).map((s) => ({
            label: s.textContent.trim(), hint: s.getAttribute('title') || ''}))""")
    numeric = [h for h in heads if h["label"] in ("есть", "занято", "свободно")]
    check("у числовых столбцов есть пояснение", len(numeric) == 3
          and all(len(h["hint"]) > 10 for h in numeric),
          ", ".join(h["label"] for h in numeric if not h["hint"]) or "все три")
    legend = page.evaluate(
        """() => (document.querySelector('#coll-legend') || {}).textContent || ''""")
    check("слово «собранная колода» введено", "собранной" in legend)
    check("сказано, где её отмечают", "По колодам" in legend)
    check("арифметика названа", "есть − занято" in legend)

    print("=== прилипающие строки видны ===")
    page.evaluate("() => window.scrollTo(0, 2000)")
    page.wait_for_timeout(400)
    sticky = page.evaluate(STICKY)
    check("счётчик не уезжает под верхнюю полосу", not sticky["counter_hidden"],
          "полоса кончается на %s, счётчик на %s"
          % (sticky["bar"], sticky["counter_top"]))
    check("строка столбцов не уезжает под счётчик", not sticky["head_hidden"],
          "строка на %s" % sticky["head_top"])

    print("=== «наверх» ===")
    top = page.evaluate("""() => {
        const b = document.querySelector('#coll-top');
        return {есть: !!b, видна: b ? !b.hidden : false};
    }""")
    check("кнопка «наверх» появляется при прокрутке",
          top["есть"] and top["видна"])
    if top["есть"]:
        page.evaluate("() => document.querySelector('#coll-top').click()")
        page.wait_for_timeout(900)
        check("и возвращает наверх",
              page.evaluate("() => window.scrollY") < 50)
        check("наверху её не видно",
              page.evaluate("() => document.querySelector('#coll-top').hidden"))

    print("=== телефон ===")
    phone = browser.new_context(viewport={"width": 390, "height": 844},
                                is_mobile=True, has_touch=True).new_page()
    phone.on("pageerror", lambda e: errors.append(str(e)))
    open_collection(phone)
    pst = phone.evaluate(STATE)
    screens = pst["height"] / 844.0
    # До починки здесь было сорок восемь экранов. Десять -- это ещё длинно, но
    # это уже список, который листают, а не бесконечная лента.
    check("страница перестала быть простынёй", screens < 10,
          "%.0f экранов (было 48)" % screens)
    check("вбок не едет", phone.evaluate(
        "() => document.documentElement.scrollWidth <= 390"))

    check("нет ошибок в консоли", not errors,
          "; ".join(e[:80] for e in errors[:3]))
    browser.close()

print()
if FAIL:
    print("НЕ СОШЛОСЬ: " + "; ".join(FAIL))
    sys.exit(1)
print("ИТОГ: всё хорошо")
