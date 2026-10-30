"""Tests for the purchase-request drafts.

The user's instruction was explicit: the message must not be an invoice. Just
    greet, then list the cards by copying the seller's own lines from their thread.
An earlier version wrote

    — 1 шт. × 2074 руб. = 2074 руб.
      ваша позиция: "11 Burgeoning (NM, CN2)"
    Итого: 2074 руб. за 1 шт.

which reads like a bill sent to a stranger. These tests pin the plain form down
so it cannot drift back.

Потом оно поползло обратно иначе -- приписками в хвосте строки: «— нужно 1
шт., 2074 ₽ за шт.». Правило теперь одно, и проверяется здесь: строка
заказа -- это количество первым символом и дальше строка продавца слово в
слово. Собственное количество продавца слева уступает место нашему, больше
не меняется ничего.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.messages import GREETING, draft_for_lot, drafts_for_plan  # noqa: E402

# В первой строке цены нет -- значит её дописывают; во второй есть -- значит
# строку не трогают. На этой паре и держится всё поведение.
BURG_LINE = "11 <b>Burgeoning</b> (NM, CN2)"
BURG_QUOTED = "11 Burgeoning (NM, CN2)"
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

    def test_every_card_line_starts_with_the_count(self):
        """Количество -- первый символ строки, а не приписка в хвосте."""
        body = [l for l in self.msg.split("\n") if l.strip()]
        for line in body[2:-1]:
            self.assertRegex(line, r"^\d+ \S", line)

    def test_nothing_of_ours_follows_the_sellers_text(self):
        for banned in ("нужно", "за шт", "₽"):
            self.assertNotIn(banned, self.msg, banned)

    def test_html_from_the_listing_is_stripped(self):
        self.assertNotIn("<b>", self.msg)

    def test_no_invoice_arithmetic(self):
        for banned in ("Итого", " × ", " = ", "шт. ×", "руб. за"):
            self.assertNotIn(banned, self.msg, "нашлось оформление чека: %r" % banned)

    def test_no_total_is_computed(self):
        """Цена за штуку -- продавцова, а сумма -- наша, и её в письме нет."""
        total = 11 * 2074 + 4 * 145
        self.assertNotIn(str(total), self.msg)
        self.assertNotIn("22814", self.msg)      # 11 x 2074, если бы посчитали
        self.assertNotIn("Итого", self.msg)

    def test_a_line_that_already_has_a_price_is_not_touched(self):
        """Иначе в строке оказалось бы две цены подряд."""
        self.assertIn(BOLT_LINE, self.msg)
        self.assertEqual(self.msg.count("145"), 1)

    def test_a_price_that_lives_outside_the_line_is_not_invented(self):
        """Её нет в строке продавца -- значит пересказывать нечего."""
        self.assertNotIn("2074", self.msg)

    def test_cards_are_one_per_line(self):
        body = [l for l in self.msg.split("\n") if l.strip()]
        self.assertIn(BURG_QUOTED, body)
        self.assertIn(BOLT_LINE, body)


class TestTheCountGoesFirst(unittest.TestCase):
    """Сколько берём -- первым символом, и это единственная наша правка."""

    def test_taking_fewer_than_offered_shows_our_count_not_theirs(self):
        """«11 Burgeoning» не говорит, что нужна одна."""
        msg = draft_for_lot(lot([item("Burgeoning", 1, 2074, BURG_LINE, stock=11)]))
        self.assertIn("1 Burgeoning (NM, CN2)", msg)
        self.assertNotIn("11 Burgeoning", msg)

    def test_the_rest_of_the_line_is_untouched(self):
        msg = draft_for_lot(lot([item("Lightning Bolt", 2, 145, BOLT_LINE, stock=4)]))
        self.assertIn("2 Lightning Bolt (NM EN CLB #187) - 145 руб", msg)

    def test_taking_the_whole_listing_still_states_the_count(self):
        msg = draft_for_lot(lot([item("Lightning Bolt", 4, 145, BOLT_LINE, stock=4)]))
        self.assertIn(BOLT_LINE, msg)
        self.assertNotIn("нужно", msg)

    def test_their_count_may_be_written_in_other_ways(self):
        for line in ("4 x Growth Spiral (NM) 50р", "4x Growth Spiral (NM) 50р",
                     "4 х Growth Spiral (NM) 50р"):
            msg = draft_for_lot(lot([item("Growth Spiral", 2, 50, line, stock=4)]))
            self.assertIn("2 Growth Spiral (NM) 50р", msg, line)

    def test_a_year_in_the_name_is_not_a_count(self):
        """«1996 World Champion» -- карта, а не тысяча девятьсот штук."""
        line = "1996 World Champion (proxy) 100 руб"
        msg = draft_for_lot(lot([item("1996 World Champion", 1, 100, line, stock=1)]))
        self.assertIn("1 1996 World Champion (proxy) 100 руб", msg)

    def test_nothing_is_added_when_the_price_is_unknown(self):
        msg = draft_for_lot(lot([item("Burgeoning", 11, 0, BURG_LINE, stock=11)]))
        self.assertIn("11 Burgeoning (NM, CN2)", msg)
        self.assertNotIn("₽", msg)

    def test_a_listing_without_a_line_falls_back_to_the_name(self):
        msg = draft_for_lot(lot([item("Sol Ring", 2, 80, "", stock=0)]))
        self.assertIn("2 Sol Ring", msg)


class TestTemplates(unittest.TestCase):
    def test_short_template_still_greets_and_lists(self):
        msg = draft_for_lot(lot([item("Burgeoning", 11, 2074, BURG_LINE)]), "ru_short")
        self.assertTrue(msg.startswith(GREETING))
        self.assertIn("11 Burgeoning (NM, CN2)", msg)
        self.assertNotIn("Итого", msg)

    def test_bare_template_is_greeting_plus_lines_only(self):
        msg = draft_for_lot(lot([item("Burgeoning", 11, 2074, BURG_LINE)]), "ru_bare")
        self.assertEqual(msg, GREETING + "\n\n" + BURG_QUOTED)

    def test_the_bare_template_keeps_a_priced_line_exactly(self):
        msg = draft_for_lot(lot([item("Lightning Bolt", 4, 145, BOLT_LINE)]), "ru_bare")
        self.assertEqual(msg, GREETING + "\n\n" + BOLT_LINE)

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
