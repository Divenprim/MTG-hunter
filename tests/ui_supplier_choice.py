"""Browser check: choosing who to buy each card from.

The user's verdict on the previous version was "щас сделано просто тупо.
Буквально не работает", with three specific things behind it:

  * the plan bought a card from a shop at 500 while a seller already in it had
    the same card at 400 (fixed in the algorithm, see tests/test_plan.py);
  * there was no way to choose a supplier by hand;
  * and editing lost your place, because every change re-rendered the plan.

So: each card shows who it is being bought from and the listings that beat it,
the full list opens on request (Sol Ring has 185 offers -- a dropdown of those
was the first attempt and it was worse than nothing), one seller can be given
the whole order, and a change keeps the page where it was.

Needs a running server and Chromium:

    .venv/Scripts/python.exe tests/ui_supplier_choice.py
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
WANTS = "1 Dark Ritual\n1 Sol Ring\n1 Lightning Bolt\n1 Counterspell"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_context(viewport={"width": 1500, "height": 900}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")

    page.click('.tab[data-tab="hunt"]')
    page.wait_for_timeout(400)
    page.fill("#hunt-wants", WANTS)
    page.uncheck("#f-collection")
    page.select_option("#f-strategy", "sellers")
    page.click("#hunt-btn")
    page.wait_for_function(
        "() => document.querySelectorAll('#hunt-plan .offer').length > 2", timeout=300000)
    page.wait_for_timeout(900)

    print("=== what the plan says about each card ===")
    meta = " ".join((page.locator("#hunt-meta").text_content() or "").split())
    print("      " + meta[:150])
    first = page.locator("#hunt-plan .offer").first
    picker = " ".join((first.locator(".picker").text_content() or "").split())
    print("      " + picker[:140])
    check("видно, у кого берётся карта",
          "берём у" in picker or "выбрано вами" in picker, picker[:50])
    check("нет выпадающего списка на сотню строк",
          page.locator("#hunt-plan select[data-pin]").count() == 0)
    check("есть кнопка полного списка предложений",
          first.locator("[data-alts]").count() == 1)

    print()
    print("=== the full list opens on request ===")
    rows = page.locator("#hunt-plan .offer")
    target = rows.nth(rows.count() - 1)
    want = target.locator("[data-alts]").get_attribute("data-alts")
    print("      правим: " + str(want))
    target.locator("[data-alts]").scroll_into_view_if_needed()
    page.wait_for_timeout(300)
    target.locator("[data-alts]").click()
    page.wait_for_timeout(700)
    offered = target.locator(".altrow").count()
    check("список открылся", offered > 3, "%d предложений" % offered)
    line = " ".join((target.locator(".altrow").first.text_content() or "").split())
    print("      дешёвое: " + line[:100])
    check("в строке цена, продавец и его объявление", "₽" in line, line[:40])
    check("длинный список скроллится, а не растягивает страницу", page.evaluate("""() => {
        const box = document.querySelector('#hunt-plan .altrows');
        return !!box && box.clientHeight <= 280; }"""))

    print()
    print("=== choosing by hand, and keeping your place ===")
    before = page.evaluate("() => Math.round(window.scrollY)")
    pick = page.evaluate("""(w) => {
      const box = document.querySelector('.alts[data-altlist="' + w + '"]');
      const row = [...box.querySelectorAll('.altrow')].find(x => !x.classList.contains('on'));
      return row ? {key: row.dataset.key,
                    text: row.textContent.replace(/[ ]+/g, ' ').trim().slice(0, 70)} : null;
    }""", want)
    if not pick:
        check("есть другой поставщик для этой карты", False, "вариантов меньше двух")
    else:
        print("      выбираем: " + pick["text"])
        page.locator('.altrow[data-key="%s"]' % pick["key"]).first.click()
        page.wait_for_function(
            "() => document.querySelectorAll('#hunt-plan button[data-unpin]').length > 0",
            timeout=60000)
        page.wait_for_timeout(1200)

        after = page.evaluate("() => Math.round(window.scrollY)")
        check("страница осталась на месте", abs(after - before) < 120,
              "%d -> %d" % (before, after))
        check("открытый список не закрылся", page.evaluate("""(w) => {
            const box = document.querySelector('.alts[data-altlist="' + w + '"]');
            return !!box && !box.hidden && box.querySelectorAll('.altrow').length > 0; }""", want))
        marked = page.evaluate("""(w) => {
            const box = document.querySelector('.alts[data-altlist="' + w + '"]');
            const on = box.querySelector('.altrow.on');
            return on ? on.textContent.replace(/[ ]+/g, ' ').trim().slice(0, 60) : null; }""", want)
        check("выбранное отмечено в списке", marked is not None, str(marked))
        check("и подписано как ваш выбор",
              "выбрано вами" in " ".join(
                  (page.locator('.picker:has(button[data-unpin])').first
                   .text_content() or "").split()))

        page.locator("#hunt-plan button[data-unpin]").first.click()
        page.wait_for_function(
            "() => document.querySelectorAll('#hunt-plan button[data-unpin]').length === 0",
            timeout=60000)
        page.wait_for_timeout(600)
        check("сброс возвращает решение программе", True, "кнопка исчезла")

    print()
    print("=== buying it all from one seller ===")
    if page.locator("#hunt-prefer").count() == 0:
        check("есть выбор «купить всё у одного»", False, "селектор не нарисован")
    else:
        options = page.evaluate(
            """() => [...document.querySelectorAll('#hunt-prefer option')]
                 .map(o => ({v: o.value, t: o.textContent.trim()}))""")
        print("      могут закрыть заказ: " + str([o["t"] for o in options[1:4]]))
        check("сказано, сколько карт закрывает каждый",
              any(" из " in o["t"] for o in options[1:]), str(options[1:2]))
        if len(options) > 1:
            page.select_option("#hunt-prefer", options[1]["v"])
            page.wait_for_timeout(2500)
            sellers = page.evaluate(
                """() => [...document.querySelectorAll('#hunt-plan .lot .lot-seller')]
                     .map(e => e.textContent.trim())""")
            print("      план стал: " + str(sellers))
            wanted_name = options[1]["t"].split(" —")[0].replace(" (магазин)", "")
            check("выбранный продавец в плане",
                  any(wanted_name.startswith(s[:8]) or s.startswith(wanted_name[:8])
                      for s in sellers),
                  "%s против %s" % (wanted_name, sellers))
            page.select_option("#hunt-prefer", "")
            page.wait_for_timeout(2500)
            check("возврат к «как выгоднее» работает",
                  page.locator("#hunt-plan .lot").count() > 0)

    print()
    check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
    page.screenshot(path="tests/ui_supplier_choice.png")
    b.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL SUPPLIER-CHOICE CHECKS PASSED")
