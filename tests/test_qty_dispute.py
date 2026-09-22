"""Сколько копий у продавца, когда число topdeck и его строка расходятся.

Живой случай: «4 × Спираль Роста - RU - NM - Ravnica Allegiance - 10».
topdeck отдаёт для этой строки qty=1 -- знака умножения после числа он не
ждёт. План из-за этого брал у частника одну копию по 10 ₽, а оставшиеся три
докупал в магазине по 20 ₽, хотя продавец написал, что их у него четыре.

То же самое ломало закрепление: «беру у этого» на строке с одной копией не
меняло ничего, потому что закреплялась одна копия из четырёх.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.hunt import Candidate, Want, build_plan  # noqa: E402
from app.lineparse import ParsedLine, qty_in_line  # noqa: E402
from app.offermatch import qty_check  # noqa: E402
from app.topdeck import Offer, Seller  # noqa: E402


def cand(want, cost, qty, seller, line, kind="user", seller_id=None,
         qty_from_line=None, reason="спор"):
    s = Seller(name=seller, kind=kind, id=seller_id or seller, refs=10, city="Москва")
    o = Offer(
        name=want, eng_name=want, rus_name="", qty=qty, cost=cost, seller=s,
        source="topdeck" if kind == "user" else seller, url="", stamp="", line=line,
    )
    c = Candidate(offer=o, parsed=ParsedLine(set_code="rna"), want=want)
    c.certainty = "exact"
    if qty_from_line:
        c.qty_in_line = qty_from_line
        c.qty_dispute = reason
    return c


def bought(plan):
    got = {}
    for lot in plan["lots"]:
        for item in lot["items"]:
            key = (lot["seller_name"], item["unit_price"])
            got[key] = got.get(key, 0) + item["quantity"]
    return got


class TestReadingTheCount(unittest.TestCase):
    def test_the_seller_writes_the_count_first(self):
        self.assertEqual(qty_in_line("\t4 × Спираль Роста - RU - NM - 10"), 4)
        self.assertEqual(qty_in_line("3 Growth Spiral ((RU, NM, RNA)) - 10"), 3)
        self.assertEqual(qty_in_line("\t2 - Спираль Роста - 15"), 2)
        self.assertEqual(qty_in_line("5 <b>спираль роста</b>"), 5)
        self.assertEqual(qty_in_line("10 шт. Спираль Роста - 12"), 10)

    def test_a_number_that_is_not_a_count_is_not_read_as_one(self):
        # Номер карты, а не количество: числа слитно с продолжением.
        self.assertIsNone(qty_in_line("235/281 Tiamat"))
        self.assertIsNone(qty_in_line("2015 Tiamat"))
        self.assertIsNone(qty_in_line(""))
        # Количество в конце строки нам не обещали разбирать -- и не надо.
        self.assertIsNone(qty_in_line("Growth Spiral 4 шт - 10"))

    def test_agreement_is_not_a_dispute(self):
        out = qty_check(4, "4 Спираль Роста (LP) - 25 руб")
        self.assertFalse(out["disputed"])
        self.assertEqual(out["qty"], 4)

    def test_the_line_wins_when_they_disagree(self):
        out = qty_check(1, "\t4 × Спираль Роста - RU - NM - 10")
        self.assertTrue(out["disputed"])
        self.assertEqual(out["qty"], 4)
        self.assertIn("4", out["reason"])


class TestThePlanBuysTheCopiesTheSellerHas(unittest.TestCase):
    def test_all_four_copies_come_from_the_seller_who_has_four(self):
        wants = [Want(name="Growth Spiral", quantity=4)]
        cands = [
            cand("Growth Spiral", 10, 1, "Не Смешно",
                 "4 × Спираль Роста - RU - NM - 10", qty_from_line=4),
            cand("Growth Spiral", 20, 4, "shop.example",
                 "4 Спираль Роста - 20", kind="shop"),
        ]
        plan = build_plan(wants, cands, prefer="sellers")
        self.assertEqual(bought(plan), {("Не Смешно", 10): 4})
        self.assertEqual(plan["total"], 40)

    def test_without_the_dispute_nothing_changes(self):
        """Тот же расклад, но продавец и правда с одной копией."""
        wants = [Want(name="Growth Spiral", quantity=4)]
        cands = [
            cand("Growth Spiral", 10, 1, "Не Смешно", "1 Спираль Роста - 10"),
            cand("Growth Spiral", 20, 4, "shop.example", "4 Спираль Роста - 20",
                 kind="shop"),
        ]
        plan = build_plan(wants, cands, prefer="sellers")
        self.assertEqual(bought(plan), {("shop.example", 20): 4})

    def test_the_count_shows_up_in_the_offer_list(self):
        wants = [Want(name="Growth Spiral", quantity=4)]
        cheap = cand("Growth Spiral", 10, 1, "Не Смешно",
                     "4 × Спираль Роста - 10", qty_from_line=4)
        plan = build_plan(wants, [cheap], prefer="sellers")
        row = plan["alternatives"]["Growth Spiral"][0]
        self.assertEqual(row["qty"], 4)
        self.assertEqual(row["qty_in_line"], 4)
        self.assertTrue(row["qty_dispute"])


class TestPinningMeansTheSellerNotTheLine(unittest.TestCase):
    """«Беру у этого» -- про продавца, а не про одну его строку."""

    def test_the_rest_of_the_copies_come_from_the_same_seller(self):
        wants = [Want(name="Growth Spiral", quantity=4)]
        one = cand("Growth Spiral", 10, 1, "Pauperist", "1 Growth Spiral (EN) - 10",
                   seller_id="1")
        three = cand("Growth Spiral", 10, 3, "Pauperist", "3 Growth Spiral (RU) - 10",
                     seller_id="1")
        shop = cand("Growth Spiral", 20, 4, "shop.example", "4 Спираль Роста - 20",
                    kind="shop")
        plan = build_plan(wants, [one, three, shop], prefer="price",
                          pins={"Growth Spiral": one.offer.key})
        self.assertEqual(plan["sellers"], 1)
        self.assertEqual(plan["total"], 40)

    def test_what_the_seller_does_not_have_is_still_bought_elsewhere(self):
        wants = [Want(name="Growth Spiral", quantity=4)]
        one = cand("Growth Spiral", 10, 1, "Pauperist", "1 Growth Spiral - 10",
                   seller_id="1")
        shop = cand("Growth Spiral", 20, 4, "shop.example", "4 Спираль Роста - 20",
                    kind="shop")
        plan = build_plan(wants, [one, shop], prefer="sellers",
                          pins={"Growth Spiral": one.offer.key})
        self.assertEqual(bought(plan), {("Pauperist", 10): 1, ("shop.example", 20): 3})


if __name__ == "__main__":
    unittest.main()
