"""A price we cannot trust must not survive to the plan.

topdeck parses seller lines itself and gets it wrong. Two real examples:

    1 Тиамат (Tiamat) #235/281 AFR RU 1300   -> topdeck says 235
    1 Dark Ritual V13 900                    -> topdeck says 13

The second one got all the way into the buying plan and was offered as the
cheapest copy, because the verdict was set in `gather` and then quietly
overwritten by `apply_filters`, which recomputes `rejected` from the filters.
The dispute now lives in its own field and outlives that pass.

Money depends on this, so it is tested end to end: gather, filter, plan.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cards import CardDB  # noqa: E402
from app.hunt import Filters, Hunter, Want, build_plan  # noqa: E402
from app.topdeck import Offer, Seller  # noqa: E402

DB = CardDB()


class FakeClient:
    def __init__(self, offers):
        self._offers = offers

    def search(self, names):
        return list(self._offers)


def offer(name, cost, line, qty=1, seller="seller-a"):
    return Offer(
        name=name, eng_name=name, rus_name="", qty=qty, cost=cost,
        seller=Seller(name=seller, kind="user", id=seller, refs=10, city="Москва"),
        source="topdeck", url="", stamp="", line=line,
    )


class TestDisputedPriceNeverReachesThePlan(unittest.TestCase):
    """The exact listing that got through: 13 roubles for a 900-rouble card."""

    def setUp(self):
        self.wants = [Want(name="Dark Ritual", quantity=1)]
        self.bogus = offer("Dark Ritual", 13, "1 Dark Ritual V13 900")
        self.real = offer("Dark Ritual", 270, "1 Dark Ritual (MB1 EN NM) - 270",
                          seller="seller-b")

    def gathered(self, offers, filters=True):
        hunter = Hunter(DB, FakeClient(offers))
        cands = hunter.gather(self.wants)
        if filters:
            hunter.apply_filters(cands, Filters())
        return cands

    def test_gather_marks_the_dispute(self):
        cands = self.gathered([self.bogus], filters=False)
        self.assertTrue(cands[0].price_dispute)
        self.assertIn("13", cands[0].price_dispute)
        self.assertIn("900", cands[0].price_dispute)

    def test_the_filter_pass_does_not_wipe_it(self):
        """This is the bug: judge() used to overwrite the verdict."""
        cands = self.gathered([self.bogus])
        self.assertTrue(cands[0].rejected, "спорная цена снова прошла фильтры")
        self.assertEqual(cands[0].rejected, cands[0].price_dispute)

    def test_the_plan_buys_the_trustworthy_listing(self):
        cands = self.gathered([self.bogus, self.real])
        plan = build_plan(self.wants, cands)
        prices = [i["unit_price"] for lot in plan["lots"] for i in lot["items"]]
        self.assertEqual(prices, [270])

    def test_it_is_not_offered_as_an_alternative_either(self):
        """The chooser must not dangle a 13-rouble bargain that does not exist."""
        cands = self.gathered([self.bogus, self.real])
        plan = build_plan(self.wants, cands)
        rows = plan["alternatives"]["Dark Ritual"]
        self.assertEqual([r["price"] for r in rows], [270])

    def test_the_reason_travels_to_the_interface(self):
        cands = self.gathered([self.bogus])
        row = cands[0].as_dict()
        self.assertIn("topdeck", row["price_dispute"])
        self.assertIn("900", row["price_dispute"])

    def test_an_agreeing_price_is_left_alone(self):
        cands = self.gathered([self.real])
        self.assertIsNone(cands[0].price_dispute)
        self.assertIsNone(cands[0].rejected)

    def test_a_line_without_a_price_is_not_a_dispute(self):
        """Most shop lines carry no price; that is not a disagreement."""
        quiet = offer("Dark Ritual", 350, "1 <b>Dark Ritual</b> (NM, MB1)")
        cands = self.gathered([quiet])
        self.assertIsNone(cands[0].price_dispute)
        self.assertIsNone(cands[0].rejected)

    def test_a_filter_rejection_still_wins_when_there_is_one(self):
        """Both reasons are real; the filter's is the one the user set."""
        hunter = Hunter(DB, FakeClient([self.bogus]))
        cands = hunter.gather(self.wants)
        hunter.apply_filters(cands, Filters(max_price=1))
        self.assertTrue(cands[0].rejected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
