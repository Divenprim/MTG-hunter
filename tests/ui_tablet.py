"""Browser check: страница на планшете.

Программа живёт на компьютере, но смотреть на колоду удобнее с планшета --
для этого есть сетевой режим (run.bat lan). Проверяется главное, что ломалось:

**Ничего не шире экрана.** В портретной ориентации (820 px) страница была
972 px: правая колонка сетки не умела сжиматься, а шапка не переносилась. На
планшете это горизонтальная прокрутка вообще всего, включая шапку.

**По кнопкам можно попасть пальцем.** Ряд условно крупных кнопок должен быть
не ниже 40 px.

Ничего не создаёт и не меняет: только смотрит.

    .venv/Scripts/python.exe tests/ui_tablet.py
"""

import os
from playwright.sync_api import sync_playwright

# Куда стучаться. По умолчанию -- обычный запуск; MTGH_UI_BASE нужна,
# когда на этом порту уже работает другая копия программы (скажем,
# запущенная по https для планшета).
BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
SIZES = [("портрет", 820, 1180), ("альбом", 1180, 820), ("узкий", 744, 1133)]
TABS = ["search", "builder", "deck", "hunt", "favourites", "collection"]
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for title, w, h in SIZES:
        page = browser.new_context(
            viewport={"width": w, "height": h}, has_touch=True,
            device_scale_factor=2).new_page()
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_timeout(700)

        print()
        print("=== %s (%d×%d) ===" % (title, w, h))
        for tab in TABS:
            page.click('.tab[data-tab="%s"]' % tab)
            page.wait_for_timeout(500)
            wide = page.evaluate(
                "() => [document.documentElement.scrollWidth, window.innerWidth]")
            check("вкладка «%s» не шире экрана" % tab, wide[0] <= wide[1] + 1,
                  "%d при окне %d" % (wide[0], wide[1]))

        # Колода -- самое плотное место: статистика, ряды кнопок, колонки карт.
        page.click('.tab[data-tab="builder"]')
        page.wait_for_timeout(400)
        opened = page.evaluate("""async () => {
          const r = await fetch('/api/decks').then(x => x.json());
          if (!r.decks.length) return false;
          await bdOpen(r.decks[0].id);
          return true;
        }""")
        if opened:
            page.wait_for_timeout(2500)
            wide = page.evaluate(
                "() => [document.documentElement.scrollWidth, window.innerWidth]")
            check("открытая колода не шире экрана", wide[0] <= wide[1] + 1,
                  "%d при окне %d" % (wide[0], wide[1]))

        small = page.evaluate("""() => {
          const bad = [];
          document.querySelectorAll('.tab, #bd-actions button, .toolbar button')
            .forEach(b => {
              const r = b.getBoundingClientRect();
              if (r.height && r.height < 40) bad.push(b.textContent.trim().slice(0, 18)
                                                      + ' (' + Math.round(r.height) + ')');
            });
          return bad;
        }""")
        check("по кнопкам можно попасть пальцем", not small, "; ".join(small[:4]))
        check("нет ошибок в консоли", not errors, "; ".join(errors[:2]))
        page.close()
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
