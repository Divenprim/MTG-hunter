"""Real browser check of the UI.

Not part of the unit suite: it needs a running server and Chromium.

    python -m playwright install chromium      # once
    .venv/Scripts/python.exe tests/ui_check.py

Exists because static analysis cannot catch what actually broke the page: an
always-visible overlay swallowing every click. It loads the app with a cold
cache, reports console errors, and verifies that the things you click respond.
"""

import sys
import time

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
FAIL = []
SHOT = "tests/ui_shot.png"


def clear_meta(page):
    """Blank the status line so the next wait cannot match the previous search."""
    page.evaluate(
        "() => { const m = document.querySelector('#search-meta');"
        " if (m) m.textContent = ''; }"
    )


def wait_results(page, timeout=25000):
    """Wait until the search has actually settled.

    Two traps this avoids:
      * a fixed sleep turns "slow" into "zero results";
      * waiting only for the spinner to vanish succeeds INSTANTLY when the
        search has not started yet (the input is debounced), so the assertion
        reads the previous query's grid. Hence clear_meta() before acting and
        a wait for real settled text here.
    """
    page.wait_for_function(
        "() => { const m = document.querySelector('#search-meta');"
        " if (!m || m.querySelector('.spinner')) return false;"
        " const t = m.textContent || '';"
        " return t.indexOf('показано') >= 0 || t.indexOf('ничего') >= 0; }",
        timeout=timeout,
    )


def set_collection(page, text):
    """Install a known collection through the API.

    The deck checks need to know what is owned; relying on whatever the user
    happens to have makes them pass or fail at random.
    """
    page.evaluate(
        """async (text) => {
            await fetch('/api/collection', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({text: text}),
            });
        }""",
        text,
    )


