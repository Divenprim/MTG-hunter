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

    def test_a_longer_name_is_not_our_card(self):
        """«Burgeoning» -- не «March of Burgeoning Life».

        Отбраковщик это ловит и говорит прямым текстом «в строке продавца
        другая карта». А добор читал у него поле `rejected`, которого в
        ответе нет, -- и мусор проходил насквозь. На девяти настоящих
        складах из девяти «находок дешевле рынка» настоящей была одна:
        «Burgeoning» за 22 ₽ оказывался March of Burgeoning Life при рынке
        от 2074 ₽, «Darkness» за 10 ₽ -- Grasp of Darkness.
        """
        # Сообщение продавца ищется по тому же признаку, что и на живой
        # странице: иначе проверка молча меряет пустоту.
        html = (
            "<div class='ipsType_richText'>"
            "1 March of Burgeoning Life (#201) [eng] - 22 руб.<br>"
            "10 Grasp of Darkness (M21 #102 RU) 10р<br>"
            "1 Scion of Darkness 39<br>"
            "2 Burgeoning (TMP eng nm) 3600"
            "</div><div class='ipsItemControls'></div>"
        )
        lines = stock.stock_lines(html)
        self.assertEqual(len(lines), 4,
                         "сперва убеждаемся, что строки вообще разобрались")
        # Пятой строкой сюда попадал обрывок `<div class="`: признак конца
        # сообщения лежит внутри тега, и его начало оставалось в куске. На
        # девяти живых темах -- по одной такой строке в каждой.
        self.assertFalse([ln for ln in lines if ln.startswith("<")],
                         "обрывки тегов -- не объявления")
        found = stock.find_wanted(html, ["Burgeoning", "Darkness"], DB)
        self.assertEqual([r["want"] for r in found], ["Burgeoning"],
                         "чужие карты с нашим словом внутри имени не наши")
        self.assertEqual(found[0]["price"], 3600)


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

    def test_below_everything_we_have_seen(self):
        """Настоящая находка -- дешевле самого дешёвого известного нам."""
        rows = [{"want": "Sol Ring", "line": "a", "price": 90, "quantity": 1}]
        out = stock.against_market(
            rows, {"sol ring": {"rub_min": 120, "rub_median": 150}})
        self.assertEqual(out[0]["verdict"], "below-floor")
        self.assertEqual(out[0]["cheaper_by"], 25)
        self.assertEqual(out[0]["market_min"], 120)

    def test_inside_the_range_is_not_a_find(self):
        """Между минимумом и медианой -- обычная цена, а не находка."""
        rows = [{"want": "Sol Ring", "line": "a", "price": 130, "quantity": 1}]
        out = stock.against_market(
            rows, {"sol ring": {"rub_min": 120, "rub_median": 150}})
        self.assertEqual(out[0]["verdict"], "in-range")
        self.assertIsNone(out[0]["cheaper_by"])

    def test_above_the_market_says_so(self):
        rows = [{"want": "Sol Ring", "line": "a", "price": 300, "quantity": 1}]
        out = stock.against_market(
            rows, {"sol ring": {"rub_min": 120, "rub_median": 150}})
        self.assertEqual(out[0]["verdict"], "above")
        self.assertLess(out[0]["cheaper_by"], 0)

    def test_foil_is_not_compared_at_all(self):
        """Фойл против цены «по имени» -- это и была та самая ложь.

        Кеш цен сведён по имени карты, без фойла и печати. Обычная за 10
        против фойлы за 4000 давала «экономию 3990».
        """
        rows = [{"want": "Chalice of the Void", "line": "1 Chalice MPS Foil 16000",
                 "price": 16000, "quantity": 1, "foil": True}]
        out = stock.against_market(
            rows, {"chalice of the void": {"rub_min": 4000, "rub_median": 5000}})
        self.assertEqual(out[0]["verdict"], "incomparable")
        self.assertIsNone(out[0]["cheaper_by"])
        self.assertIn("фойл", out[0]["why"])

    def test_wide_spread_is_not_compared(self):
        """Если под именем цены отличаются втрое -- там разные вещи."""
        rows = [{"want": "Swords to Plowshares", "line": "a", "price": 15,
                 "quantity": 1}]
        out = stock.against_market(
            rows,
            {"swords to plowshares": {"rub_min": 10, "rub_median": 400}})
        self.assertEqual(out[0]["verdict"], "incomparable")
        self.assertIsNone(out[0]["cheaper_by"])

    def test_special_condition_is_not_compared(self):
        rows = [{"want": "Sol Ring", "line": "a", "price": 40, "quantity": 1,
                 "condition": "HP"}]
        out = stock.against_market(
            rows, {"sol ring": {"rub_min": 120, "rub_median": 150}})
        self.assertEqual(out[0]["verdict"], "incomparable")
        self.assertIn("HP", out[0]["why"])

    def test_unknown_market_is_not_a_discount(self):
        """Неизвестная цена -- это «не знаем», а не «даром»."""
        rows = [{"want": "Sol Ring", "line": "a", "price": 120, "quantity": 1}]
        out = stock.against_market(rows, {})
        self.assertIsNone(out[0]["cheaper_by"])
        self.assertIsNone(out[0]["median"])
        self.assertEqual(out[0]["verdict"], "unknown")

    def test_finds_come_first_and_overpriced_last(self):
        rows = [
            {"want": "Дорогая", "line": "a", "price": 300, "quantity": 1},
            {"want": "Находка", "line": "b", "price": 50, "quantity": 1},
            {"want": "В рынке", "line": "c", "price": 130, "quantity": 1},
        ]
        market = {
            "дорогая": {"rub_min": 120, "rub_median": 150},
            "находка": {"rub_min": 120, "rub_median": 150},
            "в рынке": {"rub_min": 120, "rub_median": 150},
        }
        out = stock.against_market(rows, market)
        self.assertEqual([r["want"] for r in out],
                         ["Находка", "В рынке", "Дорогая"])


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


