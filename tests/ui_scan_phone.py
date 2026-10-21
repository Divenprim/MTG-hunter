"""Browser check: сканер на телефоне.

Заведён после жалобы «приходится пролистывать, если нужно изменить
количество сканируемых карт; кривая расстановка элементов». Замер на экране
390x844 показал ровно две беды, и обе из кода поодиночке не видны:

  * кнопка «Включить камеру» лежала на 926-й точке -- ниже первого экрана.
    Над ней стояли окно «что нового» (560 точек из 844), абзац пояснения и
    строка состояния базы отпечатков. То есть чтобы начать сканировать,
    надо было сперва листать;
  * строка найденной карты -- сетка из пяти колонок `84px 1fr auto auto
    auto`. На 390 точках она разъезжалась: колонка имени получала ширину
    ноль и имя переносилось по одному слову, а кнопка «убрать» вылезала за
    край карточки.

Отдельно: телефонная раскладка была дописана в середину style.css, выше
общего правила `.scanrow`, и проигрывала ему по порядку -- вес селекторов
одинаковый, побеждает тот, что ниже. На экране это выглядело как будто
медиазапрос не работает вовсе. Поэтому здесь проверяется не наличие правил,
а то, что получилось на экране.

Проверка смотрит, но ничего не меняет: карты подкладываются в память
страницы, в коллекцию и колоды ничего не пишется.

    .venv/Scripts/python.exe tests/ui_scan_phone.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
PHONE = {"width": 390, "height": 844}
FAIL = []


def ok(cond, label, extra=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", label,
                          "" if not extra else " — " + str(extra)))
    if not cond:
        FAIL.append(label)


# Карты подкладываются готовыми: нас занимает расстановка, а не распознавание.
# Имена взяты подлиннее -- короткое имя уместится в любую колонку и скроет
# ровно ту беду, ради которой проверка написана.
FAKE = """() => {
  if (typeof scanFound === 'undefined') return 'сканер не загружен';
  scanFound = [
    {name: 'Vorinclex, Monstrous Raider', ru_name: 'Воринклекс, Чудовищный Налётчик',
     set_code: 'khm', collector_number: '199', quantity: 2, card_id: 'p1',
     image_small: '', distance: 3},
    {name: 'Sol Ring', ru_name: 'Кольцо Солнца', set_code: 'c21',
     collector_number: '263', quantity: 4, card_id: 'p2',
     image_small: '', distance: 2},
  ];
  scanRenderFound();
  return scanFound.length;
}"""

WHERE = """() => {
  const at = (sel) => {
    const el = document.querySelector(sel);
    if (!el || el.offsetParent === null) return null;
    const b = el.getBoundingClientRect();
    return {top: Math.round(b.top + window.scrollY),
            left: Math.round(b.left), right: Math.round(b.right),
            width: Math.round(b.width), height: Math.round(b.height)};
  };
  return {camera: at('#scan-start'), news: at('#whatsnew'),
          row: at('#scan-found .scanrow'), name: at('#scan-found .scanrow .nm'),
          qty: at('#scan-found .scanrow .qty'),
          acts: at('#scan-found .scanacts'),
          drop: at('#scan-found .scanacts [data-drop]'),
          screen: window.innerHeight};
}"""

# Имя в колонку шириной в ноль переносится по одному слову, и высота строки
# разрастается. Считаем, во сколько строк легло имя: больше трёх -- развал.
LINES = """() => {
  const b = document.querySelector('#scan-found .scanrow .nm b');
  if (!b) return null;
  const cs = getComputedStyle(b);
  const line = parseFloat(cs.lineHeight) ||
               parseFloat(cs.fontSize) * 1.2;
  return {lines: Math.round(b.getBoundingClientRect().height / line),
          width: Math.round(b.getBoundingClientRect().width)};
}"""

print("=== сканер на телефоне ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport=PHONE, is_mobile=True,
                               has_touch=True).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(1500)
    page.click('.tab[data-tab="scan"]')
    page.wait_for_timeout(2000)

    put = page.evaluate(FAKE)
    ok(put == 2, "карты подложены в список", put)
    page.wait_for_timeout(600)

    w = page.evaluate(WHERE)

    print("--- камера на первом экране")
    cam = w["camera"]
    ok(cam is not None, "кнопка «Включить камеру» на месте")
    if cam:
        ok(cam["top"] + cam["height"] <= w["screen"],
           "кнопка «Включить камеру» видна без прокрутки",
           "её низ на %s при экране %s" % (cam["top"] + cam["height"],
                                           w["screen"]))
    news = w["news"]
    if news:
        ok(news["height"] <= w["screen"] * 0.45,
           "окно «что нового» не занимает пол-экрана",
           "%s точек при экране %s" % (news["height"], w["screen"]))

    print("--- строка найденной карты")
    row, nm, qty, acts, drop = (w["row"], w["name"], w["qty"], w["acts"],
                                w["drop"])
    ok(row is not None, "строка карты нарисована")
    if row and nm:
        ok(nm["width"] >= 120, "колонка имени не схлопнулась",
           "ширина %s" % nm["width"])
        ok(nm["right"] <= row["right"] + 1, "имя не вылезает за карточку",
           "%s при краю %s" % (nm["right"], row["right"]))
    if row and drop:
        ok(drop["right"] <= row["right"] + 1,
           "кнопка «убрать» не вылезает за карточку",
           "%s при краю %s" % (drop["right"], row["right"]))
    if nm and qty and acts:
        # Три ряда друг под другом: имя, количество, действия. Если сетка
        # снова встала в пять колонок, они окажутся на одной высоте.
        ok(qty["top"] >= nm["top"] + nm["height"] - 2 and
           acts["top"] >= qty["top"] + qty["height"] - 2,
           "имя, количество и действия стоят друг под другом",
           "имя %s, количество %s, действия %s" %
           (nm["top"], qty["top"], acts["top"]))
    got = page.evaluate(LINES)
    if got:
        # Ширина здесь не лишняя: в схлопнутой колонке имя переносится по
        # одному слову, но и строк выходит немного -- проверка на одни лишь
        # строки показывала PASS ровно на той беде, которую ищет.
        ok(got["lines"] <= 3 and got["width"] >= 120,
           "имя не рассыпалось по словам",
           "%s строк при ширине %s" % (got["lines"], got["width"]))

    print("--- количество без прокрутки")
    # Та самая жалоба: чтобы изменить количество у первой карты, не должно
    # приходиться листать. Страница у начала списка, минус и плюс -- рядом.
    if qty:
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(200)
        reach = page.evaluate("""() => {
          const q = document.querySelector('#scan-found .scanrow .qty');
          q.scrollIntoView({block: 'center'});
          const b = q.getBoundingClientRect();
          const btn = q.querySelectorAll('button');
          return {seen: b.top >= 0 && b.bottom <= window.innerHeight,
                  buttons: btn.length,
                  small: [...btn].filter((x) =>
                    x.getBoundingClientRect().height < 44).length};
        }""")
        ok(reach["seen"], "количество помещается на экран целиком")
        ok(reach["buttons"] >= 2 and reach["small"] == 0,
           "по «−» и «+» можно попасть пальцем",
           "кнопок %s, мельче 44 px: %s" % (reach["buttons"], reach["small"]))

    print("--- ничего не уезжает вбок")
    over = page.evaluate("""() => {
      const d = document.documentElement;
      return {page: d.scrollWidth, win: d.clientWidth};
    }""")
    ok(over["page"] <= over["win"] + 1, "сканер без прокрутки вбок",
       "%s при окне %s" % (over["page"], over["win"]))

    ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
