"""Tests for changing your mind about a card in the plan.

An offer can be refused (take the card from someone else), a card can be
dropped entirely, fewer copies can be taken -- and every one of those is
undoable, because refusals are re-applied from scratch on each rebuild rather
than accumulated.

Rebuilding must never go back to topdeck: the offers are the ones already
fetched, so the plan changes instantly.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.hunt import Candidate, Want, build_plan  # noqa: E402
from app.lineparse import ParsedLine  # noqa: E402
from app.topdeck import Offer, Seller  # noqa: E402


def cand(want, cost, qty, seller, line=None):
    s = Seller(name=seller, kind="user", id=seller, refs=10, city="Москва")
    o = Offer(
        name=want, eng_name=want, rus_name="", qty=qty, cost=cost, seller=s,
        source="topdeck", url="", stamp="",
        line=line or "%d %s %d" % (qty, want, cost),
    )
    c = Candidate(offer=o, parsed=ParsedLine(set_code="m10"), want=want)
    c.certainty = "exact"
    return c


def bought(plan):
    got = {}
    for lot in plan["lots"]:
        for it in lot["items"]:
            got[it["want"]] = got.get(it["want"], 0) + it["quantity"]
    return got


def lines(plan):
    return [it["offer"]["line"] for lot in plan["lots"] for it in lot["items"]]


class TestOfferKey(unittest.TestCase):
    """The interface has to be able to point back at one exact listing."""

    def test_the_same_listing_keys_the_same_every_time(self):
        a = cand("Sol Ring", 80, 1, "seller-a")
        b = cand("Sol Ring", 80, 1, "seller-a")
        self.assertEqual(a.offer.key, b.offer.key)

    def test_different_listings_key_differently(self):
        a = cand("Sol Ring", 80, 1, "seller-a")
        b = cand("Sol Ring", 100, 1, "seller-a")
        c = cand("Sol Ring", 80, 1, "seller-b")
        self.assertNotEqual(a.offer.key, b.offer.key)
        self.assertNotEqual(a.offer.key, c.offer.key)

    def test_the_key_travels_in_the_json(self):
        c = cand("Sol Ring", 80, 1, "seller-a")
        self.assertEqual(c.as_dict()["key"], c.offer.key)


class TestRefusingAnOffer(unittest.TestCase):
    def setUp(self):
        self.wants = [Want(name="Sol Ring", quantity=1)]
        self.cheap = cand("Sol Ring", 80, 1, "seller-a")
        self.dearer = cand("Sol Ring", 100, 1, "seller-b")
        self.cands = [self.cheap, self.dearer]

    def test_the_cheapest_is_taken_by_default(self):
        plan = build_plan(self.wants, self.cands, prefer="price")
        self.assertEqual(lines(plan), [self.cheap.offer.line])

    def test_a_refused_offer_is_replaced_by_the_next_one(self):
        self.cheap.refused = "вы отказались от этого предложения"
        plan = build_plan(self.wants, self.cands, prefer="price")
        self.assertEqual(lines(plan), [self.dearer.offer.line])
        self.assertEqual(bought(plan), {"Sol Ring": 1})

    def test_taking_the_refusal_back_restores_the_plan(self):
        first = build_plan(self.wants, self.cands, prefer="price")
        self.cheap.refused = "вы отказались от этого предложения"
        build_plan(self.wants, self.cands, prefer="price")
        self.cheap.refused = None
        again = build_plan(self.wants, self.cands, prefer="price")
        self.assertEqual(lines(again), lines(first))
        self.assertEqual(again["total"], first["total"])

    def test_refusing_every_offer_reports_the_card_as_unfilled(self):
        for c in self.cands:
            c.refused = "вы отказались от этого предложения"
        plan = build_plan(self.wants, self.cands, prefer="price")
        self.assertEqual(plan["lots"], [])
        self.assertEqual([u["name"] for u in plan["unfilled"]], ["Sol Ring"])

    def test_a_refusal_does_not_erase_why_a_filter_dropped_an_offer(self):
        """`refused` and `rejected` are separate, so undoing one keeps the other."""
        self.dearer.rejected = "дороже лимита"
        self.cheap.refused = "вы отказались от этого предложения"
        plan = build_plan(self.wants, self.cands, prefer="price")
        self.assertEqual(plan["lots"], [])
        self.cheap.refused = None
        self.assertEqual(self.dearer.rejected, "дороже лимита")


class TestRefusingACard(unittest.TestCase):
    def test_a_dropped_card_leaves_the_others_alone(self):
        wants = [Want(name="Sol Ring", quantity=1)]  # Burgeoning already dropped
        cands = [cand("Sol Ring", 80, 1, "seller-a"), cand("Burgeoning", 2074, 1, "seller-a")]
        for c in cands:
            if c.want == "Burgeoning":
                c.refused = "вы решили не брать эту карту"
        plan = build_plan(wants, cands)
        self.assertEqual(bought(plan), {"Sol Ring": 1})
        self.assertEqual(plan["unfilled"], [])

    def test_a_dropped_card_is_not_reported_as_unavailable(self):
        """Dropping it yourself is not the same as nobody selling it."""
        wants = [Want(name="Sol Ring", quantity=1)]
        cands = [cand("Sol Ring", 80, 1, "seller-a")]
        plan = build_plan(wants, cands)
        self.assertEqual(plan["unfilled"], [])


class TestTakingFewerCopies(unittest.TestCase):
    def test_fewer_copies_costs_less(self):
        cands = [cand("Lightning Bolt", 150, 4, "seller-a")]
        full = build_plan([Want(name="Lightning Bolt", quantity=4)], cands)
        part = build_plan([Want(name="Lightning Bolt", quantity=1)], cands)
        self.assertEqual(bought(full), {"Lightning Bolt": 4})
        self.assertEqual(bought(part), {"Lightning Bolt": 1})
        self.assertLess(part["total"], full["total"])

    def test_restoring_the_count_restores_the_total(self):
        cands = [cand("Lightning Bolt", 150, 4, "seller-a")]
        wants4 = [Want(name="Lightning Bolt", quantity=4)]
        first = build_plan(wants4, cands)
        build_plan([Want(name="Lightning Bolt", quantity=1)], cands)
        again = build_plan(wants4, cands)
        self.assertEqual(again["total"], first["total"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
