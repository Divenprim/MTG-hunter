"""План покупки не должен говорить человеку неправду.

Шесть мест, где он её говорил. Все найдены второй ревизией и воспроизведены
прежде, чем чинились:

* одно объявление, пришедшее в ответе дважды, покупалось дважды: из строки на
  три копии план брал четыре и писал «всё закрыто»;
* закрепление «беру здесь» на отсеянном объявлении отменялось молча, а в
  ответе значилось выполненным -- человек видел замок на своём выборе и
  другую цену в плане;
* неизвестная цена шла в «Итого» нулём: «итого 0 ₽» за две карты;
* цена, написанная продавцом в строке, не использовалась, если topdeck своей
  не дал, -- карта уезжала в «цена неизвестна» при известной цене;
* `qty_check` при нуле от topdeck отбрасывал строку, в которой сам же
  прочитал «4 ×»;
* два желания с одним именем схлопывались, и план покупал меньше, чем
  просили, не сказав об этом.

Наружу отсюда не уходит ни одного запроса: клиент topdeck подменён.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.cards import DB_PATH, CardDB                     # noqa: E402
from app.hunt import Candidate, Hunter, Want, build_plan  # noqa: E402
from app.lineparse import ParsedLine, SetIndex            # noqa: E402
from app.offermatch import qty_check                      # noqa: E402
from app.topdeck import Offer, Seller                     # noqa: E402


def offer(name, seller, qty, cost, line=None):
    who = Seller(name=seller, kind="user", id=seller, city="Москва", refs=20)
    return Offer(name=name, eng_name=name, rus_name="", qty=qty, cost=cost,
                 seller=who, source="topdeck", url="http://example.invalid",
                 stamp="2026-10-14",
                 line=line or ("%d %s %d" % (qty, name, cost)), city="Москва")


def cand(name, seller, qty, cost, certainty="exact", line=None):
    c = Candidate(offer=offer(name, seller, qty, cost, line),
                  parsed=ParsedLine(), want=name)
    c.certainty = certainty
    return c


class Duplicates(unittest.TestCase):
    """Одно объявление в ответе дважды -- это одно объявление."""

    class Twice:
        """Отдаёт каждую строку дважды: так и приходит в жизни.

        Двусторонние карты мы нарочно спрашиваем обоими именами, и строка
        продавца, где есть оба, возвращается в двух ответах.
        """

        def search(self, names):
            out = []
            for name in names:
                o = offer(name, "ПРОВЕРКА-Один", 3, 10)
                out.append(o)
                out.append(offer(name, "ПРОВЕРКА-Один", 3, 10))
            return out

    @unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
    def test_the_same_listing_is_gathered_once(self):
        hunter = Hunter(CardDB(), client=self.Twice(), set_index=SetIndex.load())
        got = hunter.gather([Want(name="Fog", quantity=4)])
        keys = [c.offer.key for c in got]
        self.assertEqual(len(keys), len(set(keys)),
                         "одно объявление попало в кандидаты дважды")

    def test_a_doubled_listing_is_not_sold_twice(self):
        """Из строки на три копии нельзя взять четыре."""
        a = cand("Fog", "userA", 3, 10)
        b = cand("Fog", "userA", 3, 10)
        self.assertEqual(a.offer.key, b.offer.key, "ключи дублей должны совпасть")
        plan = build_plan([Want(name="Fog", quantity=4)], [a, b], prefer="price")
        taken = sum(i["quantity"] for lot in plan["lots"] for i in lot["items"])
        self.assertLessEqual(taken, 3, "продали больше, чем есть у продавца")
        self.assertTrue(plan["unfilled"], "недостачу надо назвать вслух")


class Pins(unittest.TestCase):

    def test_a_pin_that_could_not_be_applied_is_named(self):
        cheap = cand("Fog", "userA", 2, 20)
        cheap.rejected = "модель не узнала карту"
        dear = cand("Fog", "shopB", 2, 300)
        plan = build_plan([Want(name="Fog", quantity=2)], [cheap, dear],
                          prefer="price", pins={"Fog": cheap.offer.key})
        self.assertEqual(plan["pins"], {},
                         "в pins попало закрепление, которое не применилось")
        self.assertEqual(len(plan["ignored_pins"]), 1)
        said = plan["ignored_pins"][0]
        self.assertEqual(said["want"], "Fog")
        self.assertEqual(said["offer_key"], cheap.offer.key)
        self.assertIn("не узнала", said["why"])

    def test_a_pin_that_worked_stays_in_pins(self):
        mine = cand("Fog", "userA", 2, 20)
        other = cand("Fog", "shopB", 2, 300)
        plan = build_plan([Want(name="Fog", quantity=2)], [mine, other],
                          prefer="price", pins={"Fog": mine.offer.key})
        self.assertEqual(plan["pins"], {"Fog": mine.offer.key})
        self.assertEqual(plan["ignored_pins"], [])

    def test_a_pin_on_an_offer_that_is_gone_says_so(self):
        only = cand("Fog", "userA", 2, 20)
        plan = build_plan([Want(name="Fog", quantity=2)], [only],
                          prefer="price", pins={"Fog": "нет-такого-ключа"})
        self.assertEqual(len(plan["ignored_pins"]), 1)
        self.assertIn("больше не в выдаче", plan["ignored_pins"][0]["why"])


class UnknownPrice(unittest.TestCase):

    def test_an_unpriced_item_is_named_not_counted_as_zero(self):
        free = cand("Fog", "userA", 2, 0)
        plan = build_plan([Want(name="Fog", quantity=2)], [free], prefer="price")
        self.assertEqual(plan["unpriced_copies"], 2)
        self.assertEqual(plan["unpriced"][0]["want"], "Fog")
        self.assertEqual(plan["unpriced"][0]["seller"], "userA")

    def test_a_fully_priced_plan_says_nothing_about_unknown_prices(self):
        known = cand("Fog", "userA", 2, 40)
        plan = build_plan([Want(name="Fog", quantity=2)], [known], prefer="price")
        self.assertEqual(plan["unpriced"], [])
        self.assertEqual(plan["unpriced_copies"], 0)
        self.assertEqual(plan["total"], 80)

    def test_the_price_written_by_the_seller_is_used(self):
        """topdeck числа не дал, продавец написал -- берём написанное."""
        c = cand("Fog", "userA", 2, 0, line="2 Fog NM 900 руб")
        c.price_in_line = 900
        self.assertEqual(c.unit_price, 900)
        self.assertEqual(c.price_rank, 900)
        self.assertTrue(c.priced)
        plan = build_plan([Want(name="Fog", quantity=2)], [c], prefer="price")
        self.assertEqual(plan["total"], 1800)
        self.assertEqual(plan["unpriced"], [])

    @unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
    def test_it_is_picked_up_on_the_way_in(self):
        """Не руками: разбор должен сам положить цену из строки."""

        class Silent:
            def search(self, names):
                return [offer(n, "ПРОВЕРКА-Один", 1, 0, "1 %s NM 900 руб" % n)
                        for n in names]

        hunter = Hunter(CardDB(), client=Silent(), set_index=SetIndex.load())
        got = hunter.gather([Want(name="Fog", quantity=1)])
        mine = [c for c in got if c.want.lower() == "fog"]
        self.assertTrue(mine, "кандидата не собрали вовсе")
        self.assertEqual(mine[0].price_in_line, 900)
        self.assertEqual(mine[0].unit_price, 900)


class QtyFromTheLine(unittest.TestCase):

    def test_zero_from_topdeck_is_not_an_empty_shelf(self):
        """Ноль -- это «не разобрал», а не «у продавца пусто»."""
        got = qty_check(0, "4 x Fog - RU - NM - 10")
        self.assertTrue(got["disputed"])
        self.assertEqual(got["qty"], 4)
        self.assertIn("не насчитал ни одной", got["reason"])

    def test_an_agreeing_pair_is_not_a_dispute(self):
        got = qty_check(4, "4 x Fog - RU - NM - 10")
        self.assertFalse(got["disputed"])
        self.assertEqual(got["qty"], 4)

    def test_nothing_written_means_nothing_to_argue_with(self):
        got = qty_check(0, "Fog - RU - NM - 10")
        self.assertFalse(got["disputed"])
        self.assertEqual(got["qty"], 0)

    def test_the_offer_survives_to_the_plan(self):
        c = cand("Fog", "userA", 0, 10, line="4 x Fog - RU - NM - 10")
        c.qty_in_line = 4
        c.qty_dispute = "topdeck не насчитал ни одной, а в строке продавца 4"
        self.assertEqual(c.stock, 4)
        plan = build_plan([Want(name="Fog", quantity=4)], [c], prefer="price")
        self.assertEqual(plan["unfilled"], [])
        self.assertEqual(plan["total"], 40)


class SameNameTwice(unittest.TestCase):

    def test_two_wants_for_one_card_add_up(self):
        one = cand("Fog", "userA", 9, 10)
        plan = build_plan([Want(name="Fog", quantity=2),
                           Want(name="FOG", quantity=3)], [one], prefer="price")
        taken = sum(i["quantity"] for lot in plan["lots"] for i in lot["items"])
        self.assertEqual(taken, 5)

    def test_what_cannot_be_covered_is_still_named(self):
        one = cand("Fog", "userA", 4, 10)
        plan = build_plan([Want(name="Fog", quantity=2),
                           Want(name="FOG", quantity=3)], [one], prefer="price")
        self.assertTrue(plan["unfilled"], "о недостаче надо сказать")
        self.assertEqual(plan["unfilled"][0]["still_missing"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
