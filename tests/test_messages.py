"""Tests for the purchase-request drafts.

The user's instruction was explicit: the message must not be an invoice. Just
    greet, then list the cards by copying the seller's own lines from their thread.
An earlier version wrote

    — 1 шт. × 2074 руб. = 2074 руб.
      ваша позиция: "11 Burgeoning (NM, CN2)"
    Итого: 2074 руб. за 1 шт.

which reads like a bill sent to a stranger. These tests pin the plain form down
so it cannot drift back.

Одно исключение проверяется отдельно: если в строке продавца цены нет вовсе
(она была в поле объявления, а не в тексте), то без неё письмо оставалось
вообще без денег -- цена, которая видна в плане, исчезала по дороге. В таком
случае цена дописывается один раз, его же числом и без арифметики.
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

    def test_a_line_without_a_price_gets_the_one_from_the_listing(self):
        """Цена видна в плане -- значит она должна доехать и до письма."""
        self.assertIn(BURG_QUOTED + " — 2074 ₽ за шт.", self.msg)

    def test_cards_are_one_per_line(self):
        body = [l for l in self.msg.split("\n") if l.strip()]
        self.assertIn(BURG_QUOTED + " — 2074 ₽ за шт.", body)
        self.assertIn(BOLT_LINE, body)


class TestQuantityIsOnlyStatedWhenNeeded(unittest.TestCase):
    def test_taking_fewer_than_offered_says_so(self):
        """"11 Burgeoning" cannot tell the seller that one copy is wanted."""
        msg = draft_for_lot(lot([item("Burgeoning", 1, 2074, BURG_LINE, stock=11)]))
        self.assertIn(BURG_QUOTED + " — нужно 1 шт.", msg)

    def test_the_count_and_the_price_are_one_clause_not_two(self):
        """«— нужно 1 шт. — 2074 ₽» читается как две поправки к одной строке."""
        msg = draft_for_lot(lot([item("Burgeoning", 1, 2074, BURG_LINE, stock=11)]))
        self.assertIn(BURG_QUOTED + " — нужно 1 шт., 2074 ₽ за шт.", msg)
        self.assertEqual(msg.count("—"), 1)

    def test_nothing_is_added_when_the_price_is_unknown(self):
        msg = draft_for_lot(lot([item("Burgeoning", 11, 0, BURG_LINE, stock=11)]))
        self.assertIn(BURG_QUOTED, msg)
        self.assertNotIn("₽", msg)

    def test_taking_the_whole_listing_adds_nothing(self):
        msg = draft_for_lot(lot([item("Lightning Bolt", 4, 145, BOLT_LINE, stock=4)]))
        self.assertIn(BOLT_LINE, msg)
        self.assertNotIn("нужно", msg)

    def test_a_listing_without_a_line_falls_back_to_the_name(self):
        msg = draft_for_lot(lot([item("Sol Ring", 2, 80, "", stock=0)]))
        self.assertIn("Sol Ring — 2 шт.", msg)


class TestWhatCountsAsAPriceInTheLine(unittest.TestCase):
    """Определяется по рублёвой пометке, а не по «есть цифры».

    В строках продавцов полно чисел, которые ценой не являются: номер карты
    (#187), код сета (CN2), год. Принять их за цену значило бы промолчать там,
    где цену как раз надо дописать.
    """

    def has_price(self, line):
        from app.messages import HAS_PRICE

        return bool(HAS_PRICE.search(line))

    def test_the_usual_ways_people_write_roubles(self):
        for line in ("Bolt - 145 руб", "Bolt 145 рублей", "Bolt 70р",
                     "Bolt 145 ₽", "Bolt 145 rub", "Bolt 145руб."):
            self.assertTrue(self.has_price(line), line)

    def test_numbers_that_are_not_prices(self):
        for line in ("11 Burgeoning (NM, CN2)", "Bolt (NM EN CLB #187)",
                     "Ancient Tomb 2004", "4 Lightning Bolt"):
            self.assertFalse(self.has_price(line), line)


class TestTemplates(unittest.TestCase):
    def test_short_template_still_greets_and_lists(self):
        msg = draft_for_lot(lot([item("Burgeoning", 11, 2074, BURG_LINE)]), "ru_short")
        self.assertTrue(msg.startswith(GREETING))
        self.assertIn("11 Burgeoning (NM, CN2)", msg)
        self.assertNotIn("Итого", msg)

    def test_bare_template_is_greeting_plus_lines_only(self):
        msg = draft_for_lot(lot([item("Burgeoning", 11, 2074, BURG_LINE)]), "ru_bare")
        self.assertEqual(
            msg, GREETING + "\n\n" + BURG_QUOTED + " — 2074 ₽ за шт.")

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
