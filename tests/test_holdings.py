"""Тесты учёта: что есть, что занято собранными колодами и что свободно.

Правило, ради которого всё это написано, одно: карты собранной колоды заняты.
Их нельзя одновременно положить в другую колоду, и значит для остальных колод
их нет. Колода «на бумаге» ничего не занимает -- к ней другой вопрос: хватит ли
свободных карт, чтобы её собрать.

Колоды здесь поддельные: проверяется счёт, а не хранилище.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import holdings  # noqa: E402


class FakeStore:
    """Хранилище колод ровно в том объёме, в каком его трогает учёт."""

    def __init__(self, decks):
        self._decks = decks

    def list_decks(self):
        return [{"id": d["id"], "name": d["name"], "format": d.get("format", "modern"),
                 "assembled": d.get("assembled", False)} for d in self._decks]

    def get_deck(self, deck_id):
        for deck in self._decks:
            if deck["id"] == deck_id:
                return {"cards": [
                    {"name": name, "quantity": qty, "section": section}
                    for name, qty, section in deck["cards"]]}
        raise KeyError(deck_id)


def deck(deck_id, name, cards, assembled=False, fmt="modern"):
    return {"id": deck_id, "name": name, "assembled": assembled, "format": fmt,
            "cards": [(n, q, s) for n, q, s in cards]}


BOLT = "Lightning Bolt"
RING = "Sol Ring"


class TestFreeAndCommitted(unittest.TestCase):
    def test_a_paper_deck_takes_nothing(self):
        store = FakeStore([deck("d1", "на бумаге", [(BOLT, 4, "main")])])
        out = holdings.report(store, {BOLT: 4})
        card = out["cards"][0]
        self.assertEqual((card["owned"], card["committed"], card["free"]), (4, 0, 4))

    def test_an_assembled_deck_takes_its_cards(self):
        store = FakeStore([deck("d1", "собрана", [(BOLT, 4, "main")], assembled=True)])
        out = holdings.report(store, {BOLT: 4})
        card = out["cards"][0]
        self.assertEqual((card["owned"], card["committed"], card["free"]), (4, 4, 0))

    def test_what_is_taken_is_gone_for_the_next_deck(self):
        """Главное правило: собранная колода забирает карты у остальных."""
        store = FakeStore([
            deck("d1", "собрана", [(BOLT, 4, "main")], assembled=True),
            deck("d2", "замысел", [(BOLT, 4, "main")]),
        ])
        out = holdings.report(store, {BOLT: 4})
        paper = next(d for d in out["decks"] if d["id"] == "d2")
        self.assertEqual(paper["missing"], 4)
        self.assertFalse(paper["ready"])

    def test_the_assembled_deck_itself_is_not_short(self):
        store = FakeStore([deck("d1", "собрана", [(BOLT, 4, "main")], assembled=True)])
        out = holdings.report(store, {BOLT: 4})
        self.assertTrue(out["decks"][0]["ready"])
        self.assertEqual(out["decks"][0]["missing"], 0)

    def test_the_maybeboard_is_a_wish_list_and_takes_nothing(self):
        store = FakeStore([deck("d1", "колода",
                                [(BOLT, 4, "main"), (RING, 1, "maybe")],
                                assembled=True)])
        out = holdings.report(store, {BOLT: 4})
        names = [c["name"] for c in out["cards"]]
        self.assertIn(BOLT, names)
        self.assertNotIn(RING, names)

    def test_the_sideboard_is_part_of_the_deck(self):
        store = FakeStore([deck("d1", "колода",
                                [(BOLT, 4, "main"), (RING, 2, "side")],
                                assembled=True)])
        out = holdings.report(store, {BOLT: 4, RING: 2})
        ring = next(c for c in out["cards"] if c["name"] == RING)
        self.assertEqual(ring["committed"], 2)


class TestWhereCardsAre(unittest.TestCase):
    def test_a_card_says_which_decks_it_is_in(self):
        store = FakeStore([
            deck("d1", "первая", [(BOLT, 2, "main")], assembled=True),
            deck("d2", "вторая", [(BOLT, 3, "main")]),
        ])
        out = holdings.report(store, {BOLT: 4})
        card = out["cards"][0]
        self.assertEqual({d["deck"] for d in card["decks"]}, {"первая", "вторая"})
        self.assertEqual(card["listed"], 5)
        self.assertTrue(next(d for d in card["decks"]
                             if d["deck"] == "первая")["assembled"])


class TestConflicts(unittest.TestCase):
    def test_two_assembled_decks_sharing_cards_are_reported(self):
        store = FakeStore([
            deck("d1", "первая", [(BOLT, 4, "main")], assembled=True),
            deck("d2", "вторая", [(BOLT, 4, "main")], assembled=True),
        ])
        out = holdings.report(store, {BOLT: 4})
        self.assertEqual(len(out["conflicts"]), 1)
        conflict = out["conflicts"][0]
        self.assertEqual(conflict["kind"], "shared")
        self.assertEqual((conflict["owned"], conflict["committed"]), (4, 8))

    def test_a_card_in_an_assembled_deck_but_not_owned_is_reported(self):
        store = FakeStore([deck("d1", "собрана", [(RING, 1, "main")], assembled=True)])
        out = holdings.report(store, {})
        self.assertEqual(out["conflicts"][0]["kind"], "missing")

    def test_nothing_is_reported_when_it_all_fits(self):
        store = FakeStore([deck("d1", "собрана", [(BOLT, 4, "main")], assembled=True)])
        self.assertEqual(holdings.report(store, {BOLT: 4})["conflicts"], [])


class TestMoneyAndTotals(unittest.TestCase):
    def test_missing_cards_are_priced(self):
        store = FakeStore([deck("d1", "замысел", [(BOLT, 4, "main")])])
        prices = {"lightning bolt": {"rub_min": 150}}
        out = holdings.report(store, {BOLT: 1}, prices=prices)
        self.assertEqual(out["decks"][0]["missing"], 3)
        self.assertEqual(out["decks"][0]["missing_rub"], 450)

    def test_totals_count_what_is_owned_apart_from_what_is_listed(self):
        store = FakeStore([deck("d1", "замысел", [(RING, 1, "main")])])
        out = holdings.report(store, {BOLT: 4})
        self.assertEqual(out["totals"]["copies"], 4)
        self.assertEqual(out["totals"]["cards"], 1)     # своих карт одна
        self.assertEqual(out["totals"]["rows"], 2)      # а строк две: с Sol Ring

    def test_the_same_name_written_differently_is_one_card(self):
        """«Tiamat's» и «Tiamat’s» -- одна карта, а не две строки."""
        store = FakeStore([deck("d1", "колода", [("Gaea's Cradle", 1, "main")])])
        out = holdings.report(store, {"Gaea’s Cradle": 1})
        self.assertEqual(len(out["cards"]), 1)
        self.assertEqual(out["cards"][0]["owned"], 1)
        self.assertEqual(out["cards"][0]["listed"], 1)


if __name__ == "__main__":
    unittest.main()
