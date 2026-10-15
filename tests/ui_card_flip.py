"""Browser check: карты листаются прямо в открытом окне.

Открыв карту из выдачи, дальше смотрят следующую — а для этого приходилось
закрывать окно, вести мышь к соседней плитке и открывать снова.

Вторая половина проверки важнее первой: **окно по-прежнему закрывается**.
Стрелки добавлены внутрь окна именно потому, что нажатие по подложке закрывает
его, и кнопка, стоящая на подложке, закрывала бы окно при каждом промахе.
Поэтому здесь проверяется и то, что стрелки листают, и то, что нажатие мимо
окна закрывает, а нажатие по самой стрелке — нет.

    MTGH_UI_BASE=http://127.0.0.1:8773 .venv/Scripts/python.exe tests/ui_card_flip.py
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


def here(page, selector):
    return page.evaluate("(s) => !!document.querySelector(s)", selector)


def press(page, selector):
    """Нажать, если есть. Сценарий, который падает на отсутствующей кнопке,
    проверяет одно расхождение из шестнадцати: до остальных он не доходит."""
    return page.evaluate("""(s) => {
      const b = document.querySelector(s);
      if (!b) return false;
      b.click();
      return true;
    }""", selector)


def shown_name(page):
    return page.evaluate(
        "() => (document.querySelector('#modal-body h2') || {}).textContent || ''")


def strip_text(page):
    return page.evaluate(
        "() => (document.querySelector('.flipstrip') || {}).textContent || ''")


def modal_open(page):
    return page.evaluate("() => !document.querySelector('#overlay').hidden")


print("=== перелистывание в окне карты ===")

with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_timeout(1500)

    # ------------------------------------------------------------ выдача
    page.fill("#search-q", "goblin")
    page.keyboard.press("Enter")
    page.wait_for_timeout(3500)
    total = page.evaluate(
        "() => document.querySelectorAll('#search-results .card').length")
    ok(total > 3, "в выдаче есть что листать", total)

    page.evaluate("() => document.querySelectorAll('#search-results .card')[1].click()")
    page.wait_for_timeout(2500)
    first = shown_name(page)
    ok(here(page, ".flipstrip"), "в окне есть строка перелистывания")
    counter = strip_text(page)
    ok(re.search(r"\d+ из \d+", counter) is not None,
       "и в ней написано, где мы в списке", counter)

    press(page, ".flip.next")
    page.wait_for_timeout(2200)
    second = shown_name(page)
    ok(second and second != first, "«вперёд» открывает следующую карту",
       "%s -> %s" % (first, second))
    ok(modal_open(page), "и окно при этом остаётся открытым")

    press(page, ".flip.prev")
    page.wait_for_timeout(2200)
    ok(shown_name(page) == first, "«назад» возвращает к прежней",
       shown_name(page))

    # ------------------------------------------------------------ клавиши
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(2200)
    ok(shown_name(page) == second, "стрелка → листает тем же шагом",
       shown_name(page))
    page.keyboard.press("ArrowLeft")
    page.wait_for_timeout(2200)
    ok(shown_name(page) == first, "стрелка ← тоже")

    # Курсор сетки идёт за окном, а не живёт своей жизнью под ним.
    page.keyboard.press("ArrowRight")
    page.wait_for_timeout(2200)
    cursor_at = page.evaluate("""() => {
      const tiles = [...document.querySelectorAll('#search-results .card')];
      return tiles.findIndex((t) => t.classList.contains('cursor'));
    }""")
    strip_at = page.evaluate("""() => {
      const m = (document.querySelector('.flipstrip') || {}).textContent || '';
      const hit = m.match(/(\\d+) из/);
      return hit ? parseInt(hit[1], 10) - 1 : -1;
    }""")
    ok(cursor_at == strip_at,
       "курсор в выдаче идёт за открытой картой",
       "курсор %s, окно %s" % (cursor_at, strip_at))

    # --------------------------------------------- закрытие не сломалось
    press(page, ".flip.next")
    page.wait_for_timeout(1800)
    ok(modal_open(page), "нажатие по стрелке не закрывает окно")

    page.evaluate("""() => {
      const o = document.querySelector('#overlay');
      const r = o.getBoundingClientRect();
      o.dispatchEvent(new MouseEvent('click', {bubbles: true,
        clientX: r.left + 8, clientY: r.top + 8}));
    }""")
    page.wait_for_timeout(900)
    ok(not modal_open(page), "нажатие мимо окна по-прежнему закрывает его")

    page.evaluate("() => document.querySelectorAll('#search-results .card')[0].click()")
    page.wait_for_timeout(2200)
    page.keyboard.press("Escape")
    page.wait_for_timeout(700)
    ok(not modal_open(page), "Esc тоже закрывает")

    # ------------------------------------------------------------ колода
    decks = page.evaluate(
        "async () => (await fetch('/api/decks').then(r => r.json())).decks")
    page.click('.tab[data-tab="builder"]')
    page.wait_for_timeout(1200)
    if decks:
        page.evaluate("(id) => bdOpen(id)", decks[0]["id"])
        page.wait_for_timeout(2500)
    opened = page.evaluate("""() => {
      const rows = (bdDeck && bdDeck.cards) || [];
      if (rows.length < 2) return 0;
      bdOpenCard(rows[0]);
      return rows.length;
    }""")
    page.wait_for_timeout(2200)
    if opened:
        ok(here(page, ".flipstrip"), "в колоде окно карты тоже листается",
           strip_text(page))
        was = shown_name(page)
        press(page, ".flip.next")
        page.wait_for_timeout(2000)
        ok(shown_name(page) != was, "и открывает соседнюю карту колоды",
           "%s -> %s" % (was, shown_name(page)))
        page.evaluate("() => closeModal()")
    else:
        print("  ----  в колоде меньше двух карт — листать нечего")

    # --------------------------------------- одиночная карта: стрелок нет
    page.click('.tab[data-tab="search"]')
    page.wait_for_timeout(800)
    page.evaluate("() => openCard({name: 'Одна карта', legalities: {}})")
    page.wait_for_timeout(1200)
    ok(not here(page, ".flipstrip"),
       "когда листать нечего, строки перелистывания нет")
    page.evaluate("() => closeModal()")

    ok(not errors, "ошибок в консоли нет", "; ".join(errors[:3]))
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
sys.exit(1 if FAIL else 0)
