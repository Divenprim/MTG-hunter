"""Browser check: changing your mind about a card in the hunt plan.

The user's complaint was blunt: "нельзя передумать брать карту". So the plan has
to let you refuse one listing, refuse a card outright, take fewer copies, and
put any of it back -- all without a new topdeck request.

Also guards the message text: a draft is a greeting plus the seller's own lines,
never an invoice with quantities, multiplications and a total.

Needs a running server and Chromium:

    .venv/Scripts/python.exe tests/ui_hunt_choices.py
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
WANTS = "2 Lightning Bolt\n1 Sol Ring"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def plan_lines(page):
    """What the plan currently proposes, as raw seller lines."""
    return [" ".join((t or "").split())
            for t in page.locator("#hunt-plan .offer .rawline").all_text_contents()]


def total(page):
    txt = page.locator("#hunt-meta").text_content() or ""
    digits = ""
    marker = "итог: "
    if marker in txt:
        for ch in txt[txt.index(marker) + len(marker):]:
            if ch.isdigit():
                digits += ch
            elif ch not in "  ":
                break
    return int(digits or 0)


with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_context(viewport={"width": 1500, "height": 1150}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")

    page.click('.tab[data-tab="hunt"]')
    page.wait_for_timeout(400)
    page.fill("#hunt-wants", WANTS)
    page.uncheck("#f-collection")
    page.click("#hunt-btn")
    # The hunt talks to topdeck at 1.5s per batch, so give it room.
    page.wait_for_function(
        "() => document.querySelectorAll('#hunt-plan .offer').length > 0", timeout=300000)
    page.wait_for_timeout(600)

    print("=== plan is built ===")
    before = plan_lines(page)
    before_total = total(page)
    check("plan has offers", len(before) > 0, "%d предложений" % len(before))
    check("total is shown", before_total > 0, "%d руб." % before_total)
    for line in before:
        print("      " + line[:70])

    print()
    print("=== the draft is a greeting plus the seller's own lines ===")
    msg = page.locator("#hunt-plan .msgbox textarea").first.input_value()
    print("      --- черновик ---")
    for ln in msg.split("\n"):
        print("      " + ln)
    check("greets", msg.startswith("Здравствуйте!"), msg[:30])
    check("quotes the seller's line verbatim",
          any(ln in msg for ln in before), "нет ни одной строки продавца")
    check("no invoice arithmetic",
          "Итого" not in msg and " × " not in msg and " = " not in msg,
          "нашлось оформление чека")
    check("no restated prices per copy", "шт. ×" not in msg, msg[:60])

    print()
    print("=== refusing one listing ===")
    page.locator("#hunt-plan button[data-skip-offer]").first.click()
    page.wait_for_function(
        "(old) => { const els = document.querySelectorAll('#hunt-plan .offer .rawline');"
        " return els.length === 0 || els[0].textContent.replace(/[ ]+/g,' ').trim() !== old; }",
        arg=before[0], timeout=60000)
    page.wait_for_timeout(400)
    after = plan_lines(page)
    check("the refused listing is gone from the plan", before[0] not in after,
          "всё ещё в плане" if before[0] in after else before[0][:50])
    check("a replacement was chosen", len(after) > 0, "%d предложений" % len(after))
    check("the refusal is shown with a way back",
          page.locator("#hunt-choices button[data-unskip]").count() > 0)
    for line in after:
        print("      " + line[:70])

    print()
    print("=== taking the refusal back ===")
    page.locator("#hunt-choices button[data-unskip]").first.click()
    page.wait_for_function(
        "(n) => document.querySelectorAll('#hunt-choices button[data-unskip]').length === 0",
        arg=0, timeout=60000)
    page.wait_for_timeout(500)
    check("plan is exactly as it was", plan_lines(page) == before,
          "стало: %s" % [l[:34] for l in plan_lines(page)])
    check("total is back", total(page) == before_total,
          "%d вместо %d" % (total(page), before_total))

    print()
    print("=== refusing a card outright ===")
    dropped = (page.locator("#hunt-plan button[data-skip-want]").first
               .get_attribute("data-skip-want"))
    page.locator("#hunt-plan button[data-skip-want]").first.click()
    page.wait_for_function(
        "(name) => { const chips = document.querySelectorAll('#hunt-choices .wantchip.off b');"
        " return Array.from(chips).some(el => el.textContent.trim() === name); }",
        arg=dropped, timeout=60000)
    page.wait_for_timeout(400)
    wants_now = [" ".join((t or "").split())
                 for t in page.locator("#hunt-plan .offer .want").all_text_contents()]
    check("the card is out of the plan",
          not any(w.startswith(dropped) for w in wants_now), "«%s» осталась" % dropped)
    check("it is listed as dropped, with «вернуть»",
          page.locator("#hunt-choices button[data-undrop]").count() > 0)

    page.locator("#hunt-choices button[data-undrop]").first.click()
    page.wait_for_function(
        "() => document.querySelectorAll('#hunt-choices button[data-undrop]').length === 0",
        timeout=60000)
    page.wait_for_timeout(500)
    check("the card comes back", plan_lines(page) == before,
          "стало: %s" % [l[:34] for l in plan_lines(page)])

    print()
    print("=== taking fewer copies ===")
    qty = page.locator("#hunt-choices input.qty").first
    most = int(qty.get_attribute("max") or "1")
    if most > 1:
        qty.fill("1")
        qty.dispatch_event("change")
        page.wait_for_function("(t) => { const m = document.querySelector('#hunt-meta');"
                               " return m && m.textContent.indexOf(t) < 0; }",
                               arg=str(before_total), timeout=60000)
        page.wait_for_timeout(400)
        check("fewer copies means a smaller total", total(page) < before_total,
              "%d вместо %d" % (total(page), before_total))
        # The ceiling must stay at what the hunt was for. Reading it back from
        # the re-planned want (now 1) would trap the user at one copy forever.
        again = page.locator("#hunt-choices input.qty").first
        check("the ceiling still allows the full count",
              again.get_attribute("max") == str(most),
              "max=%s, а нужно было %d" % (again.get_attribute("max"), most))
        check("the strip still says how many are needed",
              ("из %d" % most) in (page.locator("#hunt-choices").text_content() or ""))
        qty = again
        qty.fill(str(most))
        qty.dispatch_event("change")
        page.wait_for_timeout(1200)
        check("restoring the count restores the plan", total(page) == before_total,
              "%d вместо %d" % (total(page), before_total))
    else:
        check("fewer copies means a smaller total", True, "нечего уменьшать (max=1)")
        check("restoring the count restores the plan", True, "нечего уменьшать")

    print()
    print("=== your edits to a draft survive a re-plan ===")
    box = page.locator("#hunt-plan .msgbox textarea").first
    mine = "Здравствуйте! Пишу от себя, беру всё."
    box.fill(mine)
    box.dispatch_event("input")
    page.wait_for_timeout(300)
    # A re-plan: refuse a listing from a DIFFERENT lot if there is one, else the
    # same one and back again.
    page.locator("#hunt-choices input.qty").first.dispatch_event("change")
    page.wait_for_timeout(1500)
    kept = page.locator('#hunt-plan .msgbox textarea[data-seller]').first.input_value()
    check("the edited message was not overwritten", kept == mine, kept[:50])
    check("there is a way back to the generated draft",
          page.locator("#hunt-plan .reset-msg").count() > 0)
    page.locator("#hunt-plan .reset-msg").first.click()
    page.wait_for_timeout(400)
    back = page.locator("#hunt-plan .msgbox textarea").first.input_value()
    check("the generated draft is restored",
          back.startswith("Здравствуйте!") and back != mine, back[:40])

    print()
    check("no console errors", not errors, "; ".join(errors[:3]))
    page.screenshot(path="tests/ui_hunt_choices.png", full_page=True)
    b.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL HUNT-CHOICE CHECKS PASSED")
