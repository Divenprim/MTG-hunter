"""Что покупать первым, когда колод несколько.

Главное, что проверяется, -- порядок. Список покупок, в котором карта для
трёх колод стоит вперемешку с картой для одной, отвечает на вопрос «чего
нет», а не на вопрос «с чего начать»; а начинают именно с того, что двигает
больше всего за те же деньги.

Второе -- честность счёта. Карты, занятые собранной колодой, в запас не
идут: они лежат в ней. Складывать их в общий котёл значит обещать человеку,
что у него есть то, чего он не может взять, не разобрав собранное.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import shopping                                   # noqa: E402


class FakeStore:
    """Колоды как их отдаёт DeckStore -- без базы."""

    def __init__(self, decks):
        self._decks = decks

    def list_decks(self):
        return [{"id": d["id"], "name": d["name"],
                 "format": d.get("format", "modern"),
                 "assembled": d.get("assembled", False)}
                for d in self._decks]

    def get_deck(self, deck_id):
        for d in self._decks:
            if d["id"] == deck_id:
                rows = [{"name": name, "quantity": qty, "section": "main"}
                        for name, qty in d["cards"].items()]
                rows += [{"name": name, "quantity": qty, "section": "side"}
                         for name, qty in (d.get("side") or {}).items()]
                return {"cards": rows}
        raise KeyError(deck_id)


def store_of(*decks):
    return FakeStore(list(decks))


def deck(deck_id, name, cards, assembled=False, fmt="modern", side=None):
    return {"id": deck_id, "name": name, "cards": cards,
            "assembled": assembled, "format": fmt, "side": side or {}}


PRICES = {
    "lightning bolt": {"rub_min": 100},
    "thoughtseize": {"rub_min": 900},
    "fatal push": {"rub_min": 150},
    "ponder": {"rub_min": 50},
}


class TestOrder(unittest.TestCase):

    def test_a_card_three_decks_want_comes_before_one_deck_wants(self):
        store = store_of(
            deck("a", "Первая", {"Lightning Bolt": 4}),
            deck("b", "Вторая", {"Lightning Bolt": 4}),
            deck("c", "Третья", {"Lightning Bolt": 4, "Ponder": 4}),
        )
        out = shopping.plan(store, {}, prices=PRICES)
        names = [c["name"] for c in out["cards"]]
        self.assertEqual(names[0], "Lightning Bolt")
        row = out["cards"][0]
        self.assertEqual(row["decks"], 3)
        self.assertEqual(row["lack"], 12, "12 копий, чтобы собрать все три")

    def test_what_finishes_a_deck_comes_first_of_all(self):
        """Колоде не хватает одной карты -- это не «приближает», а достраивает."""
        store = store_of(
            # Этой не хватает только Ponder.
            deck("a", "Почти готова", {"Ponder": 1}),
            # А этой -- Bolt, и он нужен ещё двум.
            deck("b", "Вторая", {"Lightning Bolt": 4, "Fatal Push": 4}),
            deck("c", "Третья", {"Lightning Bolt": 4, "Fatal Push": 4}),
        )
        out = shopping.plan(store, {}, prices=PRICES)
        self.assertEqual(out["cards"][0]["name"], "Ponder")
        self.assertEqual(out["cards"][0]["finishes"], ["Почти готова"])

    def test_cheaper_wins_when_everything_else_is_equal(self):
        store = store_of(
            deck("a", "Первая", {"Thoughtseize": 4, "Fatal Push": 4}),
            deck("b", "Вторая", {"Thoughtseize": 4, "Fatal Push": 4}),
        )
        out = shopping.plan(store, {}, prices=PRICES)
        self.assertEqual([c["name"] for c in out["cards"]],
                         ["Fatal Push", "Thoughtseize"])

    def test_unknown_price_is_not_free(self):
        """Карта без цены не должна всплывать как «дешёвая»."""
        store = store_of(
            deck("a", "Первая", {"Fatal Push": 1, "Карта без цены": 1}),
        )
        out = shopping.plan(store, {}, prices=PRICES)
        self.assertEqual([c["name"] for c in out["cards"]],
                         ["Fatal Push", "Карта без цены"])
        self.assertEqual(out["totals"]["no_price"], 1)


class TestHonestCount(unittest.TestCase):

    def test_cards_in_an_assembled_deck_are_not_available(self):
        """Четыре Молнии в собранном Бёрне для других колод не существуют."""
        store = store_of(
            deck("a", "Собранная", {"Lightning Bolt": 4}, assembled=True),
            deck("b", "На бумаге", {"Lightning Bolt": 4}),
        )
        out = shopping.plan(store, {"Lightning Bolt": 4}, prices=PRICES)
        self.assertEqual(len(out["cards"]), 1)
        row = out["cards"][0]
        self.assertEqual(row["lack"], 4)
        self.assertEqual(row["owned"], 4)
        self.assertEqual(row["free"], 0)
        self.assertEqual(row["decks"], 1, "собранная колода в счёт не идёт")

    def test_what_we_already_have_is_subtracted(self):
        store = store_of(deck("a", "Первая", {"Lightning Bolt": 4}))
        out = shopping.plan(store, {"Lightning Bolt": 3}, prices=PRICES)
        self.assertEqual(out["cards"][0]["lack"], 1)
        self.assertEqual(out["totals"]["rub"], 100)

    def test_a_deck_we_can_build_is_not_in_the_list(self):
        store = store_of(deck("a", "Готова", {"Lightning Bolt": 4}))
        out = shopping.plan(store, {"Lightning Bolt": 4}, prices=PRICES)
        self.assertEqual(out["cards"], [])
        self.assertEqual(out["totals"]["decks_short"], 0)

    def test_assembled_decks_can_be_counted_on_purpose(self):
        store = store_of(
            deck("a", "Собранная", {"Lightning Bolt": 4}, assembled=True))
        out = shopping.plan(store, {"Lightning Bolt": 1}, prices=PRICES,
                            include_assembled=True)
        self.assertEqual(out["cards"][0]["lack"], 3)

    def test_the_same_name_written_differently_is_one_card(self):
        """«Tiamat's» и «Tiamat’s» -- одна карта, а не две строки."""
        store = store_of(
            deck("a", "Первая", {"Tiamat's Fury": 1}),
            deck("b", "Вторая", {"Tiamat’s Fury": 1}),
        )
        out = shopping.plan(store, {}, prices={})
        self.assertEqual(len(out["cards"]), 1)
        self.assertEqual(out["cards"][0]["decks"], 2)


