"""Browser check: the history of received orders.

Nothing here receives a real order: receiving moves cards into the user's own
collection, and a test must not do that. So the renderer is fed a state of its
own and the DOM is checked -- which is exactly the part that can break, since
the numbers themselves are covered by tests/test_order_history.py.

Needs a running server and Chromium:

    .venv/Scripts/python.exe tests/ui_order_history.py
"""

import os
from playwright.sync_api import sync_playwright

# Куда стучаться. По умолчанию -- обычный запуск; MTGH_UI_BASE нужна,
# когда на этом порту уже работает другая копия программы (скажем,
# запущенная по https для планшета).
BASE = os.environ.get("MTGH_UI_BASE", "http://127.0.0.1:8765")
FAIL = []

# Two received orders and one still on its way, as the API would report them.
STATE = {
    "orders": [{
        "id": "pend1", "seller_name": "продавец-в-пути", "seller_kind": "user",
        "total": 300, "created": "2026-09-07 12:00:00", "status": "pending",
        "items": [{"name": "Sol Ring", "name_norm": "sol ring",
                   "quantity": 1, "unit_price": 300, "subtotal": 300}],
    }],
    "ordered": {"sol ring": 1},
    "history": [
        {
            "id": "got1", "seller_name": "продавец-а", "seller_kind": "user",
            "total": 1000, "created": "2026-08-30 09:00:00",
            "status": "received", "received": "2026-09-05 18:30:00", "cards": 5,
            "items": [
                {"name": "Lightning Bolt", "quantity": 4, "unit_price": 150,
                 "subtotal": 600},
                {"name": "Sol Ring", "quantity": 1, "unit_price": 400,
                 "subtotal": 400},
            ],
        },
        {
            "id": "got2", "seller_name": "магазин-б", "seller_kind": "shop",
            "total": 520, "created": "2026-07-01 10:00:00",
            "status": "received", "received": None, "cards": 3,
            "items": [{"name": "Cultivate", "quantity": 3, "unit_price": 60,
                       "subtotal": 180}],
        },
    ],
    "spent": {"orders": 2, "total": 1520, "sellers": 2, "cards": 8,
              "first": "2026-07-01 10:00:00", "last": "2026-09-05 18:30:00"},
}


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    page = browser.new_context(viewport={"width": 1500, "height": 1150}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")

    page.click('.tab[data-tab="hunt"]')
    page.wait_for_timeout(400)

    print("=== history beside the orders still on their way ===")
    page.evaluate("(state) => applyOrderState(state)", STATE)
    page.wait_for_timeout(300)
    check("pending orders are still shown",
          page.locator("#hunt-orders .pending-order").count() == 1)
    check("the history is a section of its own",
          page.locator("#hunt-orders .order-history").count() == 1)
    check("each received order is a row",
          page.locator("#hunt-orders .got-order").count() == 2,
          "%d строк" % page.locator("#hunt-orders .got-order").count())

    summary = " ".join(
        (page.locator("#hunt-orders .order-history > summary").text_content() or "").split())
    check("the summary counts the orders and the money",
          "2 заказа" in summary and "1 520" in summary, summary)

    page.locator("#hunt-orders .order-history > summary").click()
    page.wait_for_timeout(200)
    text = " ".join((page.locator("#hunt-orders .order-history").text_content() or "").split())
    check("cards and sellers are totalled",
          "карт: 8" in text and "продавцов: 2" in text, text[:130])
    check("the span of dates is shown",
          "с 01.07.2026 по 05.09.2026" in text, text[:200])
    check("it says these are prices actually paid",
          "действительно заплатили" in text, text[:200])

    print()
    print("=== what a row says ===")
    first = " ".join((page.locator("#hunt-orders .got-order").first.text_content() or "").split())
    check("the seller and the total", "продавец-а" in first and "1 000" in first, first[:90])
    check("the date received, as a date", "получено 05.09.2026" in first, first[:120])
    check("and the date it was ordered", "заказан 30.08.2026" in first, first[:150])
    check("the price paid per card", "4× Lightning Bolt по 150" in first, first[-90:])

    second = " ".join((page.locator("#hunt-orders .got-order").nth(1).text_content() or "").split())
    check("an order received before dates were recorded says so",
          "дата не записана" in second, second[:120])

    print()
    print("=== history alone, with nothing on its way ===")
    page.evaluate("""(state) => applyOrderState(
        {orders: [], ordered: {}, history: state.history, spent: state.spent})""",
        STATE)
    page.wait_for_timeout(250)
    check("the history does not disappear with the pending list",
          page.locator("#hunt-orders .order-history").count() == 1)
    check("and no empty pending section is left",
          page.locator("#hunt-orders .pending-orders").count() == 0)

    print()
    print("=== a card nobody bought stays quiet ===")
    page.evaluate("() => loadOrders()")
    page.wait_for_timeout(500)
    page.click('.tab[data-tab="search"]')
    page.fill("#search-q", "Lightning Bolt")
    page.press("#search-q", "Enter")
    page.wait_for_function(
        "() => document.querySelectorAll('#search-results .card').length > 0", timeout=30000)
    page.locator("#search-results .card").first.click()
    page.wait_for_function(
        "() => !document.querySelector('#overlay').hidden", timeout=20000)
    page.wait_for_timeout(1200)
    check("the purchase block exists in the card window",
          page.locator("#modal-bought").count() == 1)
    bought = (page.locator("#modal-bought").text_content() or "").strip()
    check("and shows nothing when the card was never bought", bought == "",
          bought[:80])
    page.locator("#modal-close").click()

    print()
    check("no console errors", not errors, "; ".join(errors[:3]))
    page.screenshot(path="tests/ui_order_history.png")
    browser.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL ORDER-HISTORY CHECKS PASSED")
