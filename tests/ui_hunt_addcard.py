"""Browser check: adding one more card to an order that already exists.

"вот эту ещё докинуть" -- and the useful part is the ORDER of the answer. A card
at 775 from someone already in the plan costs no extra parcel and no second
conversation; 270 from a stranger does. So the sellers already in the order are
shown first, everyone else after, and the card joins the order only when a
listing is chosen.

What this pins down:
  * nothing is added, and the plan does not move, until you pick;
  * the two groups appear in that order, with the reason spelled out;
  * the chosen listing is honoured and marked as your choice;
  * the wants box and the "Берём" strip keep in step with the addition.

Needs a running server and Chromium:

    .venv/Scripts/python.exe tests/ui_hunt_addcard.py
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
WANTS = "1 Sol Ring\n1 Lightning Bolt"
EXTRA = "Dark Ritual"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


def plan_wants(page):
    return page.evaluate(
        """() => [...document.querySelectorAll('#hunt-plan .offer .want')]
             .map(e => e.textContent.trim().split(' —')[0])""")


with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_context(viewport={"width": 1500, "height": 1000}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")

    page.click('.tab[data-tab="hunt"]')
    page.wait_for_timeout(400)
    page.fill("#hunt-wants", WANTS)
    page.uncheck("#f-collection")
    page.click("#hunt-btn")
    page.wait_for_function(
        "() => document.querySelectorAll('#hunt-plan .lot').length > 0", timeout=300000)
    page.wait_for_timeout(800)

    print("=== the order we start from ===")
    meta = " ".join((page.locator("#hunt-meta").text_content() or "").split())
    print("      " + meta[-70:])
    check("строка «докинуть карту» появилась вместе с планом",
          not page.evaluate("() => document.querySelector('#hunt-addbox').hidden"))
    started = plan_wants(page)
    print("      в плане: " + str(started))

    print()
    print("=== looking the card up ===")
    page.fill("#hunt-add", EXTRA)
    page.wait_for_function(
        "() => document.querySelectorAll('#hunt-suggest .setrow').length > 0",
        timeout=30000)
    check("подсказки по имени работают",
          page.locator("#hunt-suggest .setrow").count() > 0)
    page.locator("#hunt-suggest .setrow").first.click()
    page.wait_for_function(
        "() => document.querySelectorAll('#hunt-lookup .lookrow').length > 0",
        timeout=300000)
    page.wait_for_timeout(600)

    groups = page.evaluate(
        """() => [...document.querySelectorAll('#hunt-lookup .lookgroup h5')]
             .map(e => e.textContent.replace(/\\s+/g, ' ').trim())""")
    for g in groups:
        print("      " + g[:80])
    check("первым идёт раздел «у кого уже покупаем»",
          bool(groups) and "уже покупаем" in groups[0], str(groups[:1]))
    check("и сказано, что там нет второй пересылки",
          bool(groups) and "пересылк" in groups[0], str(groups[:1]))
    if len(groups) > 1:
        check("остальные идут после, с оговоркой про ещё одну посылку",
              "остальных" in groups[1] and "посылка" in groups[1], groups[1][:60])

    rows = page.evaluate(
        """() => [...document.querySelectorAll('#hunt-lookup .lookgroup')].map(g => ({
             head: g.querySelector('h5').textContent.replace(/\\s+/g, ' ').trim().slice(0, 34),
             rows: [...g.querySelectorAll('.lookrow')].slice(0, 2)
               .map(r => r.textContent.replace(/\\s+/g, ' ').trim().slice(0, 70)),
           }))""")
    for g in rows:
        print("      " + g["head"])
        for x in g["rows"]:
            print("         " + x)
    check("в строке видно цену, продавца и его объявление",
          bool(rows) and bool(rows[0]["rows"]) and "₽" in rows[0]["rows"][0],
          str(rows[:1]))

    # The whole point: looking is not buying.
    check("до подтверждения карта в план не попала",
          EXTRA not in plan_wants(page), str(plan_wants(page)))
    check("и в список охоты тоже",
          EXTRA not in page.input_value("#hunt-wants"),
          page.input_value("#hunt-wants").replace(chr(10), " / "))

    print()
    print("=== declining leaves everything as it was ===")
    page.click("#hunt-look-cancel")
    page.wait_for_timeout(400)
    check("«не надо» закрывает панель",
          (page.locator("#hunt-lookup").text_content() or "").strip() == "")
    check("план не тронут", plan_wants(page) == started, str(plan_wants(page)))

    print()
    print("=== taking it from a seller already in the order ===")
    page.fill("#hunt-add", EXTRA)
    page.wait_for_function(
        "() => document.querySelectorAll('#hunt-suggest .setrow').length > 0",
        timeout=30000)
    page.locator("#hunt-suggest .setrow").first.click()
    page.wait_for_function(
        "() => document.querySelectorAll('#hunt-lookup .lookrow').length > 0",
        timeout=300000)
    page.wait_for_timeout(500)

    chosen = " ".join(
        (page.locator("#hunt-lookup .lookgroup").first
         .locator(".lookrow").first.text_content() or "").split())[:60]
    print("      беру: " + chosen)
    (page.locator("#hunt-lookup .lookgroup").first
     .locator(".lookrow").first.locator("button").click())
    page.wait_for_function(
        """(name) => [...document.querySelectorAll('#hunt-plan .offer .want')]
             .some(e => e.textContent.indexOf(name) >= 0)""",
        arg=EXTRA, timeout=180000)
    page.wait_for_timeout(1000)

    lots = page.evaluate(
        """() => [...document.querySelectorAll('#hunt-plan .lot')].map(l => ({
             seller: (l.querySelector('.lot-seller') || {}).textContent.trim(),
             items: [...l.querySelectorAll('.offer .want')]
               .map(e => e.textContent.trim().split(' —')[0]),
           }))""")
    print("      план стал: " + str(lots))
    check("карта в плане", any(EXTRA in l["items"] for l in lots), str(lots))
    check("и у продавца, который уже был в заказе, без новой посылки",
          len(lots) == 1, str([l["seller"] for l in lots]))
    check("выбор помечен как ваш",
          page.locator("#hunt-plan button[data-unpin]").count() > 0)
    check("карта дописана в список охоты",
          EXTRA in page.input_value("#hunt-wants"),
          page.input_value("#hunt-wants").replace(chr(10), " / "))
    strip = page.evaluate(
        """() => [...document.querySelectorAll('#hunt-choices .wantchip b')]
             .map(e => e.textContent.trim())""")
    check("и появилась в строке «Берём» со своим количеством",
          EXTRA in strip, str(strip))
    check("панель поиска закрылась",
          (page.locator("#hunt-lookup").text_content() or "").strip() == "")

    print()
    print("=== cleanup ===")
    wants = page.input_value("#hunt-wants")
    kept = chr(10).join(l for l in wants.splitlines() if EXTRA.lower() not in l.lower())
    page.fill("#hunt-wants", kept)
    page.dispatch_event("#hunt-wants", "input")
    page.wait_for_timeout(300)
    check("список охоты возвращён как был",
          EXTRA not in page.input_value("#hunt-wants"))

    print()
    check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
    page.screenshot(path="tests/ui_hunt_addcard.png", full_page=True)
    b.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL ADD-CARD CHECKS PASSED")