class TestTotals(unittest.TestCase):

    def test_totals_add_up(self):
        store = store_of(
            deck("a", "Первая", {"Lightning Bolt": 4, "Ponder": 2}),
            deck("b", "Вторая", {"Lightning Bolt": 4}),
        )
        out = shopping.plan(store, {}, prices=PRICES)
        self.assertEqual(out["totals"]["cards"], 2)
        self.assertEqual(out["totals"]["copies"], 10)
        self.assertEqual(out["totals"]["rub"], 8 * 100 + 2 * 50)
        self.assertEqual(out["totals"]["multi_deck"], 1)
        self.assertEqual(out["totals"]["decks"], 2)

    def test_each_deck_says_how_many_it_lacks_and_how_many_it_wants(self):
        store = store_of(
            deck("a", "Первая", {"Lightning Bolt": 4}),
            deck("b", "Вторая", {"Lightning Bolt": 2}),
        )
        out = shopping.plan(store, {}, prices=PRICES)
        needs = {n["deck"]: n for n in out["cards"][0]["needs"]}
        self.assertEqual(needs["Первая"]["lack"], 4)
        self.assertEqual(needs["Вторая"]["need"], 2)


class TestSpare(unittest.TestCase):
    """Что лежит сверх всех нужд -- пара к списку покупок."""

    def test_extra_copies_are_spare(self):
        store = store_of(deck("a", "Первая", {"Lightning Bolt": 4}))
        out = shopping.spare(store, {"Lightning Bolt": 7}, prices=PRICES)
        self.assertEqual(len(out["cards"]), 1)
        row = out["cards"][0]
        self.assertEqual(row["spare"], 3)
        self.assertEqual(row["needed"], 4)
        self.assertEqual(row["worth"], 300)
        self.assertTrue(row["in_decks"])

    def test_all_decks_count_even_assembled_ones(self):
        """Карта, занятая собранной колодой, не лишняя."""
        store = store_of(
            deck("a", "Собранная", {"Lightning Bolt": 4}, assembled=True),
            deck("b", "На бумаге", {"Lightning Bolt": 4}),
        )
        out = shopping.spare(store, {"Lightning Bolt": 8}, prices=PRICES)
        self.assertEqual(out["cards"], [])

    def test_a_card_no_deck_wants_is_marked(self):
        store = store_of(deck("a", "Первая", {"Ponder": 1}))
        out = shopping.spare(store, {"Thoughtseize": 2}, prices=PRICES)
        row = out["cards"][0]
        self.assertEqual(row["name"], "Thoughtseize")
        self.assertFalse(row["in_decks"])
        self.assertEqual(out["totals"]["unused"], 1)

    def test_keeping_a_spare_copy(self):
        """Запас сверху: без него продаётся последняя копия стейпла."""
        store = store_of(deck("a", "Первая", {"Lightning Bolt": 4}))
        out = shopping.spare(store, {"Lightning Bolt": 6}, prices=PRICES,
                             keep=2)
        self.assertEqual(out["cards"], [])

    def test_basic_lands_are_not_for_sale(self):
        store = store_of(deck("a", "Первая", {"Lightning Bolt": 4}))
        out = shopping.spare(store, {"Forest": 40}, prices={})
        self.assertEqual(out["cards"], [])

    def test_the_most_valuable_comes_first(self):
        store = store_of(deck("a", "Первая", {}))
        out = shopping.spare(
            store, {"Lightning Bolt": 4, "Thoughtseize": 1}, prices=PRICES)
        self.assertEqual([c["name"] for c in out["cards"]],
                         ["Thoughtseize", "Lightning Bolt"])
        self.assertEqual(out["totals"]["rub"], 900 + 400)


