"""Tests for comparing a deck with the average deck on its commander.

Nothing here touches the network: EDHREC is someone else's free service, so
both pages it would fetch are canned, and the client is a stub that fails the
test if it is asked for anything else.

What is worth guarding:

  * a card is counted once, under one type, or the totals stop adding up to 99;
  * a land is a land and not a function, and a ramp spell that searches a
    library is ramp and not a tutor -- otherwise nine fetchlands and Cultivate
    turn into "22 туторов", which is the kind of advice that sends someone
    looking for a bug;
  * a difference is only called notable when it is big enough to act on;
  * the commander itself is outside the comparison, on both sides.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Isolate the on-disk cache before the modules read the data directory.
_TMP = tempfile.mkdtemp(prefix="mtgh-shape-")
os.environ["MTGH_DATA_DIR"] = _TMP

from app import deckshape  # noqa: E402
from app.cards import CardDB  # noqa: E402

DB = CardDB()

# Numbers of a plausible commander page. They are not any real commander's --
# the point is that our side reads them, not that they are true.
COMMANDER_PAGE = {
    "creature": 28,
    "instant": 8,
    "sorcery": 8,
    "artifact": 10,
    "enchantment": 8,
    "battle": 0,
    "planeswalker": 1,
    "land": 36,
    "basic": 12,
    "nonbasic": 24,
    "tag_counts": [
        {"count": 5700, "slug": "dragons", "value": "Dragons"},
        {"count": 591, "slug": "aggro", "value": "Aggro"},
    ],
    "budget_counts": {"budget": 100, "middle": 800, "expensive": 100},
    "bracket_counts": {"2": 300, "3": 500},
    "panels": {
        "mana_curve": {"1": 5, "2": 11, "3": 13},
        "combocounts": [
            {"value": "Dragon Tempest + Ancient Gold Dragon", "href": "/combos/x"},
        ],
    },
    "container": {"json_dict": {"card": {"name": "Tiamat", "num_decks": 1234}}},
}

# The averaged decklist: real card names, so the local database can be joined.
AVERAGE_CARDS = [
    "Sol Ring", "Arcane Signet", "Cultivate", "Rampant Growth",
    "Vampiric Tutor", "Rhystic Study", "Swords to Plowshares",
    "Counterspell", "Birds of Paradise", "Mountain",
]

AVERAGE_PAGE = {
    "creature": 28,
    "land": 36,
    "basic": 12,
    "container": {
        "json_dict": {
            "cardlists": [
                {"cardviews": [{"name": name} for name in AVERAGE_CARDS]},
            ]
        }
    },
}


class Stub:
    """Stands in for RecClient: two canned pages and nothing else."""

    def __init__(self):
        self.asked = []

    def fetch(self, name, refresh=False, kind="commanders"):
        self.asked.append((name, kind, refresh))
        if kind == "commanders":
            return dict(COMMANDER_PAGE, _cached=True)
        if kind == "average-decks":
            return dict(AVERAGE_PAGE, _cached=True)
        raise AssertionError("нежданный запрос: %s" % kind)


def deck(rows):
    return {"cards": [
        {"name": name, "quantity": qty, "section": section}
        for name, qty, section in rows
    ]}


class TestCounting(unittest.TestCase):
    def test_a_card_is_counted_under_one_type_only(self):
        """An artifact creature is a creature, not both."""
        m = deckshape.measure([("Solemn Simulacrum", 1)], DB)
        self.assertEqual(m["types"].get("creature"), 1)
        self.assertIsNone(m["types"].get("artifact"))
        self.assertEqual(sum(m["types"].values()), 1)

    def test_a_creature_land_is_a_land(self):
        m = deckshape.measure([("Dryad Arbor", 1)], DB)
        self.assertEqual(m["types"].get("land"), 1)
        self.assertIsNone(m["types"].get("creature"))

    def test_copies_are_counted_not_names(self):
        m = deckshape.measure([("Mountain", 9)], DB)
        self.assertEqual(m["cards"], 9)
        self.assertEqual(m["basics"], 9)
        self.assertEqual(m["types"].get("land"), 9)

    def test_lands_stay_out_of_the_curve(self):
        m = deckshape.measure([("Mountain", 5), ("Sol Ring", 1)], DB)
        self.assertEqual(m["curve"], {1: 1})

    def test_a_card_we_do_not_know_is_reported_not_dropped(self):
        m = deckshape.measure([("Не карта, а название", 3)], DB)
        self.assertEqual(m["unknown"], 3)
        self.assertEqual(m["cards"], 3)
        self.assertEqual(m["types"], {})


class TestFunctions(unittest.TestCase):
    def test_a_land_tutor_is_ramp_and_not_a_tutor(self):
        m = deckshape.measure([("Cultivate", 1)], DB)
        self.assertEqual(m["functions"].get("ramp"), 1)
        self.assertIsNone(m["functions"].get("tutor"))

    def test_a_real_tutor_is_a_tutor(self):
        m = deckshape.measure([("Vampiric Tutor", 1)], DB)
        self.assertEqual(m["functions"].get("tutor"), 1)

    def test_a_card_counts_in_every_function_it_serves(self):
        """A mana rock that draws is ramp and draw both."""
        m = deckshape.measure([("Sol Ring", 1), ("Rhystic Study", 1)], DB)
        self.assertEqual(m["functions"].get("ramp"), 1)
        self.assertEqual(m["functions"].get("draw"), 1)

    def test_a_fetchland_is_a_land_and_not_a_tutor(self):
        """Nine fetchlands must not be reported as nine tutors."""
        m = deckshape.measure([("Arid Mesa", 1)], DB)
        self.assertEqual(m["types"].get("land"), 1)
        self.assertEqual(m["functions"], {})

    def test_a_land_contributes_no_function_at_all(self):
        m = deckshape.measure([("The World Tree", 1), ("Ancient Tomb", 1)], DB)
        self.assertEqual(m["types"].get("land"), 2)
        self.assertEqual(m["functions"], {})

    def test_removal_is_recognised(self):
        m = deckshape.measure([("Swords to Plowshares", 1)], DB)
        self.assertEqual(m["functions"].get("removal"), 1)


class TestDeckRows(unittest.TestCase):
    def test_the_commander_is_outside_the_comparison(self):
        rows = deckshape.deck_rows(deck([
            ("Tiamat", 1, "commander"),
            ("Sol Ring", 1, "main"),
            ("Lightning Bolt", 1, "side"),
        ]))
        self.assertEqual(rows, [("Sol Ring", 1)])


class TestLines(unittest.TestCase):
    def test_only_a_gap_worth_acting_on_is_notable(self):
        rows = deckshape._lines(
            [("ramp", "Рампа"), ("draw", "Добор")],
            {"ramp": 4, "draw": 7}, {"ramp": 10, "draw": 8},
            deckshape.NOTABLE_FUNCTION)
        ramp, draw = rows
        self.assertEqual((ramp["yours"], ramp["average"], ramp["delta"]), (4, 10, -6))
        self.assertTrue(ramp["notable"])
        self.assertFalse(draw["notable"], "разница в одну карту -- это не совет")

    def test_a_row_empty_on_both_sides_is_not_shown(self):
        rows = deckshape._lines(
            [("battle", "Битвы")], {}, {}, deckshape.NOTABLE_TYPE)
        self.assertEqual(rows, [])


class TestCompare(unittest.TestCase):
    def setUp(self):
        self.stub = Stub()

    def test_both_pages_are_asked_for_once_each(self):
        deckshape.compare(deck([("Sol Ring", 1, "main")]), "Tiamat", DB,
                          client=self.stub)
        kinds = [kind for _name, kind, _refresh in self.stub.asked]
        self.assertEqual(sorted(kinds), ["average-decks", "commanders"])

    def test_average_types_come_from_the_pages_own_counts(self):
        """The averaged decklist collapses basics; the counts do not."""
        res = deckshape.compare(deck([("Sol Ring", 1, "main")]), "Tiamat", DB,
                                client=self.stub)
        types = {row["key"]: row["average"] for row in res["types"]}
        self.assertEqual(types["creature"], 28)
        self.assertEqual(types["land"], 36)
        self.assertEqual(res["cards"]["average"], 99)
        self.assertNotIn("basic", types, "базовые -- это часть земель, не тип")

    def test_your_side_is_your_deck(self):
        res = deckshape.compare(
            deck([("Mountain", 10, "main"), ("Sol Ring", 1, "main"),
                  ("Tiamat", 1, "commander")]),
            "Tiamat", DB, client=self.stub)
        types = {row["key"]: row["yours"] for row in res["types"]}
        self.assertEqual(types["land"], 10)
        self.assertEqual(types["artifact"], 1)
        self.assertEqual(res["cards"]["yours"], 11)

    def test_functions_compare_both_decks_by_the_same_rule(self):
        res = deckshape.compare(deck([("Cultivate", 1, "main")]), "Tiamat", DB,
                                client=self.stub)
        ramp = next(r for r in res["functions"] if r["key"] == "ramp")
        # Four of the ten canned cards are ramp by our tags.
        self.assertGreaterEqual(ramp["average"], 3)
        self.assertEqual(ramp["yours"], 1)
        self.assertTrue(ramp["notable"])

    def test_themes_budget_brackets_and_combos_come_through(self):
        res = deckshape.compare(deck([]), "Tiamat", DB, client=self.stub)
        self.assertEqual([t["label"] for t in res["themes"]], ["Dragons", "Aggro"])
        self.assertEqual(res["brackets"], {"2": 300, "3": 500})
        self.assertEqual(res["budget"]["middle"], 800)
        self.assertEqual(res["combos"][0]["cards"],
                         ["Dragon Tempest", "Ancient Gold Dragon"])
        self.assertEqual(res["decks"], 1234)

    def test_the_curve_is_the_pages_own(self):
        res = deckshape.compare(deck([("Sol Ring", 1, "main")]), "Tiamat", DB,
                                client=self.stub)
        self.assertEqual(res["curve"]["average"][2], 11)
        self.assertEqual(res["curve"]["yours"], {1: 1})


class TestPolitenessGuard(unittest.TestCase):
    def test_a_page_is_not_asked_for_without_a_commander(self):
        from app.edhrec import EdhrecError, RecClient

        with self.assertRaises(EdhrecError):
            RecClient().fetch("")


if __name__ == "__main__":
    unittest.main(verbosity=2)
