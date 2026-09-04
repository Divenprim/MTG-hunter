"""Tests for preparing an order at a shop.

A shop lot is not a conversation: it becomes an order on the shop's own site.
The program prepares the list and the links and stops there -- it does not fill
anyone's cart, which is the same line it does not cross when it refuses to send
private messages.

What is guarded here:

  * shops are recognised by domain, and an unknown shop still works (list and
    direct links) rather than disappearing;
  * a URL pattern is only ever used where it was verified against the live
    site -- a guessed one that silently searches for nothing is worse than no
    link, so a shop without a verified pattern must report none;
  * private sellers never get an order block.
"""

import os
import sys
import unittest
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import shops  # noqa: E402


def item(name, quantity=1, price=100, url="", line=""):
    return {
        "want": name,
        "quantity": quantity,
        "unit_price": price,
        "subtotal": quantity * price,
        "offer": {"line": line or ("%d %s %d" % (quantity, name, price)), "url": url},
    }


def lot(seller, kind="shop", items=None, total=100, url=""):
    items = items if items is not None else [item("Sol Ring")]
    return {
        "seller_name": seller,
        "seller_kind": kind,
        "seller_url": url,
        "total": total,
        "items": items,
    }


class TestDomain(unittest.TestCase):
    def test_a_bare_domain(self):
        self.assertEqual(shops.domain_of("spellmarket.ru"), "spellmarket.ru")

    def test_a_url(self):
        self.assertEqual(
            shops.domain_of("https://www.mtgsale.ru/home/search-results?Name=x"),
            "mtgsale.ru")

    def test_a_nickname_is_not_a_domain(self):
        self.assertIsNone(shops.domain_of("Wonderslav"))

    def test_nothing(self):
        self.assertIsNone(shops.domain_of(""))


class TestShopLookup(unittest.TestCase):
    def test_a_known_shop_brings_its_verified_search(self):
        shop = shops.shop_for("spellmarket.ru")
        self.assertTrue(shop["known"])
        self.assertEqual(shop["name"], "SpellMarket")
        self.assertIn("route=product/search", shop["search"])

    def test_a_shop_whose_search_was_not_verified_offers_none(self):
        """Angry Bottle Gnome searches by POST; there is no link to build."""
        shop = shops.shop_for("angrybottlegnome.ru")
        self.assertTrue(shop["known"])
        self.assertIsNone(shop["search"])
        self.assertIn("формой", shop["note"])

    def test_an_unknown_shop_still_works(self):
        shop = shops.shop_for("cards-of-somewhere.ru")
        self.assertFalse(shop["known"])
        self.assertIsNone(shop["search"])
        self.assertEqual(shop["home"], "https://cards-of-somewhere.ru/")
        self.assertIn("незнаком", shop["note"])

    def test_every_registered_pattern_takes_the_card_name(self):
        for domain, cfg in shops.SHOPS.items():
            if cfg["search"]:
                self.assertIn("{q}", cfg["search"], domain)

    def test_no_registered_shop_lacks_a_name_or_home(self):
        for domain, cfg in shops.SHOPS.items():
            self.assertTrue(cfg.get("name"), domain)
            self.assertTrue(cfg.get("home"), domain)


class TestOrderForLot(unittest.TestCase):
    def setUp(self):
        self.lot = lot("spellmarket.ru", items=[
            item("Burgeoning", 1, 2500,
                 url="https://spellmarket.ru/index.php?route=product/product&product_id=34189",
                 line="<b>Burgeoning</b> (Special Guests) 2500"),
            item("Sol Ring", 2, 80),
        ], total=2660)
        self.order = shops.order_for_lot(self.lot)

    def test_the_list_is_quantity_then_name(self):
        self.assertEqual(self.order["list_text"], "1 Burgeoning\n2 Sol Ring")

    def test_a_direct_card_link_is_kept_as_is(self):
        first = self.order["cards"][0]
        self.assertIn("product_id=34189", first["url"])

    def test_a_card_without_a_direct_link_gets_a_search_link(self):
        second = self.order["cards"][1]
        self.assertEqual(second["url"], "")
        self.assertIn(urllib.parse.quote("Sol Ring"), second["search_url"])

    def test_cards_without_direct_links_are_listed(self):
        self.assertEqual(self.order["missing_links"], ["Sol Ring"])

    def test_the_sellers_line_comes_through_without_markup(self):
        """It is what you check the printing against before paying."""
        self.assertEqual(self.order["cards"][0]["line"],
                         "Burgeoning (Special Guests) 2500")

    def test_an_unverified_shop_gives_no_search_links(self):
        order = shops.order_for_lot(lot("angrybottlegnome.ru", items=[item("Sol Ring")]))
        self.assertIsNone(order["cards"][0]["search_url"])
        self.assertEqual(order["list_text"], "1 Sol Ring")


class TestOrdersForPlan(unittest.TestCase):
    def test_only_shops_get_orders(self):
        plan = {"lots": [
            lot("spellmarket.ru", kind="shop"),
            lot("Wonderslav", kind="user"),
            lot("mtgsale.ru", kind="shop"),
        ]}
        orders = shops.orders_for_plan(plan)
        self.assertEqual([o["seller_name"] for o in orders],
                         ["spellmarket.ru", "mtgsale.ru"])

    def test_a_plan_without_shops_yields_nothing(self):
        self.assertEqual(shops.orders_for_plan({"lots": [lot("X", kind="user")]}), [])

    def test_an_empty_plan_is_fine(self):
        self.assertEqual(shops.orders_for_plan({}), [])


class TestOrderForNames(unittest.TestCase):
    def test_a_bare_list_still_gets_search_links(self):
        order = shops.order_for_names(["Sol Ring", "Burgeoning"], "mtgsale.ru")
        self.assertEqual(order["list_text"], "1 Sol Ring\n1 Burgeoning")
        self.assertTrue(all(c["search_url"] for c in order["cards"]))
        self.assertEqual(order["links"], [])

    def test_blank_names_are_dropped(self):
        order = shops.order_for_names(["Sol Ring", "", "   "], "mtgsale.ru")
        self.assertEqual(len(order["cards"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