class TestAgainstTheSameVersion(unittest.TestCase):
    """Фойл сравнивается с фойлом, убитая копия -- с убитой.

    Это ответ на главную претензию к прежней мерке: цена в кеше была одна
    на имя, и «обычная за 10 против фойлы за 4000» выдавалась за экономию
    3990. Теперь цены пишутся по версиям, и сравнивать есть с чем.
    """

    VARIANTS = {
        "thoughtseize": [
            {"set_code": "mm3", "foil": 1, "condition": "NM",
             "rub_min": 4200, "rub_max": 4500, "offers": 2},
            {"set_code": "ths", "foil": 0, "condition": "MP",
             "rub_min": 700, "rub_max": 800, "offers": 2},
            {"set_code": "2xm", "foil": 0, "condition": "NM",
             "rub_min": 1100, "rub_max": 1400, "offers": 5},
        ]
    }
    PRICES = {"thoughtseize": {"rub_min": 700, "rub_median": 1100, "offers": 9}}

    def look(self, **row):
        base = {"want": "Thoughtseize", "line": "x", "quantity": 1}
        base.update(row)
        return stock.against_market([base], self.PRICES, self.VARIANTS)[0]

    def test_a_cheap_foil_is_measured_against_foils(self):
        got = self.look(price=2500, foil=True, set_code="mm3", condition="NM")
        self.assertEqual(got["basis"], "version")
        self.assertEqual(got["verdict"], "below-floor")
        self.assertEqual(got["market_min"], 4200)
        self.assertIn("фойл", got["version"])

    def test_a_plain_copy_is_not_measured_against_a_foil(self):
        got = self.look(price=950, foil=False, set_code="2xm", condition="NM")
        self.assertEqual(got["market_min"], 1100)
        self.assertNotIn("фойл", got["version"])

    def test_a_worn_copy_is_measured_against_worn_ones(self):
        got = self.look(price=750, foil=False, set_code="ths", condition="MP")
        self.assertEqual(got["basis"], "version")
        self.assertEqual(got["verdict"], "in-range")

    def test_an_unknown_printing_falls_back_to_the_same_kind(self):
        """Набора нет в наших ценах -- сравниваем с обычными, а не бросаем."""
        got = self.look(price=900, foil=False, set_code="zzz", condition="NM")
        self.assertEqual(got["basis"], "version")
        self.assertEqual(got["market_min"], 1100)

    def test_without_recorded_versions_the_old_refusal_stands(self):
        rows = [{"want": "Thoughtseize", "line": "x", "price": 2500,
                 "quantity": 1, "foil": True}]
        got = stock.against_market(rows, self.PRICES, {})[0]
        self.assertEqual(got["basis"], "name")
        self.assertEqual(got["verdict"], "incomparable")

    def test_above_the_recorded_spread_is_dearer(self):
        got = self.look(price=2000, foil=False, set_code="2xm", condition="NM")
        self.assertEqual(got["verdict"], "above")
        self.assertLess(got["cheaper_by"], 0)

    def test_picking_a_version_needs_a_price(self):
        self.assertIsNone(stock.pick_variant(
            {"foil": False, "condition": "NM"},
            [{"set_code": "x", "foil": 0, "condition": "NM", "rub_min": None}]))
