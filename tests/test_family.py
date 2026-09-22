"""Тесты семейства колод: ядро, сменные части, сайдборд, модули.

Смысл проверок один: общее у разных исполнений -- это и есть колода, а
остальное сменные части. Если карта пережила все переделки, она в ядре; если
она есть у одного исполнения и отвечает на чужой ход -- ей место в сайдборде.

Колоды здесь поддельные, как и в тестах учёта: проверяется счёт, а не
хранилище.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import family  # noqa: E402


class FakeStore:
    def __init__(self, decks):
        self._decks = decks

    def list_decks(self):
        return [{"id": d["id"], "name": d["name"], "format": d.get("format", "modern"),
                 "family": d.get("family", ""), "assembled": d.get("assembled", False)}
                for d in self._decks]

    def get_deck(self, deck_id):
        for deck in self._decks:
            if deck["id"] == deck_id:
                out = dict(deck)
                out["cards"] = [{"name": n, "quantity": q, "section": s}
                                for n, q, s in deck["cards"]]
                return out
        raise KeyError(deck_id)


def deck(deck_id, name, cards, fam=""):
    return {"id": deck_id, "name": name, "family": fam,
            "cards": [(n, q, s) for n, q, s in cards]}


A = deck("a", "первый", [("Fog", 4, "main"), ("Maze's End", 4, "main"),
                         ("Explore", 3, "main")], fam="turbofog")
B = deck("b", "второй", [("Fog", 4, "main"), ("Maze's End", 4, "main"),
                         ("Holy Day", 4, "main")], fam="turbofog")
C = deck("c", "третий", [("Fog", 2, "main"), ("Maze's End", 4, "main"),
                         ("Explore", 2, "main"), ("Darkness", 2, "main")],
         fam="turbofog")


class TestFamilies(unittest.TestCase):
    def test_decks_with_one_family_are_grouped(self):
        out = family.families(FakeStore([A, B]))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["name"], "turbofog")
        self.assertEqual(out[0]["variants"], 2)
        self.assertTrue(out[0]["explicit"])

    def test_a_deck_without_a_family_is_its_own(self):
        lone = deck("x", "одинокая", [("Fog", 4, "main")])
        out = family.families(FakeStore([lone]))
        self.assertEqual(out[0]["name"], "одинокая")
        self.assertFalse(out[0]["explicit"])


class TestCore(unittest.TestCase):
    """Общее у всех исполнений -- это и есть колода."""

    def setUp(self):
        self.out = family.compare(FakeStore([A, B, C]), ["a", "b", "c"])

    def test_what_is_everywhere_is_the_core(self):
        core = set(self.out["core"])
        self.assertIn("fog", core)
        self.assertIn("maze's end", core)
        self.assertNotIn("holy day", core)

    def test_the_core_counts_the_smallest_shared_number(self):
        """У Fog 4, 4 и 2 копии: общего -- две, а не четыре."""
        row = next(r for r in self.out["rows"] if r["key"] == "fog")
        self.assertEqual(row["min"], 2)
        self.assertEqual(row["max"], 4)
        self.assertEqual(self.out["totals"]["core_copies"], 2 + 4)

    def test_what_comes_and_goes_is_neither_core_nor_unique(self):
        self.assertIn("explore", self.out["often"])
        self.assertNotIn("explore", self.out["core"])
        self.assertNotIn("explore", self.out["flex"])

    def test_what_is_in_one_execution_only_is_flexible(self):
        self.assertEqual(set(self.out["flex"]), {"holy day", "darkness"})

    def test_every_card_knows_its_count_in_every_execution(self):
        row = next(r for r in self.out["rows"] if r["key"] == "explore")
        self.assertEqual(row["counts"], {"a": 3, "b": 0, "c": 2})
        self.assertEqual(row["present"], 2)


class TestOrder(unittest.TestCase):
    def test_the_core_comes_first(self):
        out = family.compare(FakeStore([A, B]), ["a", "b"])
        first = out["rows"][0]
        self.assertEqual(first["present"], 2)
        self.assertIn(first["key"], out["core"])


class TestSingleExecution(unittest.TestCase):
    def test_one_execution_is_all_core(self):
        out = family.compare(FakeStore([A]), ["a"])
        self.assertEqual(len(out["core"]), 3)
        self.assertEqual(out["flex"], [])

    def test_nothing_to_compare_does_not_fail(self):
        out = family.compare(FakeStore([]), [])
        self.assertEqual(out["rows"], [])
        self.assertEqual(out["totals"]["variants"], 0)


class TestSideboardAndWincon(unittest.TestCase):
    """Разметка по назначению работает только с базой карт; без неё поля есть,
    но пустые -- и это лучше, чем выдумывать."""

    def test_without_the_card_base_nothing_is_marked(self):
        out = family.compare(FakeStore([A, B]), ["a", "b"], db=None)
        self.assertEqual(out["sideboard_candidates"], [])
        self.assertEqual(out["wincons"], [])
        self.assertFalse(any(r["reactive"] for r in out["rows"]))


class TestSections(unittest.TestCase):
    def test_the_sideboard_is_not_part_of_the_deck_itself(self):
        with_side = deck("s", "с сайдом",
                         [("Fog", 4, "main"), ("Darkness", 2, "side")])
        out = family.compare(FakeStore([with_side]), ["s"])
        names = {r["key"] for r in out["rows"]}
        self.assertIn("fog", names)
        self.assertIn("darkness", names)
        row = next(r for r in out["rows"] if r["key"] == "darkness")
        self.assertEqual(row["counts"]["s"], 0)
        self.assertEqual(row["in_side"]["s"], 2)

    def test_the_maybeboard_is_ignored(self):
        with_maybe = deck("m", "с возможным",
                          [("Fog", 4, "main"), ("Sol Ring", 1, "maybe")])
        out = family.compare(FakeStore([with_maybe]), ["m"])
        self.assertEqual({r["key"] for r in out["rows"]}, {"fog"})


if __name__ == "__main__":
    unittest.main()
