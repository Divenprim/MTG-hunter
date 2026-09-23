"""Browser check: читаемость. Каждый видимый текст против фона под ним.

Заведён после того, как стало нечитаемо сразу в трёх местах, и ни одно из них
не видно из кода поодиночке:

  * теги-назначения сделали кнопками, а глобальное правило button красит текст
    в --on-accent, то есть в почти чёрный, -- на тёмном фоне не видно ничего;
  * у меню карты фоном стоял var(--panel), а такого токена в style.css нет:
    меню рисовалось насквозь, поверх статистики колоды;
  * количество и цена на карточке стоят на тёмной ленте поверх картинки, а
    цвет текста брали из темы -- в светлой теме это чёрное на чёрном.

Поэтому проверка не по списку правил, а сплошная: обходятся все вкладки и оба
режима темы, у каждого элемента с собственным текстом берётся настоящий цвет и
настоящий фон под ним. Норма WCAG AA: 4.5 для мелкого текста, 3.0 для крупного
(18px и больше либо 14px жирного).

Колоду сценарий не меняет: он только смотрит.

    .venv/Scripts/python.exe tests/ui_contrast.py
"""

import json
import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from playwright.sync_api import sync_playwright          # noqa: E402

BASE = "http://127.0.0.1:8765"
FAIL = []

SWEEP = """() => {
  const lum = (c) => {
    const m = (c.match(/[\\d.]+/g) || [0, 0, 0]).map(Number);
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92
      : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(m[0]) + 0.7152 * f(m[1]) + 0.0722 * f(m[2]);
  };
  // Полупрозрачный фон -- это ещё не фон: под ним лежит настоящий.
  const solid = (c) => {
    const m = c.match(/[\\d.]+/g);
    return m && (m.length < 4 || Number(m[3]) > 0.5);
  };
  const bgOf = (el) => {
    let node = el;
    while (node) {
      const c = getComputedStyle(node).backgroundColor;
      if (solid(c)) return c;
      node = node.parentElement;
    }
    return getComputedStyle(document.body).backgroundColor;
  };
  const ratio = (a, b) => {
    const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p);
    return (x + 0.05) / (y + 0.05);
  };
  const out = {};
  document.querySelectorAll("*").forEach((el) => {
    if (!el.offsetParent && getComputedStyle(el).position !== "fixed") return;
    const own = [...el.childNodes].some(
      (n) => n.nodeType === 3 && n.textContent.trim().length > 1);
    if (!own) return;
    const box = el.getBoundingClientRect();
    if (box.width < 4 || box.height < 4) return;
    const cs = getComputedStyle(el);
    if (cs.visibility === "hidden" || Number(cs.opacity) < 0.3) return;
    const size = parseFloat(cs.fontSize);
    const need = (size >= 18 || (size >= 14 && Number(cs.fontWeight) >= 600))
      ? 3.0 : 4.5;
    const got = ratio(cs.color, bgOf(el));
    if (got >= need) return;
    const key = el.tagName.toLowerCase() + "." +
      el.className.toString().split(" ").filter(Boolean).slice(0, 2).join(".");
    if (out[key] && out[key].ratio <= got) return;
    out[key] = {what: key, ratio: Math.round(got * 100) / 100, need: need,
                color: cs.color, text: el.textContent.trim().slice(0, 24)};
  });
  return Object.values(out);
}"""

SETUP = """async (name) => {
  const made = await fetch('/api/decks', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name: name, format: 'modern'})}).then(r => r.json());
  await fetch('/api/decks/' + made.deck.id + '/cards', {method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({cards: [
      {name: 'Ethereal Haze', quantity: 4, section: 'main'},
      {name: 'Fog', quantity: 4, section: 'main'},
      {name: 'Isochron Scepter', quantity: 1, section: 'main'},
      {name: 'Sol Ring', quantity: 1, section: 'side'}]})});
  return made.deck.id;
}"""

