"""У базовой земли не бывает «не той печати».

Правило «уверенность важнее цены» защищает от подмены карты: объявление без
указанного сета может оказаться любой печатью, поэтому оно уступает
объявлению, где сет назван, даже если оно дешевле. Для базовой земли
защищать нечего — любой Лес это Лес, принт из колоды всё равно не
закрепляется, — а правило работало и там:

    3 Forest (NM, Kaldheim) - 36 руб      ← сет назван, «exact»
    3 Forest (NM) - 11 руб                ← сета нет, «partial», проигрывает

и план покупал землю за 36, показывая рядом её же за 11 у того же продавца.

Проверяется и обратное: у обычной карты правило остаётся как было.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cards import CardDB  # noqa: E402
from app.hunt import Candidate, Filters, Hunter, Want, assess, build_plan  # noqa: E402
from app.lineparse import ParsedLine  # noqa: E402
from app.topdeck import Offer, Seller  # noqa: E402

DB = CardDB()


def hunter():
    """Охотник без сети: клиент тут не используется, нужна только база карт."""
    return Hunter(DB, client=object(), set_index=object())


def cand(name, cost, qty, seller, set_code=None, kind="shop"):
    s = Seller(name=seller, kind=kind, id=seller, refs=10, city="Москва")
    line = "%d %s (NM%s) - %d руб" % (
        qty, name, ", " + set_code.upper() if set_code else "", cost)
    o = Offer(name=name, eng_name=name, rus_name="", qty=qty, cost=cost, seller=s,
              source=seller, url="", stamp="", line=line)
    return Candidate(offer=o, parsed=ParsedLine(set_code=set_code), want=name)


class TestWhatCountsAsBasic(unittest.TestCase):
    def setUp(self):
        self.h = hunter()

    def test_the_five_and_wastes(self):
        for name in ("Forest", "Island", "Swamp", "Mountain", "Plains", "Wastes"):
            self.assertTrue(self.h._is_basic_land(name), name)

    def test_snow_covered_too(self):
        self.assertTrue(self.h._is_basic_land("Snow-Covered Forest"))

    def test_an_ordinary_card_is_not(self):
        for name in ("Lightning Bolt", "Sol Ring", "Ancient Tomb", "Dryad Arbor"):
            self.assertFalse(self.h._is_basic_land(name), name)

    def test_a_name_we_do_not_know_is_not_basic(self):
        self.assertFalse(self.h._is_basic_land("Не карта, а название"))
        self.assertFalse(self.h._is_basic_land(""))


class TestCertainty(unittest.TestCase):
    def test_a_missing_set_is_not_a_doubt_for_a_basic(self):
        certainty, gaps = assess(ParsedLine(), Filters(), basic_land=True)
        self.assertEqual(certainty, "exact")
        self.assertEqual(gaps, [])

    def test_it_still_is_for_everything_else(self):
        certainty, gaps = assess(ParsedLine(), Filters(), basic_land=False)
        self.assertEqual(certainty, "partial")
        self.assertIn("set not stated", gaps)

    def test_language_and_condition_still_count_for_basics(self):
        """Их выбрал сам пользователь -- это не наша догадка о печати."""
        certainty, gaps = assess(
            ParsedLine(), Filters(languages=["ru"]), basic_land=True)
        self.assertEqual(certainty, "partial")
        self.assertEqual(gaps, ["language not stated"])

    def test_a_mixed_listing_stays_ambiguous_even_for_a_basic(self):
        certainty, _gaps = assess(
            ParsedLine(mixed=True), Filters(), basic_land=True)
        self.assertEqual(certainty, "ambiguous")


class TestThePlanBuysTheCheapBasic(unittest.TestCase):
    def setUp(self):
        self.h = hunter()

    def plan_for(self, name, quantity=3, prefer="sellers"):
        cands = [
            cand(name, 36, 4, "shop.example", set_code="khm"),
            cand(name, 11, 4, "shop.example"),
        ]
        self.h.apply_filters(cands, Filters())
        return build_plan([Want(name=name, quantity=quantity)], cands, prefer=prefer)

    def test_the_same_shop_cheaper_wins(self):
        for prefer in ("sellers", "price"):
            plan = self.plan_for("Forest", prefer=prefer)
            prices = [it["unit_price"] for lot in plan["lots"] for it in lot["items"]]
            self.assertEqual(prices, [11], prefer)

    def test_an_ordinary_card_still_pays_for_certainty(self):
        """Обратная сторона правила: тут дешевле -- не значит вернее."""
        plan = self.plan_for("Lightning Bolt")
        prices = [it["unit_price"] for lot in plan["lots"] for it in lot["items"]]
        self.assertEqual(prices, [36])

    def test_the_cheap_basic_is_first_among_suppliers(self):
        plan = self.plan_for("Forest")
        rows = plan["alternatives"]["Forest"]
        self.assertEqual([r["price"] for r in rows], [11, 36])
        self.assertTrue(all(r["certainty"] == "exact" for r in rows))


if __name__ == "__main__":
    unittest.main(verbosity=2)
