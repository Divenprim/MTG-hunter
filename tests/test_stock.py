"""Склад продавца: что ещё у него есть из нашего списка.

Посылка стоит одинаково, одна в ней карта или двадцать. Продавец уже в плане
— значит добрать у него остальное бесплатно по доставке, и это самый большой
выигрыш, какой в охоте бывает. У частника на topdeck все объявления ведут на
одну ссылку — тему, где лежит весь его склад.

Проверяется то, на чём это ломается:

* **границы слов.** «Island» не должен ловить «Tropical Island», а «Forest» —
  «Misty Rainforest». На живом складе это сразу дало ложных находок больше,
  чем настоящих;
* **цена.** В теме она стоит где попало и без пометки «руб»: обычный разбор
  видел её у 1050 строк из 8898. Номер карты (`#235`, `№275`, `0278`) ценой
  считать нельзя — это старая ошибка, про которую написано в `lineparse`;
* **чужие карты.** `offermatch` отсеивает «Urban Burgeoning», когда ищем
  «Burgeoning»;
* **наружу не ходим.** Разбор работает с готовым HTML, запросов здесь нет
  ни одного.

Образец склада лежит в `tests/data/stock-topic.html` — кусок настоящей темы,
обезличенный: ссылки заменены, ника продавца в нём нет.
"""

import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import stock  # noqa: E402
from app.cards import CardDB  # noqa: E402

DB = CardDB()
SAMPLE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "data", "stock-topic.html")


def sample_html():
    with io.open(SAMPLE, encoding="utf-8") as fh:
        return fh.read()


class TestPrice(unittest.TestCase):
    """Цена в строке склада -- и ни разу не номер карты."""

    def test_price_in_the_middle_of_the_line(self):
        self.assertEqual(stock.price_of("4 Misty Rainforest 2800 zen rus"), 2800)

    def test_price_after_a_collector_number(self):
        self.assertEqual(
            stock.price_of("3 Breeding Pool (RVR №275 ENG NM) 950"), 950)

    def test_a_number_with_a_leading_zero_is_not_a_price(self):
        self.assertEqual(
            stock.price_of("1 Breeding Pool 1200 (EOE borderless 0278 eng nm)"),
            1200)

    def test_hash_number_is_not_a_price(self):
        self.assertEqual(
            stock.price_of("2 Chalice of the Void MPS#33 Foil 16000"), 16000)
        self.assertEqual(
            stock.price_of("1 Тиамат (Tiamat) #235/281 AFR RU 1300"), 1300)

    def test_quantity_is_not_a_price(self):
        """«4 Ash Barrens 40» -- сорок рублей, а не четыре."""
        self.assertEqual(stock.price_of("4 Ash Barrens 40"), 40)

    def test_no_price_at_all(self):
        self.assertIsNone(stock.price_of("Lightning Bolt"))


class TestWordBoundaries(unittest.TestCase):
    """Самая настоящая ловушка этого разбора."""

    def test_island_does_not_catch_tropical_island(self):
        found = stock.find_wanted(
            '<div class="ipsType_richText">1 Tropical Island 98000<br>'
            '</div><div class="ipsItemControls">',
            ["Island"], DB)
        self.assertEqual(found, [])

    def test_forest_does_not_catch_misty_rainforest(self):
        found = stock.find_wanted(
            '<div class="ipsType_richText">4 Misty Rainforest 2800<br>'
            '</div><div class="ipsItemControls">',
            ["Forest"], DB)
        self.assertEqual(found, [])

    def test_the_card_itself_is_found(self):
        found = stock.find_wanted(
            '<div class="ipsType_richText">4 Misty Rainforest 2800 zen rus<br>'
            '</div><div class="ipsItemControls">',
            ["Misty Rainforest"], DB)
        self.assertEqual(len(found), 1, found)
        self.assertEqual(found[0]["price"], 2800)
        self.assertEqual(found[0]["quantity"], 4)

    def test_basic_lands_are_not_looked_for_at_all(self):
        """Их не покупают поштучно, а ловят они пол-склада."""
        index = stock.wanted_index(["Forest", "Island", "Лес", "Sol Ring"])
        self.assertEqual(list(index), ["sol ring"])

    def test_short_names_are_skipped(self):
        self.assertEqual(stock.wanted_index(["Fog", "Opt"]), {})


