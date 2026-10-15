"""Browser check: прилипшие строки не закрывают друг друга.

Четвёртый этап раздал высоту шапки четырём липким полосам и пропустил самую
ходовую — строку поиска. Она прилипает к тому же `top: 0` с тем же
`z-index`, но идёт в DOM позже, поэтому своим непрозрачным фоном закрашивает
вкладки: целишься в «Охоту», попадаешь в поле запроса.

Здесь проверяется ровно то, что должно быть верно всегда:

* по вкладке можно попасть после прокрутки;
* `--topbar-h` равен настоящей высоте шапки, а не той, что была до ответа
  сервера (счётчик базы дорисовывается позже и переносит шапку в две строки);
* когда шапка отлипает (узкое окно), липкие строки не отступают в пустоту;
* флажки не меньше 16 пикселей.

    .venv/Scripts/python.exe tests/ui_sticky.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
FAIL = []


def ok(cond, label, extra=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", label,
                          "" if not extra else " — " + str(extra)))
    if not cond:
        FAIL.append(label)


def topbar_h(page):
    return page.evaluate("""() => {
      const v = getComputedStyle(document.documentElement)
        .getPropertyValue('--topbar-h').trim();
      return parseFloat(v) || 0;
    }""")


def real_h(page):
    return page.evaluate("""() => {
      const b = document.querySelector('.topbar');
      return b ? Math.round(b.getBoundingClientRect().height) : 0;
    }""")


print("=== липкие строки ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1500, "height": 900})
    page = ctx.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(1800)

    # ------------------------------------------------ высота шапки измерена верно
    measured, actual = topbar_h(page), real_h(page)
    ok(abs(measured - actual) <= 2,
       "--topbar-h равен настоящей высоте шапки",
       "в переменной %s, на деле %s" % (measured, actual))

    # ------------------------------------------------ по вкладке можно попасть
    page.fill("#search-q", "goblin")
    page.keyboard.press("Enter")
    page.wait_for_timeout(3500)
    page.evaluate("() => document.scrollingElement.scrollTo(0, 1500)")
    page.wait_for_timeout(500)

    under = page.evaluate("""() => {
      const t = [...document.querySelectorAll('.tab')]
        .find((x) => x.dataset.tab === 'hunt');
      if (!t) return 'вкладки нет';
      const b = t.getBoundingClientRect();
      const el = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
      if (!el) return 'ничего';
      return el === t ? 'сама вкладка'
        : (el.id || el.className || el.tagName) + ' (' + el.tagName + ')';
    }""")
    ok(under == "сама вкладка",
       "после прокрутки под вкладкой «Охота» — сама вкладка", under)

    page.evaluate("""() => {
      const t = [...document.querySelectorAll('.tab')]
        .find((x) => x.dataset.tab === 'hunt');
      const b = t.getBoundingClientRect();
      const el = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
      if (el) el.click();
    }""")
    page.wait_for_timeout(1200)
    ok(page.evaluate("() => document.querySelector('.tab.active').dataset.tab") == "hunt",
       "нажатие в это место действительно открывает «Охоту»",
       page.evaluate("() => document.querySelector('.tab.active').textContent"))

    # ------------------------------------------------ строка поиска под шапкой
    page.click('.tab[data-tab="search"]')
    page.wait_for_timeout(800)
    page.evaluate("() => document.scrollingElement.scrollTo(0, 1500)")
    page.wait_for_timeout(400)
    boxes = page.evaluate("""() => {
      const bar = document.querySelector('.topbar');
      const tool = document.querySelector('#panel-search .toolbar');
      if (!bar || !tool) return null;
      const a = bar.getBoundingClientRect(), b = tool.getBoundingClientRect();
      return {шапка: [Math.round(a.top), Math.round(a.bottom)],
              строка_поиска: [Math.round(b.top), Math.round(b.bottom)]};
    }""")
    ok(boxes is not None and boxes["строка_поиска"][0] >= boxes["шапка"][1] - 2,
       "строка поиска встаёт под шапкой, а не поверх", boxes)

    # ------------------------------------------------ флажки видны мышью
    page.click('.tab[data-tab="hunt"]')
    page.wait_for_timeout(1000)
    size = page.evaluate("""() => {
      const c = document.querySelector('#panel-hunt input[type=checkbox]');
      if (!c) return null;
      const b = c.getBoundingClientRect();
      return [Math.round(b.width), Math.round(b.height)];
    }""")
    ok(size is not None and min(size) >= 16, "флажки не меньше 16 px", size)

    # ------------------------------------------------ узкое окно: отступа нет
    page.set_viewport_size({"width": 900, "height": 900})
    page.wait_for_timeout(900)
    narrow = page.evaluate("""() => {
      const bar = document.querySelector('.topbar');
      return {
        положение_шапки: getComputedStyle(bar).position,
        переменная: getComputedStyle(document.documentElement)
          .getPropertyValue('--topbar-h').trim(),
      };
    }""")
    ok(narrow["положение_шапки"] != "sticky" and
       (parseable := narrow["переменная"]) and float(parseable.replace("px", "")) == 0,
       "шапка отлипла — отступ обнулён", narrow)

    # ------------------------------------------------ шапка выросла — отступ тоже
    page.set_viewport_size({"width": 1500, "height": 900})
    page.wait_for_timeout(900)
    grown = page.evaluate("""() => {
      const s = document.querySelector('#status');
      if (s) s.textContent = s.textContent + ' '.repeat(10) +
        'длинная строка, какой шапка становится после ответа сервера, ' +
        'она переносится и шапка вырастает вдвое';
      return true;
    }""")
    page.wait_for_timeout(700)
    measured, actual = topbar_h(page), real_h(page)
    ok(abs(measured - actual) <= 2,
       "шапка выросла после ответа сервера — отступ пересчитан",
       "в переменной %s, на деле %s" % (measured, actual))

    ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
