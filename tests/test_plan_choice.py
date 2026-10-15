"""Б2: план не держится за продавца, которого выбрал первым шагом.

Жадный проход берёт продавца по цене за копию на текущем шаге и больше к
этому выбору не возвращается. Дальше работают только проходы внутри
выбранных: `_improve` переносит карту к тому, кто уже в плане и дешевле,
`_merge_sellers` убирает продавца дешевле собственной пересылки. Сказать «а
надо было с самого начала брать у другого» не умел ни один.

Сверка с полным перебором по мерке из докстринга `build_plan` — деньги плюс
плата за каждого продавца — на 1331 раскладе давала **72** плана дороже
идеала, худший на 180 ₽. После `_resettle` остаётся **3**; они требуют
менять сразу нескольких продавцов, а это уже полный перебор, невозможный на
настоящих размерах (сотни предложений).

Здесь закреплён тот самый расклад, разобранный руками, и общая проверка
«переселение не делает план дороже».
"""

import itertools
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.hunt import Candidate, Want, build_plan  # noqa: E402
from app.lineparse import ParsedLine  # noqa: E402
from app.topdeck import Offer, Seller  # noqa: E402

FEE = 250


def cand(want, cost, qty, seller):
    s = Seller(name=seller, kind="user", id=seller, refs=10)
    o = Offer(name=want, eng_name=want, rus_name="", qty=qty, cost=cost,
              seller=s, source="topdeck", url="", stamp="",
              line="%d %s %d" % (qty, want, cost))
    c = Candidate(offer=o, parsed=ParsedLine(set_code="m10"), want=want)
    c.certainty = "exact"
    return c


def plan_cost(plan, fee=FEE):
    return plan["total"] + fee * plan["sellers"]


def brute_force(wants, cands, fee=FEE):
    """Точный минимум перебором по подмножествам продавцов."""
    sellers = sorted({c.offer.seller.name for c in cands})
    best = None
    for size in range(1, len(sellers) + 1):
        for chosen in itertools.combinations(sellers, size):
            total, ok = 0, True
            for want in wants:
                need = want.quantity
                offers = sorted(
                    [c for c in cands if c.want == want.name
                     and c.offer.seller.name in chosen],
                    key=lambda c: c.offer.cost)
                for c in offers:
                    if need <= 0:
                        break
                    take = min(need, c.offer.qty)
                    total += take * c.offer.cost
                    need -= take
                if need > 0:
                    ok = False
                    break
            if ok:
                cost = total + fee * len(chosen)
                if best is None or cost < best:
                    best = cost
    return best


class TestTheFirstSellerIsNotForever(unittest.TestCase):
    def test_cheap_first_card_does_not_decide_the_whole_order(self):
        """Расклад, на котором это поймали.

        S3 держит карту A дешевле всех (70 против 90), поэтому жадный проход
        открывает его первым — а дальше добирает у него же карту B по 300,
        хотя у S2 она по 220. Один продавец в обоих случаях, разница 180 ₽.
        """
        wants = [Want(name="Card A", quantity=3), Want(name="Card B", quantity=3)]
        cands = [
            cand("Card A", 300, 2, "S1"),
            cand("Card A", 90, 4, "S2"),
            cand("Card B", 220, 4, "S2"),
            cand("Card A", 70, 3, "S3"),
            cand("Card B", 300, 4, "S3"),
        ]
        plan = build_plan(wants, cands, prefer="sellers", seller_fee=FEE)
        self.assertEqual(plan["unfilled"], [])
        self.assertEqual([lot["seller_name"] for lot in plan["lots"]], ["S2"])
        self.assertEqual(plan["total"], 3 * 90 + 3 * 220)
        self.assertEqual(plan_cost(plan), brute_force(wants, cands))

    def test_the_rebuild_is_explained(self):
        """Молча перестраивать план нельзя: числа меняются на глазах."""
        wants = [Want(name="Card A", quantity=3), Want(name="Card B", quantity=3)]
        cands = [
            cand("Card A", 90, 4, "S2"),
            cand("Card B", 220, 4, "S2"),
            cand("Card A", 70, 3, "S3"),
            cand("Card B", 300, 4, "S3"),
        ]
        plan = build_plan(wants, cands, prefer="sellers", seller_fee=FEE)
        note = plan["resettled"]
        self.assertTrue(note, "пересборка не объяснена")
        self.assertGreater(note["saved"], 0)
        self.assertEqual(note["sellers_after"], 1)

    def test_pinned_choice_is_never_resettled(self):
        """«Беру здесь» — указание, а не совет."""
        wants = [Want(name="Card A", quantity=1), Want(name="Card B", quantity=2)]
        pricey = cand("Card A", 400, 1, "S1")
        cands = [
            pricey,
            cand("Card A", 50, 1, "S2"),
            cand("Card B", 100, 2, "S2"),
        ]
        plan = build_plan(wants, cands, prefer="sellers", seller_fee=FEE,
                          pins={"Card A": pricey.offer.key})
        sellers = {lot["seller_name"] for lot in plan["lots"]}
        self.assertIn("S1", sellers)
        self.assertEqual(plan["ignored_pins"], [])

    def test_price_strategy_is_untouched(self):
        """«Минимальная цена за карту» не знает платы за продавца вовсе."""
        wants = [Want(name="Card A", quantity=1), Want(name="Card B", quantity=1)]
        cands = [
            cand("Card A", 50, 1, "S1"),
            cand("Card B", 900, 1, "S1"),
            cand("Card A", 60, 1, "S2"),
            cand("Card B", 100, 1, "S2"),
        ]
        plan = build_plan(wants, cands, prefer="price", seller_fee=FEE)
        self.assertEqual(plan["total"], 150)
        self.assertIsNone(plan["resettled"])


class TestAgainstBruteForce(unittest.TestCase):
    """Общая проверка: на маленьких раскладах план близок к точному минимуму."""

    def cases(self, rng, how_many):
        for _ in range(how_many):
            cards = ["Card A", "Card B", "Card C"][:rng.randint(2, 3)]
            wants = [Want(name=c, quantity=rng.randint(1, 3)) for c in cards]
            cands = []
            for s in ["S%d" % i for i in range(1, rng.randint(3, 4) + 1)]:
                for card in cards:
                    if rng.random() < 0.72:
                        cands.append(cand(
                            card,
                            rng.choice([70, 90, 110, 140, 180, 220, 300]),
                            rng.randint(1, 4), s))
            yield wants, cands

    def test_rarely_worse_and_never_much(self):
        rng = random.Random(20261015)
        checked = worse = 0
        overpaid = 0
        for wants, cands in self.cases(rng, 400):
            ideal = brute_force(wants, cands)
            if ideal is None:
                continue
            plan = build_plan(wants, cands, prefer="sellers", seller_fee=FEE)
            if sum(u["still_missing"] for u in plan["unfilled"]):
                continue
            checked += 1
            mine = plan_cost(plan)
            self.assertGreaterEqual(mine, ideal, "план дешевле точного минимума")
            if mine > ideal:
                worse += 1
                overpaid = max(overpaid, mine - ideal)
        self.assertGreater(checked, 300, "раскладов для сверки слишком мало")
        # До починки было 72 из 1331 (5.4%). Порог держим с запасом: он ловит
        # возврат жадности, но не падает от одного неудачного расклада.
        self.assertLess(worse / checked, 0.02,
                        "планов дороже идеала: %d из %d" % (worse, checked))
        self.assertLess(overpaid, 200, "худшая переплата: %d" % overpaid)


if __name__ == "__main__":
    unittest.main()
