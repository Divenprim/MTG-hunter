"""Browser check: the builder in columns, the way Archidekt does it.

"билдер не удобен, сделай как в архидек" -- what that shape actually gives you:
one column per category, cards stacked so each title bar stays readable, and
filing a card is a drag rather than typing into a field.

Dragging only means something when the columns ARE the filing, so it is enabled
under grouping by category and switched off (with a reason shown) under
groupings derived from the cards themselves.

Creates its own deck and deletes it at the end -- the user's decks are not
touched.

Needs a running server and Chromium:

    .venv/Scripts/python.exe tests/ui_builder_columns.py
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
DECK_NAME = "Колонки (тест)"
CARDS = ["Sol Ring", "Cultivate", "Counterspell", "Swords to Plowshares"]
NEW_CATEGORY = "Рампа"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def column_of(page, card_id):
    return page.evaluate("""(id) => {
      const el = document.querySelector('.stackcard[data-card="' + id + '"]');
      return el ? el.closest('.bdcolumn').dataset.group : null;
    }""", card_id)


def drag(page, card_id, selector):
    """Grab a stacked card by its visible strip, as a person would.

    Aiming at the middle of a stacked card hits the card lying on top of it --
    only the top strip of each card is actually exposed. That is how a stack
    works and how Archidekt behaves; the test has to point where a hand would.
    """
    src = page.locator('.stackcard[data-card="%s"]' % card_id).first
    dst = page.locator(selector).first
    src.scroll_into_view_if_needed()
    page.wait_for_timeout(200)
    src.hover(position={"x": 40, "y": 18})
    page.mouse.down()
    # Drag events only fire while the pointer MOVES, so the highlight has to be
    # measured during the movement, not after arriving.
    box = dst.bounding_box()
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 30, steps=8)
    page.wait_for_timeout(200)
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + 40, steps=4)
    page.wait_for_timeout(200)
    highlighted = page.locator("#bd-cards .bdcolumn.over").count()
    page.mouse.up()
    page.wait_for_timeout(2500)
    return highlighted


with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_context(viewport={"width": 1500, "height": 950}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    # The "new category" column asks for a name.
    page.on("dialog", lambda d: d.accept(NEW_CATEGORY))
    page.goto(BASE, wait_until="networkidle")

    page.click('.tab[data-tab="builder"]')
    page.wait_for_function(
        "() => document.querySelector('#panel-builder.active') !== null", timeout=20000)
    page.wait_for_timeout(700)

    print("=== a deck of our own ===")
    page.fill("#bd-newdeck", DECK_NAME)
    page.press("#bd-newdeck", "Enter")
    page.wait_for_function("() => !document.querySelector('#bd-editor').hidden", timeout=20000)
    for name in CARDS:
        page.fill("#bd-add", name)
        page.wait_for_function(
            "() => document.querySelectorAll('#bd-suggest .setrow').length > 0", timeout=20000)
        page.locator("#bd-suggest .setrow").first.click()
        page.wait_for_timeout(450)
    check("колода создана и наполнена",
          page.locator("#bd-cards .bdrow, #bd-cards .stackcard").count() >= len(CARDS))

    print()
    print("=== the columns ===")
    page.select_option("#bd-group", "category")
    page.select_option("#bd-view", "columns")
    page.wait_for_timeout(1200)
    cols = page.locator("#bd-cards .bdcolumn").count()
    stacked = page.locator("#bd-cards .stackcard").count()
    check("вид колонками собрался", cols >= 2 and stacked >= len(CARDS),
          "%d колонок, %d карт" % (cols, stacked))
    heads = page.evaluate(
        """() => [...document.querySelectorAll('#bd-cards .bdcolumn .colhead b')]
             .map(e => e.textContent.trim())""")
    print("      колонки: " + str(heads))
    check("есть колонка «новая категория»",
          page.locator("#bd-cards .bdcolumn.newcol").count() == 1)
    check("в заголовке колонки видно количество",
          "шт." in (page.locator("#bd-cards .colhead .meta").first.text_content() or ""))

    # The card element IS the exposed strip; its picture spills upward over the
    # cards above. So the strip is the element height and the card is the image.
    geo = page.evaluate("""() => {
      const cards = [...document.querySelectorAll('#bd-cards .bdstack .stackcard')];
      if (cards.length < 2) return null;
      const a = cards[0].getBoundingClientRect();
      const c = cards[1].getBoundingClientRect();
      const img = cards[0].querySelector('img').getBoundingClientRect();
      const stack = cards[0].closest('.bdstack').getBoundingClientRect();
      const last = cards[cards.length - 1].querySelector('img').getBoundingClientRect();
      return {
        strip: Math.round(c.top - a.top),
        card: Math.round(img.height),
        n: cards.length,
        stack: Math.round(stack.height),
        overflow: Math.round(last.bottom - stack.bottom),
      };
    }""")
    print("      полоса %s px из карты %s px, %s карт → стопка %s px"
          % ((geo or {}).get("strip"), (geo or {}).get("card"),
             (geo or {}).get("n"), (geo or {}).get("stack")))
    # A stack shows the title bar, not half the card. The first version left 47%
    # of every card visible and a column of 24 creatures was 2328 px tall.
    share = round(geo["strip"] / geo["card"] * 100) if geo else 0
    check("видна только шапка карты, а не половина", 8 <= share <= 20,
          "видно %d%% карты" % share)
    check("полоса всё же достаточна, чтобы в неё попасть",
          geo and geo["strip"] >= 22, "полоса %s px" % (geo or {}).get("strip"))
    # (n-1) strips plus one whole card: the column is exactly as tall as it needs.
    expected = (geo["n"] - 1) * geo["strip"] + geo["card"] if geo else 0
    check("высота колонки ровно под содержимое",
          geo and abs(geo["stack"] - expected) <= 4,
          "%s px против ожидаемых %s" % ((geo or {}).get("stack"), expected))
    check("последняя карта не вылезает из колонки",
          geo and geo["overflow"] <= 2, "вылезает на %s px" % (geo or {}).get("overflow"))

    print()
    print("=== dragging onto the new-category column ===")
    first_id = page.locator("#bd-cards .stackcard").first.get_attribute("data-card")
    highlighted = drag(page, first_id, "#bd-cards .bdcolumn.newcol")
    check("колонка подсветилась под курсором", highlighted >= 1, "%d" % highlighted)
    where = column_of(page, first_id)
    print("      карта теперь в: " + str(where))
    check("карта попала в созданную категорию", where == NEW_CATEGORY, str(where))

    print()
    print("=== dragging between existing columns ===")
    other = page.evaluate("""(cat) => {
      const el = [...document.querySelectorAll('#bd-cards .stackcard')]
        .find(x => x.closest('.bdcolumn').dataset.group !== cat);
      return el ? el.dataset.card : null;
    }""", NEW_CATEGORY)
    if not other:
        check("есть карта в другой колонке", False, "все карты в одной категории")
    else:
        drag(page, other, '#bd-cards .bdcolumn[data-group="%s"]' % NEW_CATEGORY)
        check("вторая карта тоже переехала",
              column_of(page, other) == NEW_CATEGORY, str(column_of(page, other)))
        counted = page.evaluate("""(cat) => {
          const col = document.querySelector('.bdcolumn[data-group="' + cat + '"]');
          return col ? col.querySelectorAll('.stackcard').length : 0;
        }""", NEW_CATEGORY)
        check("в колонке стало две карты", counted == 2, "%d" % counted)

    print()
    print("=== a grouping the cards define cannot be dragged ===")
    page.select_option("#bd-group", "cmc")
    page.wait_for_timeout(900)
    draggable = page.evaluate(
        """() => document.querySelectorAll('#bd-cards .stackcard[draggable="true"]').length""")
    check("перетаскивание выключено", draggable == 0, "%d перетаскиваемых" % draggable)
    hint = " ".join((page.locator("#bd-cards .colhint").text_content() or "").split())
    check("и сказано, почему", "перетаскиванием" in hint, hint[:60])
    print("      " + hint[:100])

    print()
    print("=== the other views still work ===")
    page.select_option("#bd-group", "category")
    for view in ("rows", "compact", "grid"):
        page.select_option("#bd-view", view)
        page.wait_for_timeout(500)
        n = page.locator("#bd-cards .bdrow, #bd-cards .gcard").count()
        check("вид «%s» рисуется" % view, n >= len(CARDS), "%d элементов" % n)

    print()
    print("=== cleanup ===")
    page.select_option("#bd-view", "rows")
    page.wait_for_timeout(300)
    page.click("#bd-delete")
    gone = True
    try:
        page.wait_for_function(
            """(name) => ![...document.querySelectorAll('#bd-decks .bddeck .nm')]
                 .some(e => e.textContent.trim() === name)""",
            arg=DECK_NAME, timeout=20000)
    except Exception:
        gone = False
    left = [t.strip() for t in page.locator("#bd-decks .bddeck .nm").all_text_contents()]
    check("тестовая колода удалена, ваши на месте", gone and DECK_NAME not in left,
          "осталось: %s" % left)

    print()
    check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
    page.screenshot(path="tests/ui_builder_columns.png")
    b.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL COLUMN CHECKS PASSED")
