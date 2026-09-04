"""Browser check: a shop lot becomes an order, a person stays a conversation.

The point of the split: you write to a private seller, but at a shop you place
an order on its own site. So a shop lot shows the list to paste and a direct
link to each card's page -- and no private-message draft, which would be
nonsense.

It also pins down the promise the panel makes in words: the cart is yours to
fill. The program prepares the order and stops.

Depends on live topdeck listings, so if no shop happens to be selling the test
card right now the shop half is skipped rather than failed.

Needs a running server and Chromium:

    .venv/Scripts/python.exe tests/ui_shop_order.py
"""

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8765"
# Shops stock these reliably, and Burgeoning has been seen at spellmarket.
WANTS = "1 Burgeoning\n1 Sol Ring"
FAIL = []


def check(label, ok, detail=""):
    print(("  PASS  " if ok else "  FAIL  ") + label + (" -- " + detail if detail else ""))
    if not ok:
        FAIL.append(label)


with sync_playwright() as pw:
    b = pw.chromium.launch()
    page = b.new_context(viewport={"width": 1450, "height": 950}).new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    page.goto(BASE, wait_until="networkidle")

    print("=== which shops we have verified links for ===")
    known = page.evaluate(
        "async () => (await (await fetch('/api/shops')).json()).shops")
    for shop in known:
        print("      %-22s %-20s поиск: %s" % (
            shop["domain"], shop["name"], "есть" if shop["search"] else "нет"))
    check("реестр магазинов не пуст", len(known) >= 3, "%d магазинов" % len(known))
    check("у каждого записан домен и имя",
          all(s.get("domain") and s.get("name") for s in known))

    print()
    print("=== a hunt with shops allowed ===")
    page.click('.tab[data-tab="hunt"]')
    page.wait_for_timeout(400)
    page.fill("#hunt-wants", WANTS)
    page.uncheck("#f-collection")
    page.check("#f-shops")
    page.check("#f-users")
    page.select_option("#f-strategy", "price")
    page.click("#hunt-btn")
    page.wait_for_function(
        "() => document.querySelectorAll('#hunt-plan .lot').length > 0", timeout=300000)
    page.wait_for_timeout(800)

    lots = page.evaluate("""() => [...document.querySelectorAll('#hunt-plan .lot')].map(l => ({
      seller: ((l.querySelector('.lot-seller') || {}).textContent || '').trim(),
      shop: !!l.querySelector('.badge.shop'),
      order: !!l.querySelector('.orderbox'),
      msgHidden: !!(l.querySelector('.msgbox') || {}).hidden,
    }))""")
    for l in lots:
        print("      %-22s магазин=%-5s заказ=%-5s ЛС скрыто=%s"
              % (l["seller"][:22], l["shop"], l["order"], l["msgHidden"]))

    people = [l for l in lots if not l["shop"]]
    if people:
        check("частному продавцу — черновик письма, не заказ",
              not any(l["order"] for l in people) and not any(l["msgHidden"] for l in people))

    stores = [l for l in lots if l["shop"]]
    if not stores:
        print("      (магазинов в плане нет — вторая половина проверки пропущена)")
        check("план собрался", bool(lots), "лотов нет")
    else:
        check("у магазина есть блок заказа", all(l["order"] for l in stores))
        check("и нет черновика ЛС", all(l["msgHidden"] for l in stores))

        box = page.locator(".orderbox").first
        text = " ".join((box.text_content() or "").split())
        print("      " + text[:130])
        check("названо, в каком магазине заказ", "Заказ в магазине" in text, text[:40])
        check("сказано, что корзину собираете вы",
              "Корзину собираете вы" in text,
              "нет предупреждения о том, кто оформляет заказ")

        listing = box.locator("textarea.orderlist").input_value()
        print("      список: " + " / ".join(listing.splitlines()))
        check("список в формате «количество имя»",
              all(l.split()[0].isdigit() for l in listing.splitlines() if l.strip()),
              listing[:40])

        hrefs = page.evaluate("""() => [...document.querySelectorAll('.orderbox .orderlinks a')]
            .map(a => a.href)""")
        check("на каждую карту есть ссылка", len(hrefs) > 0, "%d ссылок" % len(hrefs))
        for h in hrefs[:3]:
            print("      ссылка: " + h[:96])
        domains = [s["domain"] for s in known]
        check("ссылки ведут на сам магазин",
              all(any(d in h for d in domains) for h in hrefs), str(hrefs[:1]))

        # Copying is the whole interaction, so it has to actually copy.
        page.context.grant_permissions(["clipboard-read", "clipboard-write"])
        box.locator("button.copy-order").click()
        page.wait_for_timeout(500)
        pasted = page.evaluate("async () => await navigator.clipboard.readText()")
        check("кнопка копирует именно список", pasted.strip() == listing.strip(),
              pasted[:40])

        if box.locator("button.copy-links").count():
            box.locator("button.copy-links").click()
            page.wait_for_timeout(500)
            copied = page.evaluate("async () => await navigator.clipboard.readText()")
            check("вторая кнопка копирует ссылки",
                  copied.strip().splitlines() == hrefs, copied[:60])

    print()
    check("ошибок в консоли нет", not errors, "; ".join(errors[:3]))
    page.screenshot(path="tests/ui_shop_order.png", full_page=True)
    b.close()

print()
print("FAILED: %s" % FAIL if FAIL else "ALL SHOP-ORDER CHECKS PASSED")