def restore_collection(page, saved):
    """Put the user's own collection back."""
    lines = [str(count) + " " + name for name, count in (saved or {}).items()]
    set_collection(page, chr(10).join(lines))


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        # bypass_cache-ish: a fresh context has no cache at all
        page = browser.new_context(viewport={"width": 1500, "height": 950}).new_page()

        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append("pageerror: %s" % e))

        print("=== load ===")
        page.goto(BASE, wait_until="networkidle")
        check("page loads", True)
        check("no console errors", not errors, "; ".join(errors[:3]))

        print()
        print("=== nothing is covering the page ===")
        check("overlay hidden", page.locator("#overlay").is_hidden() is True)
        check("filters panel hidden", page.locator("#filters-panel").is_hidden() is True)
        check("deck actions hidden", page.locator("#deck-actions").is_hidden() is True)
        check("hunt actions hidden", page.locator("#hunt-actions").is_hidden() is True)

        # What element actually receives a click in the middle of the page?
        at_center = page.evaluate(
            "() => { const e = document.elementFromPoint(innerWidth/2, innerHeight/2);"
            " return e ? (e.id || e.className || e.tagName) : 'none'; }"
        )
        check("centre of page is not the overlay", "overlay" not in str(at_center),
              "elementFromPoint -> %s" % at_center)

        print()
        print("=== tabs ===")
        for name in ("deck", "hunt", "collection", "search"):
            page.click('.tab[data-tab="%s"]' % name)
            visible = page.locator("#panel-" + name).is_visible()
            check("tab %s opens its panel" % name, visible)

        print()
        print("=== search ===")
        page.click('.tab[data-tab="search"]')
        clear_meta(page)
        page.fill("#search-q", "Lightning Bolt")
        wait_results(page)
        cards = page.locator("#search-results .card").count()
        check("search returns cards", cards > 0, "%d tiles" % cards)
        first_name = page.locator("#search-results .card .cardname").first.text_content() if cards else ""
        check("first hit is the card itself", first_name.strip() == "Lightning Bolt",
              "got %r" % first_name)

        print()
        print("=== filters panel ===")
        page.click("#filters-toggle")
        check("filters panel opens", page.locator("#filters-panel").is_visible())
        page.click('#f-colors .cbtn[data-c="R"]')
        clear_meta(page)
        page.click("#filters-apply")
        wait_results(page)
        composed = page.input_value("#search-q")
        check("filters compose into the query box", "c:r" in composed, "query=%r" % composed)
        clear_meta(page)
        page.click("#filters-reset")
        wait_results(page)
        page.click("#filters-toggle")
        check("filters panel closes again", page.locator("#filters-panel").is_hidden())

        print()
        print("=== type picker (tokens, not checkboxes) ===")
        clear_meta(page)
        page.fill("#search-q", "")
        page.wait_for_timeout(700)
        if page.locator("#filters-panel").is_hidden():
            page.click("#filters-toggle")
        # quick button
        clear_meta(page)
        page.click('#f-type-quick button[data-type="Creature"]')
        wait_results(page)
        chips = page.locator("#f-type-chips .chip").count()
        check("quick button adds a type token", chips == 1, "%d tokens" % chips)
        check("query gains the type", "t:creature" in page.input_value("#search-q"),
              page.input_value("#search-q"))
        # typed subtype
        page.fill("#f-type-input", "Dragon")
        clear_meta(page)
        page.press("#f-type-input", "Enter")
        wait_results(page)
        chips = page.locator("#f-type-chips .chip").count()
        check("typing a subtype adds a second token", chips == 2, "%d tokens" % chips)
        composed = page.input_value("#search-q")
        check("both types are in the query (AND)",
              "t:creature" in composed and "t:dragon" in composed, composed)
        found = page.locator("#search-results .card").count()
        check("creature+dragon returns results", found > 0, "%d tiles" % found)
        # remove one token
        clear_meta(page)
        page.locator("#f-type-chips .chip").first.click()
        wait_results(page)
        check("clicking a token removes it",
              page.locator("#f-type-chips .chip").count() == 1)
        clear_meta(page)
        page.click("#filters-reset")
        wait_results(page)
        check("reset clears the tokens", page.locator("#f-type-chips .chip").count() == 0)
        page.click("#filters-toggle")

        print()
        print("=== set picker & Secret Lair ===")
        if page.locator("#filters-panel").is_hidden():
            page.click("#filters-toggle")
        rows = page.locator("#f-set-list .setrow").count()
        check("set list is populated on load", rows > 0, "%d rows" % rows)
        page.fill("#f-set-input", "modern horizons")
        page.wait_for_timeout(500)
        rows = page.locator("#f-set-list .setrow").count()
        check("typing filters the set list", rows > 0, "%d rows" % rows)
        clear_meta(page)
        page.locator("#f-set-list .setrow").first.click()
        wait_results(page)
        check("clicking a set adds a chip", page.locator("#f-set-chips .chip").count() == 1)
        check("query gains s:", "s:" in page.input_value("#search-q"),
              page.input_value("#search-q"))
        clear_meta(page)
        page.locator("#f-set-chips .chip").first.click()
        wait_results(page)

        clear_meta(page)
        page.click('#f-set-quick button[data-group="secretlair"]')
        wait_results(page)
        composed = page.input_value("#search-q")
        check("Secret Lair is one click", "s:secretlair" in composed, composed)
        found = page.locator("#search-results .card").count()
        check("Secret Lair returns cards", found > 0, "%d tiles" % found)
        clear_meta(page)
        page.click('#f-flags button[data-flag="borderless"]')
        wait_results(page)
        composed = page.input_value("#search-q")
        check("treatment flag joins the query",
              "is:borderless" in composed and "s:secretlair" in composed, composed)
        narrowed = page.locator("#search-results .card").count()
        check("borderless narrows Secret Lair", narrowed > 0, "%d tiles" % narrowed)
        clear_meta(page)
        page.click("#filters-reset")
        wait_results(page)
        check("reset clears sets and flags",
              page.locator("#f-set-chips .chip").count() == 0
              and page.locator("#f-flags button.on").count() == 0)
        page.click("#filters-toggle")


        print()
        print("=== Secret Lair drop picker ===")
        if page.locator("#filters-panel").is_hidden():
            page.click("#filters-toggle")
        page.wait_for_timeout(400)
        rows = page.locator("#f-drop-list .droprow").count()
        check("drop list is populated on load", rows > 0, "%d rows" % rows)

        page.fill("#f-drop-input", "sonic")
        page.wait_for_timeout(1200)
        rows = page.locator("#f-drop-list .droprow").count()
        check("searching a drop by a card inside it works", rows > 0, "%d drops" % rows)
        listing = page.locator("#f-drop-list").text_content() or ""
        check("the Sonic drop lists its other cards too",
              "Amy Rose" in listing and "Knuckles" in listing,
              "list text: %r" % listing[:110])

        clear_meta(page)
        page.locator("#f-drop-list .droprow").first.click()
        wait_results(page)
        composed = page.input_value("#search-q")
        check("picking a drop pins the number range",
              "cn>=" in composed and "cn<=" in composed, composed)
        check("drop chip appears", page.locator("#f-drop-chips .chip").count() == 1)
        found = page.locator("#search-results .card").count()
        check("the drop returns its cards", found > 0, "%d tiles" % found)
        names = page.locator("#search-results").text_content() or ""
        check("drop results include the non-obvious members",
              "Amy Rose" in names or "Knuckles" in names,
              "results: %r" % names[:110])

        # a filter click must not lose the pinned range
        clear_meta(page)
        page.click('#f-type-quick button[data-type="Creature"]')
        wait_results(page)
        composed = page.input_value("#search-q")
        check("adding a filter keeps the drop range",
              "cn>=" in composed and "t:creature" in composed, composed)

        clear_meta(page)
        page.click("#filters-reset")
        wait_results(page)
        check("reset clears the drop", page.locator("#f-drop-chips .chip").count() == 0)
        page.click("#filters-toggle")

        print()
        print("=== exact match stays first in every sort ===")
        clear_meta(page)
        page.fill("#search-q", "tiamat")
        wait_results(page)
        for sort in ("relevance", "price_asc", "released", "name", "cmc"):
            clear_meta(page)
            page.select_option("#search-sort", sort)
            wait_results(page)
            first = page.locator("#search-results .card .cardname").first.text_content()
            check("sort=%s puts Tiamat first" % sort, first.strip() == "Tiamat",
                  "got %r" % first.strip())
        clear_meta(page)
        page.select_option("#search-sort", "relevance")
        wait_results(page)

        print()
        print("=== card modal ===")
        clear_meta(page)
        page.fill("#search-q", "Fable of the Mirror-Breaker")
        wait_results(page)
        first_tile_name = page.locator("#search-results .card .cardname").first.text_content()
        check("modal test is looking at the right card",
              "Fable" in first_tile_name or "Reflection" in first_tile_name,
              "first tile is %r" % first_tile_name)
        if page.locator("#search-results .card").count() == 0:
            check("modal: had a card to click", False)
        else:
            page.locator("#search-results .card").first.click()
            page.wait_for_timeout(600)
            check("modal opens", page.locator("#overlay").is_visible())
            check("modal shows an image", page.locator("#modal-art").count() > 0)
            check("flip button present for a two-faced card",
                  page.locator("#modal-flip").count() > 0)
            if page.locator("#modal-flip").count():
                before = page.get_attribute("#modal-art", "src")
                page.click("#modal-flip")
                page.wait_for_timeout(400)
                after = page.get_attribute("#modal-art", "src")
                check("flip changes the artwork", before != after)
            page.wait_for_timeout(900)
            rows = page.locator("#modal-printings tr").count()
            check("printings list loads", rows > 0, "%d rows" % rows)
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            check("Esc closes the modal", page.locator("#overlay").is_hidden())

        print()
        print("=== favourites: folders ===")
        page.click('.tab[data-tab="favourites"]')
        page.wait_for_timeout(700)
        check("favourites panel opens", page.locator("#panel-favourites").is_visible())
        folders = page.locator("#fav-folders .favfolder").count()
        check("a default folder exists", folders >= 1, "%d folders" % folders)

        stamp = str(int(time.time()))
        page.fill("#fav-newfolder", "Тест " + stamp)
        page.press("#fav-newfolder", "Enter")
        page.wait_for_timeout(900)
        after = page.locator("#fav-folders .favfolder").count()
        check("new folder is created", after == folders + 1, "%d -> %d" % (folders, after))
        check("new folder becomes current",
              (page.locator("#fav-title").text_content() or "").strip() == "Тест " + stamp,
              page.locator("#fav-title").text_content())

        # add a card from the search modal into that folder
        page.click('.tab[data-tab="search"]')
        clear_meta(page)
        page.fill("#search-q", "Sol Ring")
        wait_results(page)
        page.locator("#search-results .card").first.click()
        page.wait_for_timeout(900)
        page.locator(".add-fav").first.click()
        page.wait_for_timeout(1000)
        page.keyboard.press("Escape")
        page.click('.tab[data-tab="favourites"]')
        page.wait_for_timeout(700)
        rows = page.locator("#fav-cards .favrow").count()
        check("card lands in the folder", rows == 1, "%d rows" % rows)
        name = page.locator("#fav-cards .favrow .nm").first.text_content()
        check("saved card keeps its name", "Sol Ring" in name, "got %r" % name)
        check("saved card shows artwork",
              page.locator("#fav-cards .favrow img").count() == 1)

        # quantity edit
        page.fill("#fav-cards .favrow input[data-qty]", "3")
        page.locator("#fav-cards .favrow input[data-qty]").dispatch_event("change")
        page.wait_for_timeout(900)
        check("quantity edit sticks",
              "3 шт." in (page.locator("#fav-summary").text_content() or ""),
              page.locator("#fav-summary").text_content())

        # push the folder into the hunt
        page.click("#fav-to-hunt")
        page.wait_for_timeout(900)
        wants = page.input_value("#hunt-wants")
        check("folder goes to the hunt", "Sol Ring" in wants, "hunt list %r" % wants[:60])

        # cleanup: remove the card, delete the folder
        page.click('.tab[data-tab="favourites"]')
        page.wait_for_timeout(500)
        page.locator("#fav-cards [data-remove]").first.click()
        page.wait_for_timeout(900)
        check("card can be removed", page.locator("#fav-cards .favrow").count() == 0)
        page.on("dialog", lambda d: d.accept())
        page.click("#fav-delete")
        try:
            # Wait for the folder count to actually drop back, rather than
            # guessing a duration -- the same trap as the search checks.
            page.wait_for_function(
                "(n) => document.querySelectorAll('#fav-folders .favfolder').length === n",
                arg=folders, timeout=15000)
            deleted = True
        except Exception:  # noqa: BLE001
            deleted = False
        check("folder can be deleted", deleted,
              "%d folders, expected %d" % (
                  page.locator("#fav-folders .favfolder").count(), folders))
        page.click('.tab[data-tab="search"]')



        print()
        print("=== hunt on topdeck (one card, live request) ===")
        page.click('.tab[data-tab="hunt"]')
        page.fill("#hunt-wants", "1 Snapcaster Mage")
        page.click("#hunt-btn")
        try:
            page.wait_for_function(
                "() => { const m = document.querySelector('#hunt-meta');"
                " return m && (m.textContent||'').indexOf('итог') >= 0; }",
                timeout=120000,
            )
            got_plan = True
        except Exception as exc:  # noqa: BLE001
            got_plan = False
            check("hunt completes", False, str(exc)[:90])
        if got_plan:
            check("hunt completes", True, (page.locator("#hunt-meta").text_content() or "")[:70])
            lots = page.locator("#hunt-plan .lot").count()
            check("plan has at least one seller lot", lots > 0, "%d lots" % lots)
            check("the seller's own line is shown",
                  page.locator("#hunt-plan .rawline").count() > 0)
            check("a purchase message was drafted",
                  "Здравствуйте" in (page.locator("#hunt-plan .msgbox textarea").first.input_value() or ""))

        print()
        print("=== offer rows in the plan are laid out sanely ===")
        boxes = page.evaluate("""() => {
            const offer = document.querySelector('#hunt-plan .offer');
            if (!offer) return null;
            const img = offer.querySelector('.thumb');
            const want = offer.querySelector('.want');
            if (!img || !want) return null;
            const a = img.getBoundingClientRect(), b = want.getBoundingClientRect();
            return { imgRight: a.right, textLeft: b.left };
        }""")
        if boxes is None:
            check("offer layout measured", False, "no offer row to measure")
        else:
            check("card name does not overlap the artwork",
                  boxes["textLeft"] >= boxes["imgRight"] - 1,
                  "image ends at %.0f, text starts at %.0f" % (boxes["imgRight"], boxes["textLeft"]))
        check("each offer says which printing is pictured",
              page.locator("#hunt-plan .printinfo").count() > 0)


        print()
        print("=== deck workbench: analyse, pick, file away ===")
        # The "missing" checks need a known collection. Save the real one,
        # install a fixture, and restore it at the end -- a test must not
        # depend on, or damage, the user's own data.
        saved_collection = page.evaluate(
            "async () => (await (await fetch('/api/collection')).json()).collection"
        ) or {}
        set_collection(page, "\n".join([
            "2 Lightning Bolt", "1 Sol Ring", "4 Brainstorm",
        ]))
        page.click('.tab[data-tab="deck"]')
        page.wait_for_timeout(300)
        page.click("#panel-deck details.help summary")   # open the paste box
        page.fill("#deck-text", "\n".join([
            "4 Lightning Bolt",
            "2 Sol Ring",
            "1 Tiamat",
            "4 Brainstorm",
            "1 Ragavan, Nimble Pilferer",
        ]))
        page.click("#deck-text-btn")
        page.wait_for_function(
            "() => document.querySelectorAll('#deck-view .deckrow').length > 0",
            timeout=30000)
        rows = page.locator("#deck-view .deckrow").count()
        check("deck rows render", rows == 5, "%d rows" % rows)
        check("workbench is shown", page.locator("#deck-workbench").is_visible())
        check("rows show what is missing",
              page.locator("#deck-view .have.need").count() > 0,
              "%d 'need' badges" % page.locator("#deck-view .have.need").count())
        check("rows show prices", page.locator("#deck-view .pr").count() == 5)
        meta = page.locator("#deck-meta").text_content() or ""
        check("summary states what to buy", "нет в коллекции" in meta, meta[:80])

        # filter down to what is missing
        page.select_option("#deck-filter", "missing")
        page.wait_for_timeout(500)
        filtered = page.locator("#deck-view .deckrow").count()
        check("filter 'only missing' narrows the list", 0 < filtered < 5,
              "%d rows" % filtered)
        page.select_option("#deck-filter", "all")
        page.wait_for_timeout(400)

        # sort by price
        page.select_option("#deck-sort", "price_desc")
        page.wait_for_timeout(500)
        first = page.locator("#deck-view .deckrow .nm b").first.text_content() or ""
        check("sorting by price puts the expensive card first",
              "Ragavan" in first, "got %r" % first)

        # quick select
        page.click('#deck-quickselect button[data-sel="missing"]')
        page.wait_for_timeout(500)
        selected = page.locator("#deck-view .deckrow.sel").count()
        check("quick select picks the missing cards", selected > 0, "%d selected" % selected)
        info = page.locator("#deck-selinfo").text_content() or ""
        check("selection bar counts and prices the picks",
              "выбрано" in info and "$" in info, info[:70])

        # file them into a brand-new list
        stamp2 = str(int(time.time()))
        page.fill("#deck-new-folder", "Колода " + stamp2)
        page.click("#deck-add-fav")
        page.wait_for_timeout(1500)
        page.click('.tab[data-tab="favourites"]')
        page.wait_for_timeout(800)
        title = (page.locator("#fav-title").text_content() or "").strip()
        check("cards land in the new list", title == "Колода " + stamp2, "got %r" % title)
        favrows = page.locator("#fav-cards .favrow").count()
        check("the new list holds the picked cards", favrows == selected,
              "%d rows vs %d picked" % (favrows, selected))
        summary = page.locator("#fav-summary").text_content() or ""
        check("list quantity is what you are SHORT, not the deck count",
              "5 шт." in summary, summary[:60])


        # shift-click takes the whole run between two clicks, in DISPLAY order
        page.click('.tab[data-tab="deck"]')
        page.wait_for_timeout(400)
        page.click('#deck-quickselect button[data-sel="none"]')
        page.wait_for_timeout(300)
        rows = page.locator("#deck-view .deckrow")
        rows.nth(0).click()
        page.wait_for_timeout(250)
        one = page.locator("#deck-view .deckrow.sel").count()
        rows.nth(3).click(modifiers=["Shift"])
        page.wait_for_timeout(350)
        four = page.locator("#deck-view .deckrow.sel").count()
        check("shift-click selects the range", one == 1 and four == 4,
              "%d then %d selected" % (one, four))

        # and straight to the hunt
        page.click('.tab[data-tab="deck"]')
        page.wait_for_timeout(400)
        page.click('#deck-quickselect button[data-sel="expensive"]')
        page.wait_for_timeout(500)
        page.click("#deck-sel-hunt")
        page.wait_for_timeout(800)
        wants = page.input_value("#hunt-wants")
        check("selected cards go to the hunt", "Ragavan" in wants, "hunt %r" % wants[:60])

        # cleanup: the folder we made and the collection fixture
        page.click('.tab[data-tab="favourites"]')
        page.wait_for_timeout(400)
        page.click("#fav-delete")
        page.wait_for_timeout(1200)
        restore_collection(page, saved_collection)
        page.click('.tab[data-tab="search"]')


        print()
        print("=== search by purpose (Scryfall Tagger) ===")
        page.click('.tab[data-tab="search"]')
        clear_meta(page)
        page.fill("#search-q", "")
        page.wait_for_timeout(600)
        if page.locator("#filters-panel").is_hidden():
            page.click("#filters-toggle")
        page.wait_for_timeout(500)
        presets = page.locator("#f-tag-presets button").count()
        check("Russian theme presets are offered", presets >= 15, "%d presets" % presets)

        clear_meta(page)
        page.click('#f-tag-presets button[data-tag="theft-creature"]')
        wait_results(page)
        composed = page.input_value("#search-q")
        check("a theme composes into the query", "otag:theft-creature" in composed, composed)
        found = page.locator("#search-results .card").count()
        check("theme search returns cards", found > 0, "%d tiles" % found)
        check("theme chip appears", page.locator("#f-tag-chips .chip").count() == 1)

        # parent tag must pull in its children
        clear_meta(page)
        page.click('#f-tag-chips .chip')
        wait_results(page)
        clear_meta(page)
        page.click('#f-tag-presets button[data-tag="control-changing-effects"]')
        wait_results(page)
        meta = page.locator("#search-meta").text_content() or ""
        check("a parent theme expands to its children", "из" in meta and "0" != meta.strip(),
              meta[:50])

        # free text over all 4524 tags
        page.fill("#f-tag-input", "sweeper")
        page.wait_for_timeout(900)
        taglist = page.locator("#f-tag-list .tagrow").count()
        check("tag search finds the whole family", taglist > 1, "%d tags" % taglist)

        clear_meta(page)
        page.click("#filters-reset")
        wait_results(page)
        check("reset clears the theme", page.locator("#f-tag-chips .chip").count() == 0)
        page.click("#filters-toggle")
        print()
        print("=== keyboard ===")
        page.keyboard.press("/")
        focused = page.evaluate("() => document.activeElement.id")
        check("'/' focuses the search box", focused == "search-q", "focus=%r" % focused)

        print()
        # Clean up after ourselves: this test creates favourite folders
        # ("Тест ...", "Колода ...") and used to leave them in the user's real
        # favourites. A test that litters the data it is checking is worse than
        # no test.
        print()
        print("=== cleanup ===")
        removed = page.evaluate("""async () => {
          const r = await fetch('/api/favourites').then(x => x.json());
          const junk = r.favourites.folders.filter(f =>
            /^(Тест|Колода|Откат) /.test(f.name));
          for (const f of junk) {
            await fetch('/api/favourites/folders/' + f.id, {method: 'DELETE'});
          }
          return junk.map(f => f.name);
        }""")
        check("test folders removed from favourites", True,
              "убрано: %s" % (removed or "нечего"))
        left = page.evaluate("""async () => {
          const r = await fetch('/api/favourites').then(x => x.json());
          return r.favourites.folders.filter(f =>
            /^(Тест|Колода|Откат) /.test(f.name)).length;
        }""")
        check("no test folders left behind", left == 0, "%d осталось" % left)

        page.screenshot(path=SHOT, full_page=False)
        print("screenshot -> " + SHOT)
        if errors:
            print()
            print("=== console errors ===")
            for e in errors[:10]:
                print("   " + e)
        browser.close()

    print()
    if FAIL:
        print("FAILED: %d check(s): %s" % (len(FAIL), FAIL))
        sys.exit(1)
    print("ALL UI CHECKS PASSED")


if __name__ == "__main__":
    main()
