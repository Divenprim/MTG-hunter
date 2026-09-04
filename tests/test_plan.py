"""Tests for the buying plan.

The bugs these guard against, both found on real topdeck data:
  * only the single cheapest listing per card was used, so a want of 4 filled
    just 1 copy when that listing had 1 in stock;
  * a seller's several listings of the same card were ignored, understating
    their coverage.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.hunt import Candidate, Want, build_plan  # noqa: E402
from app.lineparse import ParsedLine  # noqa: E402
from app.topdeck import Offer, Seller  # noqa: E402


def cand(want, cost, qty, seller, kind="user", certainty="exact", seller_id=None):
    s = Seller(name=seller, kind=kind, id=seller_id or seller, refs=10, city="Москва")
    o = Offer(
        name=want, eng_name=want, rus_name="", qty=qty, cost=cost, seller=s,
        source="topdeck" if kind == "user" else seller, url="", stamp="",
        line="%d %s %d" % (qty, want, cost),
    )
    c = Candidate(offer=o, parsed=ParsedLine(set_code="m10"), want=want)
    c.certainty = certainty
    return c


def bought(plan):
    got = {}
    for lot in plan["lots"]:
        for item in lot["items"]:
            got[item["want"]] = got.get(item["want"], 0) + item["quantity"]
    return got


class TestPlanFillsQuantities(unittest.TestCase):
    def test_price_strategy_walks_down_the_price_list(self):
        """4 wanted; cheapest listing stocks 1, so the rest must come from the
        next listings up."""
        wants = [Want(name="Lightning Bolt", quantity=4)]
        cands = [
            cand("Lightning Bolt", 100, 1, "cheap_guy"),
            cand("Lightning Bolt", 150, 2, "mid_guy"),
            cand("Lightning Bolt", 200, 4, "rich_guy"),
        ]
        plan = build_plan(wants, cands, prefer="price")
        self.assertEqual(bought(plan), {"Lightning Bolt": 4})
        self.assertEqual(plan["unfilled"], [])
        # 1*100 + 2*150 + 1*200
        self.assertEqual(plan["total"], 600)

    def test_seller_strategy_uses_all_of_one_sellers_listings(self):
        """One seller lists the same card three times (different printings).
        Their coverage is 4, not 1."""
        wants = [Want(name="Sol Ring", quantity=4)]
        cands = [
            cand("Sol Ring", 80, 1, "hoarder", seller_id="1"),
            cand("Sol Ring", 90, 1, "hoarder", seller_id="1"),
            cand("Sol Ring", 95, 2, "hoarder", seller_id="1"),
            cand("Sol Ring", 70, 1, "other", seller_id="2"),
        ]
        plan = build_plan(wants, cands, prefer="sellers")
        self.assertEqual(bought(plan), {"Sol Ring": 4})
        self.assertEqual(plan["sellers"], 1)
        self.assertEqual(plan["lots"][0]["seller_name"], "hoarder")

    def test_seller_strategy_prefers_fewer_sellers(self):
        wants = [Want(name="A", quantity=1), Want(name="B", quantity=1)]
        cands = [
            cand("A", 500, 1, "both", seller_id="1"),
            cand("B", 500, 1, "both", seller_id="1"),
            cand("A", 10, 1, "cheap_a", seller_id="2"),
            cand("B", 10, 1, "cheap_b", seller_id="3"),
        ]
        plan = build_plan(wants, cands, prefer="sellers")
        self.assertEqual(plan["sellers"], 1)
        self.assertEqual(bought(plan), {"A": 1, "B": 1})

    def test_price_strategy_ignores_seller_count(self):
        wants = [Want(name="A", quantity=1), Want(name="B", quantity=1)]
        cands = [
            cand("A", 500, 1, "both", seller_id="1"),
            cand("B", 500, 1, "both", seller_id="1"),
            cand("A", 10, 1, "cheap_a", seller_id="2"),
            cand("B", 10, 1, "cheap_b", seller_id="3"),
        ]
        plan = build_plan(wants, cands, prefer="price")
        self.assertEqual(plan["total"], 20)
        self.assertEqual(plan["sellers"], 2)

    def test_certainty_beats_price_in_seller_strategy(self):
        wants = [Want(name="A", quantity=1)]
        cands = [
            cand("A", 50, 1, "vague", seller_id="1", certainty="ambiguous"),
            cand("A", 90, 1, "clear", seller_id="1", certainty="exact"),
        ]
        plan = build_plan(wants, cands, prefer="sellers")
        self.assertEqual(plan["lots"][0]["items"][0]["unit_price"], 90)

    def test_unfilled_is_reported_honestly(self):
        wants = [Want(name="A", quantity=4)]
        cands = [cand("A", 50, 1, "only", seller_id="1")]
        plan = build_plan(wants, cands, prefer="sellers")
        self.assertEqual(bought(plan), {"A": 1})
        self.assertEqual(plan["unfilled"], [{"name": "A", "still_missing": 3}])

    def test_rejected_candidates_are_not_bought(self):
        wants = [Want(name="A", quantity=2)]
        c1 = cand("A", 50, 5, "bad", seller_id="1")
        c1.rejected = "language not wanted"
        plan = build_plan(wants, [c1], prefer="sellers")
        self.assertEqual(plan["lots"], [])
        self.assertEqual(plan["unfilled"], [{"name": "A", "still_missing": 2}])


class TestPlanDoesNotOverpayASellerItAlreadyUses(unittest.TestCase):
    """The bug the user caught, in the smallest shape that reproduces it.

    Their words: "он хочет купить Dark Ritual в магазине за 500, хотя уже есть
    заказ у пользователя Animek, где его можно купить за 400".

    The greedy loop picks the seller covering the most cards, assigns their
    cards, and never looks back. So the shop -- picked first for covering two
    cards -- kept Dark Ritual at 500 even after Animek joined the plan with the
    same card at 400. Same postage, more money, for no reason but loop order.
    """

    def setUp(self):
        # The shop covers two cards, so the greedy pass takes it first.
        self.shop_bolt = cand("Lightning Bolt", 100, 1, "shop.example", kind="shop")
        self.shop_ritual = cand("Dark Ritual", 500, 1, "shop.example", kind="shop")
        # Animek joins the plan for Sol Ring, and also sells the ritual cheaper.
        self.animek_ritual = cand("Dark Ritual", 400, 1, "Animek")
        self.animek_sol = cand("Sol Ring", 100, 1, "Animek")
        # A card only the shop has, so the shop wins the first greedy round --
        # which is exactly how the real plan ended up buying from it.
        self.shop_only = cand("Ancient Tomb", 900, 1, "shop.example", kind="shop")
        self.cands = [self.shop_bolt, self.shop_ritual, self.shop_only,
                      self.animek_ritual, self.animek_sol]
        self.wants = [
            Want(name="Lightning Bolt", quantity=1),
            Want(name="Dark Ritual", quantity=1),
            Want(name="Sol Ring", quantity=1),
            Want(name="Ancient Tomb", quantity=1),
        ]

    def seller_of(self, plan, card):
        for lot in plan["lots"]:
            for item in lot["items"]:
                if item["want"] == card:
                    return lot["seller_name"], item["unit_price"]
        return None, None

    def test_the_card_is_bought_from_the_seller_who_is_cheaper(self):
        plan = build_plan(self.wants, self.cands)
        seller, price = self.seller_of(plan, "Dark Ritual")
        self.assertEqual((seller, price), ("Animek", 400),
                         "Dark Ritual куплен у %s за %s" % (seller, price))

    def test_it_does_not_cost_a_new_seller(self):
        """Animek was in the plan anyway, so this costs no extra postage."""
        plan = build_plan(self.wants, self.cands)
        self.assertEqual(plan["sellers"], 2)

    def test_the_move_is_reported_with_the_saving(self):
        plan = build_plan(self.wants, self.cands)
        self.assertEqual(plan["saved"], 100)
        move = next(m for m in plan["moves"] if m["want"] == "Dark Ritual")
        self.assertEqual(move["from_price"], 500)
        self.assertEqual(move["to_price"], 400)
        self.assertEqual(move["to_seller"], "Animek")

    def test_everything_is_still_bought(self):
        plan = build_plan(self.wants, self.cands)
        self.assertEqual(bought(plan), {"Lightning Bolt": 1, "Dark Ritual": 1,
                                        "Sol Ring": 1, "Ancient Tomb": 1})
        self.assertEqual(plan["unfilled"], [])

    def test_a_seller_left_with_nothing_drops_out(self):
        """If everything moves away, the plan gets shorter as well as cheaper."""
        wants = [Want(name="Dark Ritual", quantity=1), Want(name="Sol Ring", quantity=1)]
        cands = [
            cand("Dark Ritual", 500, 1, "shop.example", kind="shop"),
            cand("Dark Ritual", 400, 1, "Animek"),
            cand("Sol Ring", 100, 1, "Animek"),
        ]
        plan = build_plan(wants, cands)
        self.assertEqual([lot["seller_name"] for lot in plan["lots"]], ["Animek"])
        self.assertEqual(plan["total"], 500)

    def test_certainty_is_not_traded_away_for_price(self):
        """A vague cheap listing must not displace a fully described one."""
        vague = cand("Dark Ritual", 300, 1, "Animek", certainty="partial")
        cands = [self.shop_bolt, self.shop_ritual, self.shop_only,
                 vague, self.animek_sol]
        plan = build_plan(self.wants, cands)
        seller, price = self.seller_of(plan, "Dark Ritual")
        self.assertEqual((seller, price), ("shop.example", 500),
                         "смутное объявление не должно вытеснять описанное")

    def test_stock_is_respected_when_moving(self):
        """Animek has one copy; the second must stay where it was."""
        wants = [Want(name="Dark Ritual", quantity=2),
                 Want(name="Sol Ring", quantity=1)]
        cands = [
            cand("Dark Ritual", 500, 2, "shop.example", kind="shop"),
            cand("Dark Ritual", 400, 1, "Animek"),
            cand("Sol Ring", 100, 1, "Animek"),
        ]
        plan = build_plan(wants, cands)
        self.assertEqual(bought(plan)["Dark Ritual"], 2)
        prices = sorted(
            item["unit_price"]
            for lot in plan["lots"] for item in lot["items"]
            if item["want"] == "Dark Ritual"
        )
        self.assertEqual(prices, [400, 500])


class TestChoosingTheSupplierByHand(unittest.TestCase):
    """The user asked to be able to choose, so the plan takes instructions."""

    def setUp(self):
        self.cheap = cand("Dark Ritual", 400, 1, "Animek")
        self.dear = cand("Dark Ritual", 500, 1, "shop.example", kind="shop")
        self.cands = [self.cheap, self.dear]
        self.wants = [Want(name="Dark Ritual", quantity=1)]

    def test_a_pinned_offer_is_used_even_when_dearer(self):
        plan = build_plan(self.wants, self.cands,
                          pins={"Dark Ritual": self.dear.offer.key})
        self.assertEqual(plan["lots"][0]["seller_name"], "shop.example")
        self.assertEqual(plan["total"], 500)

    def test_a_pin_is_not_undone_by_the_improvement_pass(self):
        plan = build_plan(self.wants, self.cands,
                          pins={"Dark Ritual": self.dear.offer.key})
        self.assertEqual(plan["moves"], [])

    def test_the_pin_is_reported_back(self):
        plan = build_plan(self.wants, self.cands,
                          pins={"Dark Ritual": self.dear.offer.key})
        self.assertEqual(plan["pins"], {"Dark Ritual": self.dear.offer.key})

    def test_a_stale_pin_is_ignored_rather_than_breaking_the_plan(self):
        plan = build_plan(self.wants, self.cands, pins={"Dark Ritual": "nosuchkey"})
        self.assertEqual(bought(plan), {"Dark Ritual": 1})

    def test_every_supplier_is_offered_as_a_choice(self):
        plan = build_plan(self.wants, self.cands)
        rows = plan["alternatives"]["Dark Ritual"]
        self.assertEqual([r["price"] for r in rows], [400, 500])
        self.assertEqual([r["seller_name"] for r in rows], ["Animek", "shop.example"])
        self.assertTrue(rows[0]["chosen"])
        self.assertFalse(rows[1]["chosen"])


class TestBuyingItAllFromOneSeller(unittest.TestCase):
    """"Suppose I want to buy it all in another shop" -- so that is a setting."""

    def setUp(self):
        self.wants = [Want(name="Lightning Bolt", quantity=1),
                      Want(name="Dark Ritual", quantity=1)]
        self.cands = [
            cand("Lightning Bolt", 100, 1, "Animek"),
            cand("Dark Ritual", 400, 1, "Animek"),
            cand("Lightning Bolt", 150, 1, "shop.example", kind="shop"),
            cand("Dark Ritual", 500, 1, "shop.example", kind="shop"),
        ]

    def test_the_chosen_seller_supplies_everything_they_stock(self):
        plan = build_plan(self.wants, self.cands, prefer_seller="shop:shop.example")
        self.assertEqual([lot["seller_name"] for lot in plan["lots"]], ["shop.example"])
        self.assertEqual(plan["total"], 650)

    def test_the_improvement_pass_does_not_undo_the_wish(self):
        """Animek is cheaper, but the user said where they want to buy."""
        plan = build_plan(self.wants, self.cands, prefer_seller="shop:shop.example")
        self.assertEqual(plan["moves"], [])
        self.assertEqual(plan["prefer_seller"], "shop:shop.example")

    def test_what_the_seller_does_not_stock_is_bought_elsewhere(self):
        wants = self.wants + [Want(name="Sol Ring", quantity=1)]
        cands = self.cands + [cand("Sol Ring", 80, 1, "Animek")]
        plan = build_plan(wants, cands, prefer_seller="shop:shop.example")
        sellers = sorted(lot["seller_name"] for lot in plan["lots"])
        self.assertEqual(sellers, ["Animek", "shop.example"])
        self.assertEqual(bought(plan)["Sol Ring"], 1)

    def test_who_could_cover_the_order_is_reported(self):
        plan = build_plan(self.wants, self.cands)
        cover = {c["name"]: c["cards"] for c in plan["coverage"]}
        self.assertEqual(cover, {"Animek": 2, "shop.example": 2})


if __name__ == "__main__":
    unittest.main(verbosity=2)
