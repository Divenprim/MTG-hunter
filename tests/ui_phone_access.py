"""Browser check: телефон и клавиатура.

Заведён после замера на экране 390 px, где одновременно сошлось пять вещей,
и ни одну из них не видно из кода:

  * «Получено → в коллекцию» -- серым по золотому. Класс `.tiny` задуман для
    подписи и несёт свой цвет; на кнопке он перебивал её собственный, потому
    что класс сильнее имени тега. Контраст 1.22 в тёмной теме, 1.09 в
    светлой при норме 4.5;
  * тридцать элементов мельче 44 px -- флажки 20, мелкие кнопки 36, вкладки
    42. Вкладки держались на 42 из-за селектора с тремя :not(): он сильнее
    правила `button` ниже по файлу, и то просто не работало;
  * «Избранное» -- единственная вкладка с горизонтальной прокруткой: 407 px
    при экране 390;
  * полоса вкладок длиннее экрана вдвое, и вкладка останавливалась где
    попало: слева читалось «лдер» вместо «Билдер»;
  * фокуса с клавиатуры не было видно нигде: своего стиля в CSS нет ни
    одного, браузерный -- тёмный по тёмному.

Проверка смотрит, но ничего не меняет: ни колод, ни коллекции не трогает.

    .venv/Scripts/python.exe tests/ui_phone_access.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
FAIL = []
TABS = ("search", "builder", "collection", "favourites", "hunt", "deck",
        "family", "scan")

# Эти остаются мельче нормы намеренно: мелкие значки стоят вплотную к крупным
# в одном ряду, и раздувать их значит ломать ряд. Промах по ним ничего не
# запускает -- это переключатели вида, а не действия.
ALLOWED_SMALL = ("theme-switch", "density", "dots", "cardmore", "ptmore",
                 "modal-close", "famcell", "crown")


def ok(cond, label, extra=""):
    print("  %s  %s%s" % ("PASS" if cond else "FAIL", label,
                          "" if not extra else " — " + str(extra)))
    if not cond:
        FAIL.append(label)


OVERFLOW = """() => {
  const d = document.documentElement;
  return {page: d.scrollWidth, win: d.clientWidth,
          who: [...document.querySelectorAll('*')]
            .filter((el) => el.offsetParent &&
                     el.getBoundingClientRect().right > d.clientWidth + 1)
            .slice(0, 4)
            .map((el) => el.tagName.toLowerCase() + '.' +
                 el.className.toString().split(' ').filter(Boolean)[0])};
}"""

SMALL = """(allowed) => {
  const out = [];
  document.querySelectorAll('button, select, .tab, a[href]').forEach((el) => {
    if (!el.offsetParent) return;
    const b = el.getBoundingClientRect();
    if (b.width < 2 || b.height < 2) return;
    if (b.height >= 44) return;
    const id = (el.id || '') + ' ' + el.className.toString() + ' ' +
               (el.parentElement ? el.parentElement.className.toString() : '');
    if (allowed.some((a) => id.indexOf(a) >= 0)) return;
    out.push({h: Math.round(b.height),
              what: el.tagName.toLowerCase() + '.' +
                    el.className.toString().split(' ').filter(Boolean)[0],
              text: (el.textContent || '').trim().slice(0, 18)});
  });
  return out;
}"""

STRIP = """() => {
  const strip = document.querySelector('.tabs');
  const now = strip.querySelector('.tab.active');
  const s = strip.getBoundingClientRect();
  const b = now.getBoundingClientRect();
  return {scroll: strip.scrollWidth, seen: strip.clientWidth,
          left: strip.scrollLeft,
          cut: Math.round(Math.max(s.left - b.left, b.right - s.right)),
          hint: strip.className,
          name: (now.textContent || '').trim()};
}"""

RING = """() => {
  const el = document.activeElement;
  const cs = getComputedStyle(el);
  return {what: el.tagName.toLowerCase() + '.' + el.className.toString(),
          style: cs.outlineStyle,
          width: parseFloat(cs.outlineWidth) || 0,
          color: cs.outlineColor,
          visible: el.matches(':focus-visible')};
}"""

CONTRAST = """() => {
  const lum = (c) => {
    const m = (c.match(/[\\d.]+/g) || [0, 0, 0]).map(Number);
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92
      : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(m[0]) + 0.7152 * f(m[1]) + 0.0722 * f(m[2]);
  };
  const ratio = (a, b) => {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return Math.round(((x + 0.05) / (y + 0.05)) * 100) / 100;
  };
  const probe = (cls) => {
    const el = document.createElement('button');
    el.className = cls;
    el.textContent = 'Получено';
    document.body.appendChild(el);
    const cs = getComputedStyle(el);
    let bg = cs.backgroundColor;
    const m = bg.match(/[\\d.]+/g);
    if (m && m.length > 3 && Number(m[3]) < 0.5) {
      bg = getComputedStyle(document.body).backgroundColor;
    }
    const got = ratio(cs.color, bg);
    el.remove();
    return got;
  };
  return {solid: probe('tiny'), ghost: probe('ghost tiny')};
}"""

print("=== телефон и клавиатура ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()

    # -------------------------------------------------- палец, экран 390 px
    page = browser.new_context(viewport={"width": 390, "height": 844},
                              is_mobile=True, has_touch=True).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(1200)

    print("--- ничего не уезжает вбок")
    for tab in TABS:
        page.click('.tab[data-tab="%s"]' % tab)
        page.wait_for_timeout(800)
        over = page.evaluate(OVERFLOW)
        ok(over["page"] <= over["win"] + 1, "%s без прокрутки вбок" % tab,
           "%s при окне %s, виноваты %s" % (over["page"], over["win"], over["who"])
           if over["page"] > over["win"] + 1 else "")

    print("--- палец: 44 px")
    page.click('.tab[data-tab="hunt"]')
    page.wait_for_timeout(800)
    small = page.evaluate(SMALL, list(ALLOWED_SMALL))
    seen = {}
    for s in small:
        seen.setdefault(s["what"] + "/" + s["text"], s)
    ok(not seen, "всё нажимаемое не ниже 44 px",
       "; ".join("%s %dpx %s" % (s["what"], s["h"], s["text"])
                 for s in list(seen.values())[:6]))

    print("--- полоса вкладок")
    # Полосу заранее уводим в противоположный край: именно так и получалось
    # «лдер» вместо «Билдера» -- раздел открыт, а вкладка его осталась за краем.
    for tab, edge in (("deck", 0), ("search", 99999), ("scan", 0)):
        page.evaluate("(x) => { document.querySelector('.tabs').scrollLeft = x; }",
                      edge)
        page.wait_for_timeout(200)
        page.evaluate("(t) => document.querySelector('.tab[data-tab=' + t + ']')"
                      ".click()", tab)
        page.wait_for_timeout(600)
        st = page.evaluate(STRIP)
        ok(st["cut"] <= 1, "вкладка «%s» видна целиком" % st["name"],
           "срезано %s px" % st["cut"] if st["cut"] > 1 else "")
    st = page.evaluate(STRIP)
    ok(st["scroll"] > st["seen"], "полоса действительно длиннее экрана",
       "%s при видимых %s" % (st["scroll"], st["seen"]))
    ok("more-" in st["hint"], "у края полосы есть признак продолжения",
       st["hint"])
    page.evaluate("() => { const s = document.querySelector('.tabs');"
                  " s.scrollLeft = s.scrollWidth; }")
    page.wait_for_timeout(300)
    st = page.evaluate(STRIP)
    ok("more-right" not in st["hint"],
       "в самом конце признака продолжения нет", st["hint"])

    print("--- читаемость мелких кнопок")
    for theme in ("dark", "light"):
        page.evaluate("(t) => document.documentElement.dataset.theme = t", theme)
        page.wait_for_timeout(200)
        got = page.evaluate(CONTRAST)
        ok(got["solid"] >= 4.5, "«Получено → в коллекцию», тема %s" % theme,
           "контраст %s при норме 4.5" % got["solid"])
        ok(got["ghost"] >= 4.5, "мелкая ghost-кнопка, тема %s" % theme,
           "контраст %s при норме 4.5" % got["ghost"])
    page.evaluate("() => document.documentElement.dataset.theme = 'dark'")

    ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))
    page.close()

    # ------------------------------------------------------------ клавиатура
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(900)

    print("--- фокус с клавиатуры виден")
    page.keyboard.press("Tab")
    page.wait_for_timeout(150)
    seen_ring = False
    for _ in range(14):
        ring = page.evaluate(RING)
        if ring["visible"] and ring["style"] != "none" and ring["width"] >= 2:
            seen_ring = True
            break
        page.keyboard.press("Tab")
        page.wait_for_timeout(100)
    ring = page.evaluate(RING)
    ok(seen_ring, "контур фокуса толщиной от 2 px",
       "%s: %s %spx" % (ring["what"], ring["style"], ring["width"]))

    # Активная вкладка: фон акцентный, значит и контур на ней должен быть не
    # акцентным, иначе он сливается.
    page.evaluate("""() => {
      const t = document.querySelector('.tab.active');
      t.focus();
      t.classList.add('probe');
    }""")
    page.wait_for_timeout(150)
    pair = page.evaluate("""() => {
      const t = document.querySelector('.tab.probe');
      const cs = getComputedStyle(t);
      t.classList.remove('probe');
      return {outline: cs.outlineColor, bg: cs.backgroundColor};
    }""")
    ok(pair["outline"] != pair["bg"],
       "на активной вкладке контур не сливается с фоном", pair)
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