class TestAgainstTheSample(unittest.TestCase):
    """На куске настоящего склада."""

    def setUp(self):
        self.html = sample_html()

    def test_lines_are_read(self):
        lines = stock.stock_lines(self.html)
        self.assertGreater(len(lines), 20, len(lines))

    def test_most_lines_have_a_price(self):
        lines = stock.stock_lines(self.html)
        priced = [ln for ln in lines if stock.price_of(ln)]
        self.assertGreater(len(priced) / max(1, len(lines)), 0.7,
                           "%d из %d" % (len(priced), len(lines)))

    def test_a_known_card_is_found_with_its_price(self):
        found = stock.find_wanted(self.html, ["Chalice of the Void"], DB)
        self.assertTrue(found, "карта из образца не нашлась")
        self.assertTrue(all(f["price"] for f in found), found)

    def test_nothing_is_invented(self):
        """Карты, которой в складе нет, и найтись не должно."""
        self.assertEqual(
            stock.find_wanted(self.html, ["Black Lotus"], DB), [])


class TestCheapestAndMarket(unittest.TestCase):
    def test_cheapest_copy_per_card_wins(self):
        rows = [
            {"want": "Sol Ring", "line": "a", "price": 300, "quantity": 1},
            {"want": "Sol Ring", "line": "b", "price": 120, "quantity": 4},
            {"want": "Sol Ring", "line": "c", "price": None, "quantity": 1},
        ]
        best = stock.cheapest_per_card(rows)
        self.assertEqual(len(best), 1)
        self.assertEqual(best[0]["price"], 120)

    def test_discount_against_the_median(self):
        rows = [{"want": "Sol Ring", "line": "a", "price": 120, "quantity": 1}]
        out = stock.against_market(rows, {"sol ring": {"rub_median": 240}})
        self.assertEqual(out[0]["cheaper_by"], 50)

    def test_unknown_market_is_not_a_discount(self):
        """Неизвестная медиана -- это «не знаем», а не «даром»."""
        rows = [{"want": "Sol Ring", "line": "a", "price": 120, "quantity": 1}]
        out = stock.against_market(rows, {})
        self.assertIsNone(out[0]["cheaper_by"])
        self.assertIsNone(out[0]["median"])

    def test_biggest_discount_comes_first(self):
        rows = [
            {"want": "A", "line": "a", "price": 90, "quantity": 1},
            {"want": "B", "line": "b", "price": 50, "quantity": 1},
        ]
        out = stock.against_market(rows, {"a": {"rub_median": 100},
                                          "b": {"rub_median": 200}})
        self.assertEqual([r["want"] for r in out], ["B", "A"])


if __name__ == "__main__":
    unittest.main()


class TestPriceAgainstSetCodes(unittest.TestCase):
    """Код набора с цифрами -- не цена.

    Поймано на девяти настоящих складах: «4 Negate 10 M20 RU NM» читалось как
    двадцать рублей вместо десяти, потому что M20 -- это набор. Коды у MTG
    почти всегда такие: M20, C21, 2XM, MH2, DDO-45.
    """

    def test_letters_before_the_number(self):
        self.assertEqual(stock.price_of("4 Negate 10 M20 RU NM"), 10)
        self.assertEqual(stock.price_of("4 Fog 15 C21 EN"), 15)

    def test_letters_after_the_number(self):
        self.assertEqual(
            stock.price_of("2 Thing in the Ice 350 2XM EN NM"), 350)

    def test_number_inside_a_collector_code(self):
        self.assertEqual(stock.price_of("2 Explore 25 PLST DDO-45"), 25)

    def test_kopecks_are_dropped_not_glued(self):
        """«30.4 руб.» -- тридцать рублей, а не триста четыре."""
        self.assertEqual(
            stock.price_of("1 Plains (#194) [eng]  - 30.4 руб."), 30)

    def test_thousands_separator_still_works(self):
        self.assertEqual(stock.price_of("1 Sol Ring 1.500 руб"), 1500)

    def test_dash_before_the_price_is_fine(self):
        self.assertEqual(stock.price_of("1 Fog - 25"), 25)
