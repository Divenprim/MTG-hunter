"""Browser check: слова и числа на экране не требуют догадок.

Из прохода пользователя:

* **П9/У4** — в выдаче поиска была одна цифра, мировая оценка в долларах, а
  рублёвая пряталась за двумя действиями. Теперь известная рублёвая цена
  стоит рядом, и у обеих сказано, что они значат;
* **П11** — «Разобрать» рядом с колодой читается как «растащить на карты»;
  строка под картой в охоте была набором обрывков через точки;
* **П14** — «60 карт · 75 не хватает»: числа считали разные множества
  (основную колоду и все разделы сразу);
* **П15** — «Sol Ring (m10) 80» с картинкой из другого сета выглядел ошибкой
  программы; на деле номера 80 в m10 нет.

    MTGH_UI_BASE=http://127.0.0.1:8773 .venv/Scripts/python.exe tests/ui_plain_words.py
"""

import os
import re
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


print("=== слова и числа ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(1800)

    # ------------------------------------------------------- П9/У4: деньги
    page.fill("#search-q", "Lightning Bolt")
    page.keyboard.press("Enter")
    page.wait_for_timeout(3500)
    money = page.evaluate("""() => {
      const foots = [...document.querySelectorAll('#search-results .cardfoot')];
      const rub = foots.map((f) => f.querySelector('.rub')).filter(Boolean);
      const usd = foots.map((f) => f.querySelector('.usd')).filter(Boolean);
      return {
        карточек: foots.length,
        с_рублями: rub.length,
        подпись_рубля: rub[0] ? rub[0].title : null,
        подпись_доллара: usd[0] ? usd[0].title : null,
      };
    }""")
    if money["с_рублями"]:
        ok("topdeck" in (money["подпись_рубля"] or ""),
           "у рублёвой цены сказано, откуда она", money["подпись_рубля"])
        ok("Scryfall" in (money["подпись_доллара"] or ""),
           "а у долларовой — что это оценка для сверки",
           money["подпись_доллара"])
    else:
        print("  ----  рублёвых цен в кеше нет — проверять нечего (%s)" % money)
        ok(money["подпись_доллара"] is None or
           "Scryfall" in money["подпись_доллара"],
           "долларовая цена всё равно подписана", money["подпись_доллара"])

    # ------------------------------------------------------- П14: числа колоды
    decks = page.evaluate(
        "async () => (await fetch('/api/decks').then(r => r.json())).decks")
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(1200)
    if decks:
        page.evaluate("(id) => bdOpen(id)", decks[0]["id"])
        page.wait_for_timeout(2500)
    count = page.evaluate(
        "() => (document.querySelector('#bd-count') || {}).textContent || ''")
    ok("в основной" in count,
       "сказано, что первое число — это основная колода", count)
    short = re.search(r"не хватает (\d+) из (\d+)", count)
    ok(short is not None or "всё есть на руках" in count,
       "а нехватка названа вместе с тем, из чего она считается", count)
    if short:
        ok(int(short.group(1)) <= int(short.group(2)),
           "и первое число не больше второго", short.group(0))

    # ------------------------------------------------------- П11: слова
    ok(page.evaluate("""() => {
        const b = [...document.querySelectorAll('.actgname')]
          .find((x) => /Изучить/.test(x.textContent));
        return !!b && !!b.title;
      }"""),
       "группа кнопок разбора называется «Изучить» и объясняет себя")
    ok(page.evaluate("""() => ![...document.querySelectorAll('.actgname')]
        .some((x) => /Разобрать/.test(x.textContent))"""),
       "слова «Разобрать» рядом с колодой больше нет")

    jargon = page.evaluate("""() => {
      const out = [];
      for (const b of document.querySelectorAll('#bd-actions button')) {
        if (!b.title || b.title.length < 12) out.push(b.textContent.trim());
      }
      return out;
    }""")
    ok(not jargon, "у каждой кнопки в ряду есть объяснение", jargon)

    # ------------------------------------------------------- П15 и охота
    page.click('.tab[data-tab="hunt"]')
    page.wait_for_timeout(1200)
    page.evaluate("""() => {
      const t = document.querySelector('#hunt-wants');
      // Карты нарочно не из ходовых: охота вычитает то, что лежит в
      // коллекции, и на стаплах план выходил пустым -- проверять было
      // нечего, а падало это как «строки выбора продавца нет».
      t.value = '2 Mana Drain\\n2 Goblin Guide';
      t.dispatchEvent(new Event('input', {bubbles: true}));
    }""")
    page.evaluate("() => document.querySelector('#hunt-btn').click()")
    page.wait_for_timeout(9000)

    picker = page.evaluate("""() => {
      const s = document.querySelector('#hunt-plan .altnow');
      return s ? s.textContent.replace(/\\s+/g, ' ').trim() : null;
    }""")
    ok(picker is not None and "продавца" in picker,
       "строка выбора продавца — фраза, а не ярлык", picker)

    prints = page.evaluate("""() => [...document.querySelectorAll('#hunt-plan .printinfo')]
        .map((p) => ({текст: p.textContent.replace(/\\s+/g, ' ').trim(),
                      сомнительная: p.classList.contains('guessed')}))""")
    ok(bool(prints), "под предложениями сказано, какая это печать", len(prints))
    bad = [p for p in prints
           if p["сомнительная"] and "картинке" in p["текст"]
           and "—" not in p["текст"]]
    ok(not bad, "а если печать не та — сказано почему", bad[:2])

    ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
