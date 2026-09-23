"""Browser check: панель форматов в билдере.

Проверяется то, ради чего она есть: посмотреть на колоду глазами другого
формата и увидеть не «не подходит», а список -- что мешает, чем заменить и что
добавить. Замена должна быть действием, а не советом: нажали -- и в колоде уже
другая карта, в том же количестве и в той же секции.

Создаёт свою колоду и удаляет её за собой.

    .venv/Scripts/python.exe tests/ui_formats.py
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
DECK_NAME = "UI Форматы"
CARDS = ["Lightning Bolt", "Fog", "Cultivate"]
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def sweep(page):
    return page.evaluate("""async (name) => {
      const r = await fetch('/api/decks').then(x => x.json());
      for (const d of r.decks.filter(d => d.name === name)) {
        await fetch('/api/decks/' + d.id, {method: 'DELETE'});
      }
      return (await fetch('/api/decks').then(x => x.json()))
        .decks.filter(d => d.name === name).length;
    }""", DECK_NAME)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")
    sweep(page)

    page.click('.tab[data-tab="builder"]')
    page.wait_for_function(
        "() => document.querySelector('#panel-builder.active') !== null", timeout=20000)
    page.wait_for_timeout(600)
    page.fill("#bd-newdeck", DECK_NAME)
    page.press("#bd-newdeck", "Enter")
    page.wait_for_function(
        "() => !document.querySelector('#bd-editor').hidden", timeout=20000)
    page.select_option("#bd-view", "rows")
    page.select_option("#bd-section", "main")
    for name in CARDS:
        page.fill("#bd-add", name)
        page.wait_for_function(
            "() => document.querySelectorAll('#bd-suggest .setrow').length > 0",
            timeout=30000)
        page.locator("#bd-suggest .setrow").first.click()
        page.wait_for_timeout(350)
    check("колода собрана", page.locator("#bd-cards .bdrow").count() == len(CARDS))

    print()
    print("=== панель форматов ===")
    page.click('#bd-actions button[data-act="formats"]')
    page.wait_for_selector("#bd-formats .fmtchip", timeout=20000)
    chips = page.eval_on_selector_all(
        "#bd-formats .fmtchip", "els => els.map(e => e.textContent)")
    check("показаны все форматы", len(chips) == 7, "%d" % len(chips))
    check("модерн среди них", any("Модерн" in c for c in chips))

    # Lightning Bolt не входит в пионер -- значит, там он и должен мешать.
    page.click('#bd-formats .fmtchip[data-fmt="pioneer"]')
    page.wait_for_timeout(500)
    # Имя мешающей карты -- кнопка: по ней открывается сама карта.
    blockers = page.eval_on_selector_all(
        "#bd-formats .fmtblockhead [data-open]", "els => els.map(e => e.textContent)")
    check("в пионере мешает Lightning Bolt",
          any("Lightning Bolt" in b for b in blockers), "; ".join(blockers))

    print()
    print("=== замена ===")
    page.click('#bd-formats button[data-replace="Lightning Bolt"]')
    page.wait_for_selector("#bd-formats .fmtcard", timeout=30000)
    picks = page.eval_on_selector_all(
        "#bd-formats .fmtcard [data-swap]", "els => els.map(e => e.dataset.swap)")
    check("предложены замены", len(picks) > 0, ", ".join(picks[:4]))

    legal = page.evaluate("""async (names) => {
      const out = [];
      for (const n of names) {
        const r = await fetch('/api/search?limit=5&q=' + encodeURIComponent(n))
          .then(x => x.json()).catch(() => null);
        const card = (r && r.cards || []).find(c => c.name === n);
        out.push([n, card ? (card.legalities || {}).pioneer : 'нет карты']);
      }
      return out;
    }""", picks[:4])
    check("все замены легальны в пионере",
          all(v == "legal" for _n, v in legal),
          "; ".join("%s=%s" % (n, v) for n, v in legal))

    chosen = picks[0]
    page.click('#bd-formats [data-swap="%s"]' % chosen)
    # Замена -- две правки: сначала кладётся новая карта, потом убирается
    # старая. Ждать надо обеих, иначе читаем состояние на полпути.
    page.wait_for_function(
        """(n) => bdDeck && bdDeck.cards.some(c => c.name === n)
           && !bdDeck.cards.some(c => c.name === 'Lightning Bolt')""",
        arg=chosen, timeout=30000)
    after = page.evaluate("""() => bdDeck.cards.map(
      c => [(c.card && c.card.name) || c.name, c.quantity, c.section])""")
    names = [a[0] for a in after]
    check("новая карта в колоде", chosen in names, ", ".join(names))
    check("старая карта убрана", "Lightning Bolt" not in names)
    check("количество и секция сохранены",
          [a for a in after if a[0] == chosen][0][1:] == [1, "main"],
          str([a for a in after if a[0] == chosen]))

    print()
    print("=== тематика ===")
    page.click("#bd-formats button[data-theme]")
    page.wait_for_selector("#bd-formats .fmttheme .fmtcards", timeout=30000)
    themes = page.text_content("#bd-formats .fmttheme p")
    check("тематика названа", "Тематика" in (themes or ""), (themes or "")[:80])
    check("есть что добавить",
          page.locator("#bd-formats .fmttheme [data-add]").count() > 0)

    print()
    check("нет ошибок в консоли", not errors, "; ".join(errors[:3]))
    left = sweep(page)
    check("тестовая колода удалена", left == 0)
    browser.close()

print()
print("ИТОГ: %s" % ("всё хорошо" if not FAIL else "провалено: " + "; ".join(FAIL)))
