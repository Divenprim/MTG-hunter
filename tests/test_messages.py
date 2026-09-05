"""Tests for the purchase-request drafts.

The user's instruction was explicit: the message must not be an invoice. Just
    greet, then list the cards by copying the seller's own lines from their thread.
An earlier version wrote

    — 1 шт. × 2074 руб. = 2074 руб.
      ваша позиция: "11 Burgeoning (NM, CN2)"
    Итого: 2074 руб. за 1 шт.

which reads like a bill sent to a stranger. These tests pin the plain form down
so it cannot drift back.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.messages import GREETING, draft_for_lot, drafts_for_plan  # noqa: E402

BURG_LINE = "11 <b>Burgeoning</b> (NM, CN2)"
BOLT_LINE = "4 Lightning Bolt (NM EN CLB #187) - 145 руб"


def lot(items, seller="seller-a", kind="user"):
    return {
        "seller_name": seller,
        "seller_kind": kind,
        "seller_city": "Москва",
        "total": sum(i["quantity"] * i["unit_price"] for i in items),
        "items": items,
    }


def item(want, quantity, unit_price, line, stock=None):
    return {
        "want": want,
        "quantity": quantity,
        "unit_price": unit_price,
        "subtotal": quantity * unit_price,
        "offer": {"line": line, "qty": stock if stock is not None else quantity},
    }


class TestDraftShape(unittest.TestCase):
    def setUp(self):
        self.msg = draft_for_lot(lot([
            item("Burgeoning", 11, 2074, BURG_LINE, stock=11),
            item("Lightning Bolt", 4, 145, BOLT_LINE, stock=4),
        ]))

    def test_it_greets_first(self):
        self.assertTrue(self.msg.startswith(GREETING), self.msg[:40])

    def test_polite_wording_is_the_requested_one(self):
        self.assertIn("По Вашей торговой теме интересуют:", self.msg)
        self.assertTrue(self.msg.endswith("Подскажите, всё в наличии?"), self.msg)

    def test_the_seller_lines_are_copied_verbatim(self):
        """Their own text, so they recognise their own listing at a glance."""
        self.assertIn("11 Burgeoning (NM, CN2)", self.msg)
        self.assertIn(BOLT_LINE, self.msg)

    def test_html_from_the_listing_is_stripped(self):
        self.assertNotIn("<b>", self.msg)

    def test_no_invoice_arithmetic(self):
        for banned in ("Итого", " × ", " = ", "шт. ×", "руб. за"):
            self.assertNotIn(banned, self.msg, "нашлось оформление чека: %r" % banned)

    def test_no_total_is_computed(self):
        self.assertNotIn("2074", self.msg.replace(BURG_LINE, ""))

    def test_cards_are_one_per_line(self):
        body = [l for l in self.msg.split("\n") if l.strip()]
        self.assertIn("11 Burgeoning (NM, CN2)", body)
        self.assertIn(BOLT_LINE, body)


class TestQuantityIsOnlyStatedWhenNeeded(unittest.TestCase):
    def test_taking_fewer_than_offered_says_so(self):
        """"11 Burgeoning" cannot tell the seller that one copy is wanted."""
        msg = draft_for_lot(lot([item("Burgeoning", 1, 2074, BURG_LINE, stock=11)]))
        self.assertIn("11 Burgeoning (NM, CN2) — нужно 1 шт.", msg)

    def test_taking_the_whole_listing_adds_nothing(self):
        msg = draft_for_lot(lot([item("Lightning Bolt", 4, 145, BOLT_LINE, stock=4)]))
        self.assertIn(BOLT_LINE, msg)
        self.assertNotIn("нужно", msg)

    def test_a_listing_without_a_line_falls_back_to_the_name(self):
        msg = draft_for_lot(lot([item("Sol Ring", 2, 80, "", stock=0)]))
        self.assertIn("Sol Ring — 2 шт.", msg)


class TestTemplates(unittest.TestCase):
    def test_short_template_still_greets_and_lists(self):
        msg = draft_for_lot(lot([item("Burgeoning", 11, 2074, BURG_LINE)]), "ru_short")
        self.assertTrue(msg.startswith(GREETING))
        self.assertIn("11 Burgeoning (NM, CN2)", msg)
        self.assertNotIn("Итого", msg)

    def test_bare_template_is_greeting_plus_lines_only(self):
        msg = draft_for_lot(lot([item("Burgeoning", 11, 2074, BURG_LINE)]), "ru_bare")
        self.assertEqual(msg, GREETING + "\n\n11 Burgeoning (NM, CN2)")

    def test_unknown_template_falls_back_instead_of_raising(self):
        msg = draft_for_lot(lot([item("Burgeoning", 11, 2074, BURG_LINE)]), "nope")
        self.assertTrue(msg.startswith(GREETING))


class TestDraftsForPlan(unittest.TestCase):
    def test_one_draft_per_seller_with_the_delivery_route(self):
        plan = {"lots": [
            lot([item("Burgeoning", 11, 2074, BURG_LINE)], seller="seller-a"),
            lot([item("Lightning Bolt", 4, 145, BOLT_LINE)],
                seller="spellmarket.ru", kind="shop"),
        ]}
        drafts = drafts_for_plan(plan)
        self.assertEqual([d["seller_name"] for d in drafts],
                         ["seller-a", "spellmarket.ru"])
        # Shops take orders on their site; private sellers by forum PM.
        self.assertEqual([d["delivery"] for d in drafts], ["pm", "site"])
        self.assertTrue(all(d["message"].startswith(GREETING) for d in drafts))

    def test_empty_plan_yields_no_drafts(self):
        self.assertEqual(drafts_for_plan({"lots": []}), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
