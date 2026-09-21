"""Объявление без цены не должно выглядеть бесплатным.

Ноль в цене значит «topdeck не дал числа», а не «даром». Как обычное число он
выигрывает любое сравнение «дешевле»: план уносит карту к продавцу, про чью
цену мы ничего не знаем, и показывает её нулём — а в списке альтернатив она
стоит первой, будто это лучшая находка. Это тот же род ошибки, что и
недоверенная цена: неизвестное не должно притворяться выгодным.

Поэтому цена для сортировки и цена для показа — разные вещи, и здесь
проверяется именно это.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.hunt import Candidate, Want, build_plan  # noqa: E402
from app.lineparse import ParsedLine  # noqa: E402
from app.topdeck import Offer, Seller  # noqa: E402


def cand(seller, price, qty=4, name="Lightning Bolt", kind="user",
         certainty="exact"):
    """Как в tests/test_plan.py: та же форма объявления, другая цена."""
    s = Seller(name=seller, kind=kind, id=seller, refs=10, city="Москва")
    o = Offer(
        name=name, eng_name=name, rus_name="", qty=qty, cost=price, seller=s,
        source="topdeck" if kind == "user" else seller, url="", stamp="",
        line="%d %s (NM)" % (qty, name),
    )
    c = Candidate(offer=o, parsed=ParsedLine(set_code="m10"), want=name)
    c.certainty = certainty
    return c


class TestPriceRank(unittest.TestCase):
    def test_a_known_price_ranks_as_itself(self):
        self.assertEqual(cand("a", 145).price_rank, 145)

    def test_no_price_ranks_last_not_first(self):
        unknown = cand("a", 0)
        self.assertGreater(unknown.price_rank, cand("b", 100000).price_rank)
        # А для показа цена остаётся тем, что она есть -- нулём.
        self.assertEqual(unknown.unit_price, 0)


class TestThePlanDoesNotChaseAZero(unittest.TestCase):
    def test_a_priceless_listing_does_not_win_on_price(self):
        wants = [Want(name="Lightning Bolt", quantity=4)]
        plan = build_plan(
            wants, [cand("no-price", 0), cand("known", 145)], prefer="price")
        sellers = [lot["seller_name"] for lot in plan["lots"]]
        self.assertEqual(sellers, ["known"])
        self.assertEqual(plan["total"], 4 * 145)

    def test_it_is_still_used_when_there_is_nothing_else(self):
        """Объявление без цены -- не мусор: если больше никто не продаёт,
        карту всё равно надо где-то взять, просто честно и последней."""
        wants = [Want(name="Lightning Bolt", quantity=4)]
        plan = build_plan(wants, [cand("no-price", 0)], prefer="price")
        self.assertEqual([lot["seller_name"] for lot in plan["lots"]], ["no-price"])
        self.assertEqual(plan["lots"][0]["items"][0]["unit_price"], 0)

    def test_the_improvement_pass_does_not_move_cards_to_a_zero(self):
        """Проход улучшения ищет дешевле, а ноль дешевле всего на свете.

        Расстановка нарочная: «both» уже в плане из-за Sol Ring и продаёт
        болты без цены, «known» продаёт их за 145. Без правила про неизвестную
        цену проход улучшения перенёс бы болты к «both» -- «сэкономив» 145
        рублей на числе, которого не существует.
        """
        wants = [
            Want(name="Lightning Bolt", quantity=4),
            Want(name="Sol Ring", quantity=1),
        ]
        candidates = [
            cand("both", 500, qty=1, name="Sol Ring"),
            cand("both", 0, qty=4, name="Lightning Bolt"),
            cand("known", 145, qty=4, name="Lightning Bolt"),
        ]
        plan = build_plan(wants, candidates, prefer="price")
        bolts = [item for lot in plan["lots"] for item in lot["items"]
                 if item["want"] == "Lightning Bolt"]
        self.assertTrue(bolts)
        for item in bolts:
            self.assertEqual(item["unit_price"], 145, "болты ушли к нулевой цене")
        self.assertNotIn("saved", [m.get("why") for m in plan.get("moves", [])])

    def test_a_seller_without_a_price_does_not_win_on_postage(self):
        """Карта без цены не дешёвая -- она неизвестная.

        Раньше продавец, закрывавший две карты вместо одной, забирал по правилу
        «меньше продавцов» и свои четыре болта без цены. Теперь у продавца есть
        своя стоимость -- пересылка, -- и неизвестное в неё не укладывается:
        болты берутся там, где цена написана.
        """
        wants = [
            Want(name="Lightning Bolt", quantity=4),
            Want(name="Sol Ring", quantity=1),
        ]
        plan = build_plan(wants, [
            cand("both", 500, qty=1, name="Sol Ring"),
            cand("both", 0, qty=4, name="Lightning Bolt"),
            cand("known", 145, qty=4, name="Lightning Bolt"),
        ], prefer="sellers")
        bolts = [item for lot in plan["lots"] for item in lot["items"]
                 if item["want"] == "Lightning Bolt"]
        self.assertTrue(bolts)
        for item in bolts:
            self.assertEqual(item["unit_price"], 145, "болты ушли к нулевой цене")

    def test_the_alternatives_list_puts_the_unknown_price_last(self):
        wants = [Want(name="Lightning Bolt", quantity=1)]
        plan = build_plan(
            wants,
            [cand("no-price", 0), cand("cheap", 100), cand("dear", 900)],
            prefer="price")
        rows = plan["alternatives"]["Lightning Bolt"]
        self.assertEqual([r["seller_name"] for r in rows],
                         ["cheap", "dear", "no-price"])
        self.assertEqual(rows[-1]["price"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
