"""Browser check: в коллекции видно, что за карта, и числа не спорят.

**П7** — «показано 48 из 87 на руках», первые плитки нормальные, остальные
три десятка — чёрные прямоугольники с количеством в углу: что за карта,
узнать нельзя. Картинок на экране под три сотни, они грузятся лениво и с
низким приоритетом, а имя жило только в `alt`, то есть не было видно никогда.
Это дыра четвёртого этапа: я мерил высоту окна и число строк, а не то, что в
плитках что-то нарисовано.

**П10** — «цена спрошена у topdeck для 86 из 87 назв.» и рядом «не спрошено
197 назв.»: 197 больше 87. Второе число считает и карты колод, но об этом не
говорилось.

    MTGH_UI_BASE=http://127.0.0.1:8773 .venv/Scripts/python.exe tests/ui_collection_tiles.py
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


print("=== плитки коллекции ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(1500)
    page.click('.tab[data-tab="collection"]')
    page.wait_for_timeout(3000)
    page.evaluate("""() => {
      const b = document.querySelector('#panel-collection [data-view=tiles]');
      if (b) b.click();
    }""")
    page.wait_for_timeout(2500)

    tiles = page.evaluate(
        "() => document.querySelectorAll('.holdcard').length")
    ok(tiles > 0, "плитки нарисованы", tiles)

    named = page.evaluate("""() => {
      const cards = [...document.querySelectorAll('.holdcard')];
      let withName = 0;
      let empty = [];
      for (const c of cards) {
        const nm = c.querySelector('.holdname, .holdnoart');
        const text = nm ? nm.textContent.trim() : '';
        if (text) withName++;
        else empty.push(c.dataset.card || '(без имени)');
      }
      return {всего: cards.length, с_именем: withName, без: empty.slice(0, 3)};
    }""")
    ok(tiles and named["с_именем"] == named["всего"],
       "на каждой плитке написано, что это за карта", named)

    # Самое важное: имя не зависит от того, доехала ли картинка.
    blind = page.evaluate("""() => {
      const cards = [...document.querySelectorAll('.holdcard')];
      let noArt = 0, noArtNamed = 0;
      for (const c of cards) {
        const img = c.querySelector('img');
        const loaded = img && img.complete && img.naturalWidth > 0;
        if (loaded) continue;
        noArt++;
        const nm = c.querySelector('.holdname, .holdnoart');
        if (nm && nm.textContent.trim()) noArtNamed++;
      }
      return {без_картинки: noArt, из_них_подписаны: noArtNamed};
    }""")
    ok(blind["без_картинки"] == blind["из_них_подписаны"],
       "карту видно и до того, как доедет картинка", blind)

    # ------------------------------------------------------------- П10
    text = page.evaluate(
        "() => document.querySelector('#panel-collection').textContent.replace(/\\s+/g, ' ')")
    in_coll = re.search(r"спрошена у topdeck для (\d+) из (\d+) назв\. коллекции", text)
    ok(in_coll is not None,
       "у числа «N из M» сказано, что это коллекция",
       (text[text.find("спрошена"):text.find("спрошена") + 70]
        if "спрошена" in text else "строки нет"))

    queue = re.search(r"не спрошено (\d+) назв\. — ([^—]+) —", text)
    if "не спрошено" in text:
        ok(queue is not None and "колод" in queue.group(2),
           "а у очереди цен — что в неё входят и карты колод",
           queue.group(0) if queue else text[text.find("не спрошено"):][:70])
        if in_coll and queue and int(queue.group(1)) > int(in_coll.group(2)):
            ok(True, "числа разной ширины — и теперь ясно, почему",
               "%s против %s" % (queue.group(1), in_coll.group(2)))
    else:
        print("  ----  очередь цен пуста — сравнивать нечего")

    ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