class TestWhichPrice(unittest.TestCase):
    """Нижняя цена могла прийти от убитой копии -- это цена другой вещи."""

    PRICES = {
        "lightning bolt": {"rub_min": 60, "rub_plain": 100},
        "thoughtseize": {"rub_min": 900},
    }

    def test_the_plain_price_rides_along(self):
        store = store_of(deck("a", "Первая", {"Lightning Bolt": 4}))
        row = shopping.plan(store, {}, prices=self.PRICES)["cards"][0]
        self.assertEqual(row["price"], 60)
        self.assertEqual(row["price_plain"], 100)

    def test_an_unknown_plain_price_is_zero_not_the_floor(self):
        store = store_of(deck("a", "Первая", {"Thoughtseize": 4}))
        row = shopping.plan(store, {}, prices=self.PRICES)["cards"][0]
        self.assertEqual(row["price_plain"], 0)

    def test_the_sum_is_still_counted_by_the_floor(self):
        """Потрёпанную тоже покупают -- врать в сумму незачем."""
        store = store_of(deck("a", "Первая", {"Lightning Bolt": 4}))
        out = shopping.plan(store, {}, prices=self.PRICES)
        self.assertEqual(out["totals"]["rub"], 60 * 4)


class TestSideboard(unittest.TestCase):
    """Сайдборд считается, но отдельной строкой: это покупка другой срочности."""

    def test_a_side_only_card_is_marked_and_stands_lower(self):
        store = store_of(deck("a", "Первая", {"Lightning Bolt": 4},
                              side={"Fatal Push": 2}))
        out = shopping.plan(store, {}, prices=PRICES)
        rows = {c["name"]: c for c in out["cards"]}
        self.assertTrue(rows["Fatal Push"]["side_only"])
        self.assertEqual(rows["Fatal Push"]["side"], 2)
        self.assertFalse(rows["Lightning Bolt"]["side_only"])
        names = [c["name"] for c in out["cards"]]
        self.assertLess(names.index("Lightning Bolt"), names.index("Fatal Push"))

    def test_one_card_in_both_sections_counts_once_and_says_how_many(self):
        store = store_of(deck("a", "Первая", {"Lightning Bolt": 4},
                              side={"Lightning Bolt": 2}))
        out = shopping.plan(store, {}, prices=PRICES)
        row = out["cards"][0]
        self.assertEqual(row["lack"], 6)
        self.assertEqual(row["side"], 2)
        self.assertFalse(row["side_only"])

    def test_without_sideboards_the_side_copies_drop_out(self):
        store = store_of(deck("a", "Первая", {"Lightning Bolt": 4},
                              side={"Lightning Bolt": 2, "Fatal Push": 3}))
        out = shopping.plan(store, {}, prices=PRICES, skip_side=True)
        rows = {c["name"]: c for c in out["cards"]}
        self.assertEqual(rows["Lightning Bolt"]["lack"], 4)
        self.assertNotIn("Fatal Push", rows)
        self.assertEqual(out["totals"]["side_copies"], 0)

    def test_the_mainboard_is_served_first_when_copies_are_short(self):
        """Не хватает на обе секции -- без карты остаётся сайд, не мейн."""
        store = store_of(deck("a", "Первая", {"Lightning Bolt": 4},
                              side={"Lightning Bolt": 2}))
        out = shopping.plan(store, {"Lightning Bolt": 5}, prices=PRICES)
        row = out["cards"][0]
        self.assertEqual(row["lack"], 1)
        self.assertEqual(row["side"], 1)

    def test_the_total_says_how_much_goes_to_sideboards(self):
        store = store_of(deck("a", "Первая", {"Lightning Bolt": 4},
                              side={"Fatal Push": 2}))
        out = shopping.plan(store, {}, prices=PRICES)
        self.assertEqual(out["totals"]["side_copies"], 2)
        self.assertEqual(out["totals"]["side_only"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
