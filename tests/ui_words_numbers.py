"""Browser check: обещания, числа и слова.

Заведён по шести расхождениям между тем, что программа говорит, и тем, что
она делает:

  * окно справки обещало клавиши `1…4` и `f` — обработчиков не было ни
    одного, при том что рядом в разметке стоит комментарий «описание не может
    разойтись с поведением»;
  * пустая выдача отправляла собирать запрос «панелью фильтров слева» —
    панель не слева, она во всю ширину над выдачей и закрыта. Человек,
    который посмотрел налево, решает, что назначений в программе нет;
  * «зелёная рампа» не находится и не может: так не называется ни одна
    карта. По русским именам поиск ищет, а описание понять не мог;
  * «$81.08» и «$131,89» на соседних экранах: в одном месте доллары
    печатались через toFixed, в другом через русскую локаль с запятой;
  * «Сила 85» — из скольких, было сказано только внизу панели мелким
    шрифтом;
  * одна и та же секция колоды называлась «Под вопросом» и «Возможно», а
    кнопки секций были подписаны «М», «С», «?» — английскими Main и Side
    кириллицей, с подписью только в наведении.

Проверка смотрит и нажимает, но ничего не удаляет: колоду заводит свою и
убирает за собой.

    .venv/Scripts/python.exe tests/ui_words_numbers.py
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
FAIL = []
DECK = "UI Слова и числа"


def ok(cond, label, extra=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", label,
                          "" if not extra else " — " + str(extra)))
    if not cond:
        FAIL.append(label)


def press(page, selector, label):
    """Нажать, а если нажимать нечего -- сказать это и идти дальше.

    Сценарий, который падает на отсутствующей кнопке, проверяет только одно
    расхождение из девятнадцати: остальные до прогона не доходят.
    """
    got = page.evaluate("""(sel) => {
      const el = document.querySelector(sel);
      if (!el) return false;
      el.click();
      return true;
    }""", selector)
    ok(got, label, "нечего нажать: " + selector)
    return got


SETUP = """async (name) => {
  const made = await fetch('/api/decks', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: name, format: 'modern'})}).then(r => r.json());
  await fetch('/api/decks/' + made.deck.id + '/cards', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cards: [
      {name: 'Lightning Bolt', quantity: 4, section: 'main'},
      {name: 'Goblin Guide', quantity: 4, section: 'main'},
      {name: 'Mountain', quantity: 24, section: 'main'},
      {name: 'Monastery Swiftspear', quantity: 4, section: 'main'}]})});
  return made.deck.id;
}"""

CLEAN = """async (name) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name === name)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
}"""

print("=== обещания, числа и слова ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1100}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.evaluate(CLEAN, DECK)
    deck_id = page.evaluate(SETUP, DECK)
    page.wait_for_timeout(600)

    # ------------------------------------------- клавиши, которые обещаны
    print("--- клавиши из окна справки")
    page.click('.tab[data-tab="search"]')
    page.fill("#search-q", "fog")
    page.keyboard.press("Enter")
    page.wait_for_timeout(2600)
    page.keyboard.press("ArrowDown")          # из строки запроса в сетку
    page.wait_for_timeout(400)
    ok(page.evaluate("() => gridCursor") >= 0, "курсор встал на карту")

    page.evaluate("() => { const b = document.querySelector('#hunt-wants');"
                  " b.value = ''; }")
    page.keyboard.press("3")
    page.wait_for_timeout(400)
    got = page.evaluate("() => document.querySelector('#hunt-wants').value")
    ok(re.match(r"^3 \S", got or ""), "«3» кладёт три штуки в охоту", repr(got))

    page.keyboard.press("f")
    page.wait_for_timeout(1200)
    toast = page.evaluate(
        "() => (document.querySelector('.toast') || {}).textContent || ''")
    ok("збранн" in toast or "купить" in toast or "Хочу" in toast,
       "«f» кладёт карту в избранное", repr(toast))

    promised = page.evaluate("""() => {
      keysOpen();
      const t = document.querySelector('#keys-body').innerText;
      keysClose();
      return t;
    }""")
    ok("1…4" in promised and "f" in promised,
       "окно справки по-прежнему обещает именно эти клавиши")

    # -------------------------------------------------- пустая выдача
    print("--- пустая выдача")
    page.fill("#search-q", "зелёная рампа")
    page.keyboard.press("Enter")
    page.wait_for_timeout(2600)
    nothing = page.evaluate(
        "() => (document.querySelector('.nothing') || {}).innerText || ''")
    ok("слева" not in nothing,
       "подсказка не отправляет налево, где панели нет")
    ok("Фильтры" in nothing, "подсказка называет кнопку, которой панель открывается")
    ok("c:g otag:ramp" in nothing,
       "русская фраза переведена в запрос", repr(nothing[:120]))

    opened = press(page, "#nothing-filters", "в подсказке есть кнопка «Фильтры»")
    page.wait_for_timeout(700)
    ok(opened and page.evaluate(
        "() => !document.querySelector('#filters-panel').hidden"),
       "кнопка в подсказке открывает панель")
    ok(page.evaluate("() => document.querySelectorAll('#f-tag-presets button').length") > 10,
       "назначения карт в панели есть — и их много",
       page.evaluate("() => document.querySelectorAll('#f-tag-presets button').length"))
    page.evaluate("() => { document.querySelector('#filters-panel').hidden = true; }")

    page.fill("#search-q", "зелёная рампа")
    page.keyboard.press("Enter")
    page.wait_for_timeout(2600)
    tried = press(page, ".instead [data-try]",
                  "перевод предлагается готовым запросом")
    page.wait_for_timeout(3000)
    found = page.evaluate(
        "() => document.querySelectorAll('#search-results .card').length")
    ok(tried and found > 0,
       "предложенный запрос действительно что-то находит", found)

    # «Лес» -- имя карты, а не описание: переводить нечего.
    page.fill("#search-q", "Лес")
    page.keyboard.press("Enter")
    page.wait_for_timeout(2600)
    ok(page.evaluate(
        "() => document.querySelectorAll('#search-results .card').length") > 0,
       "по русскому имени поиск находит как находил")

    # ------------------------------------------------- доллары одним видом
    print("--- числа")
    page.click('.tab[data-tab="collection"]')
    page.wait_for_timeout(1800)
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(800)
    page.evaluate("(id) => bdOpen(id)", deck_id)
    page.wait_for_timeout(1800)
    money = page.evaluate(r"""() => {
      const t = document.body.innerText;
      return {запятой: (t.match(/\$\s?\d+,\d\d(?!\d)/g) || []),
              точкой: (t.match(/\$\s?\d+\.\d\d(?!\d)/g) || []).length};
    }""")
    ok(not money["запятой"], "доллары везде через точку", money["запятой"][:4])

    # ------------------------------------------------- шкала у оценок
    print("--- шкала у оценок")
    page.evaluate("(id) => anOpen(id)", deck_id)
    page.wait_for_selector(".anscore", timeout=60000)
    page.wait_for_timeout(1200)
    scales = page.evaluate("""() => {
      const out = [];
      document.querySelectorAll('.antop .anscore').forEach((s) => {
        out.push({
          what: (s.querySelector('.antitle') || {}).textContent || '',
          value: ((s.querySelector('.anvalue') || {}).textContent || '').trim()});
      });
      return out;
    }""")
    ok(scales and all("из 100" in s["value"] for s in scales),
       "у каждой оценки написано, из скольких", scales)
    page.evaluate("() => { const p = anPanel(); if (p) p.hidden = true; }")

    # --------------------------------------------------------- слова
    print("--- слова")
    # Кнопки секций живут в строчном виде: в стопках их нет.
    page.evaluate("""() => {
      const v = document.querySelector('#bd-view');
      v.value = 'rows';
      v.dispatchEvent(new Event('change', {bubbles: true}));
    }""")
    page.evaluate("(id) => bdOpen(id)", deck_id)
    page.wait_for_timeout(1600)
    sect = page.evaluate("""() => {
      const out = [];
      document.querySelectorAll('#bd-cards .sect button').forEach((b) => {
        out.push({text: (b.textContent || '').trim(),
                  label: b.getAttribute('aria-label') || ''});
      });
      return out.slice(0, 3);
    }""")
    ok(sect and all(len(s["text"]) > 1 for s in sect),
       "кнопки секций подписаны словом, а не буквой", sect)
    ok(sect and all(s["label"] for s in sect),
       "у каждой кнопки секции есть подпись для чтения с экрана", sect)

    words = page.evaluate("""() => {
      const t = document.body.innerText;
      return {возможно: (t.match(/Возможно/g) || []).length,
              подвопросом: (t.match(/Под вопросом/g) || []).length};
    }""")
    ok(words["возможно"] == 0,
       "одна секция называется одним словом везде", words)

    page.evaluate("() => { const p = document.querySelector('#filters-panel');"
                  " p.hidden = false; }")
    page.wait_for_timeout(400)
    labels = page.evaluate("""() => [...document.querySelectorAll('#filters-panel .flabel')]
        .map((e) => (e.textContent || '').trim())""")
    ok("Исполнение" not in labels,
       "«исполнение» значит одно: вариант колоды, а не вид печати карты",
       labels)

    ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))
    page.evaluate(CLEAN, DECK)
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