CLEAN = """async (name) => {
  const list = await fetch('/api/decks').then(r => r.json());
  for (const d of list.decks.filter(d => d.name === name)) {
    await fetch('/api/decks/' + d.id, {method: 'DELETE'});
  }
}"""

DECK = "UI Контраст"
found = {}


def sweep(page, where, theme):
    for row in page.evaluate(SWEEP):
        key = (theme, row["what"])
        if key in found and found[key]["ratio"] <= row["ratio"]:
            continue
        row["where"] = where
        found[key] = row


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1100}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.goto(BASE, wait_until="networkidle")
    page.evaluate(CLEAN, DECK)
    deck_id = page.evaluate(SETUP, DECK)

    for theme in ("dark", "light"):
        page.evaluate("(t) => document.documentElement.dataset.theme = t", theme)

        page.click('.tab[data-tab="search"]')
        page.fill("#search-q", "fog")
        page.keyboard.press("Enter")
        page.wait_for_timeout(2500)
        sweep(page, "поиск", theme)

        page.evaluate("""() => {
          const el = document.querySelector('#results .card');
          if (el) el.click();
        }""")
        page.wait_for_timeout(1800)
        sweep(page, "окно карты", theme)
        page.evaluate("() => closeModal()")

        page.click('.tab[data-tab="builder"]')
        page.wait_for_timeout(700)
        page.evaluate("(id) => bdOpen(id)", deck_id)
        page.wait_for_timeout(1500)
        sweep(page, "билдер", theme)

        # Панель форматов: разбор, назначения-кнопки, план варианта.
        page.evaluate("() => fmtOpen()")
        page.wait_for_selector(".fmtchip", timeout=30000)
        page.click('.fmtchip[data-fmt="pioneer"]')
        page.wait_for_selector(".fmtblock", timeout=20000)
        page.click('[data-replace="Ethereal Haze"]')
        page.wait_for_selector(".fmtcard", timeout=60000)
        page.wait_for_timeout(600)
        sweep(page, "форматы", theme)
        page.evaluate("""() => {
          const chip = document.querySelector('.jobchip');
          if (chip) chip.click();
        }""")
        page.wait_for_timeout(1500)
        sweep(page, "отбор по назначению", theme)
        page.evaluate("() => { fmtPanel().hidden = true; }")

        # Плейтест: стол со своими зонами, кнопками и стопками.
        page.evaluate("(id) => ptOpen(id)", deck_id)
        page.wait_for_selector("#pt-body .pthand .ptcard", timeout=60000)
        page.wait_for_timeout(400)
        sweep(page, "плейтест", theme)
        page.evaluate("() => ptClose()")

        # Меню карты -- то самое, что рисовалось без фона.
        page.evaluate("""() => {
          const row = document.querySelector('#bd-cards .stackcard, #bd-cards .bdrow');
          if (row) row.dispatchEvent(new MouseEvent('contextmenu',
            {bubbles: true, cancelable: true, clientX: 300, clientY: 300}));
        }""")
        page.wait_for_selector(".cardmenu", timeout=20000)
        sweep(page, "меню карты", theme)
        page.evaluate("() => closeCardMenu()")

        for tab in ("hunt", "collection", "favourites", "family", "scan", "deck"):
            page.click('.tab[data-tab="%s"]' % tab)
            page.wait_for_timeout(1200)
            sweep(page, tab, theme)

    page.evaluate(CLEAN, DECK)
    browser.close()

print("=== читаемость текста ===")
for (theme, _key), row in sorted(found.items(), key=lambda p: p[1]["ratio"]):
    print("  FAIL  %s, %s: %s — контраст %.2f при норме %.1f (%s)" % (
        theme, row["where"], row["what"], row["ratio"], row["need"], row["text"]))
    FAIL.append("%s/%s" % (theme, row["what"]))
if not found:
    print("  PASS  весь текст читаем в обеих темах")

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
