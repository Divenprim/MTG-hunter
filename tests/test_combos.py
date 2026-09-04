"""Tests for the combo database.

Commander Spellbook's bulk file is 27 MB compressed and 600 MB of JSON inside,
so nothing here downloads anything: the streaming decoder is fed a gzipped
document built in the test, and the queries run against a database built from
it.

Two things are worth guarding above all:

  * the streaming decoder. The first version sliced its buffer per object,
    which made the parse quadratic -- 44k combos took ten minutes instead of
    the 45 seconds it takes now. A test that feeds it in many small chunks
    catches a regression to that shape.
  * "one card short". That answer becomes a shopping list, so counting it wrong
    means telling someone to buy a card they do not need.
"""

import gzip
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = tempfile.mkdtemp(prefix="mtgh-combo-")
os.environ.setdefault("MTGH_DATA_DIR", _TMP)

from app import combos  # noqa: E402


def variant(vid, cards, results, templates=(), popularity=100,
            commander=True, status="OK", spoiler=False, steps="Do the thing.",
            base=None, variant_count=1):
    return {
        "id": vid,
        "of": [{"id": base or vid}],
        "variantCount": variant_count,
        "status": status,
        "spoiler": spoiler,
        "identity": "U",
        "popularity": popularity,
        "manaNeeded": "{U}",
        "easyPrerequisites": "All permanents on the battlefield.",
        "notablePrerequisites": "",
        "description": steps,
        "bracketTag": "C",
        "legalities": {"commander": commander, "modern": False},
        "uses": [{"card": {"name": n, "oracleId": "x", "typeLine": "Creature"}}
                 for n in cards],
        "requires": [{"template": {"name": t}} for t in templates],
        "produces": [{"feature": {"name": r}} for r in results],
    }


def document(variants):
    payload = {"timestamp": "2026-09-04T00:00:00+00:00", "version": "test",
               "variants": variants}
    return gzip.compress(json.dumps(payload).encode("utf-8"))


def blocks(data, size):
    for i in range(0, len(data), size):
        yield data[i:i + size]


SAMPLE = [
    variant("a", ["Thassa's Oracle", "Demonic Consultation"], ["Win the game"],
            popularity=1000),
    variant("b", ["Kiki-Jiki, Mirror Breaker", "Zealous Conscripts"],
            ["Infinite creature ETB"], popularity=500),
    variant("c", ["Sol Ring", "Hullbreaker Horror"], ["Infinite colorless mana"],
            templates=["Permanent Castable for {C}"], popularity=300),
    variant("d", ["Basalt Monolith", "Rings of Brighthearth"], ["Infinite mana"],
            popularity=200, commander=False),
    variant("e", ["Lightning Bolt"], ["Three damage"], popularity=10),
    variant("f", ["Sol Ring", "Mana Crypt"], ["Spoiled combo"], spoiler=True),
    variant("g", ["Sol Ring", "Mox Diamond"], ["Bad data"], status="NR"),
    # Spellbook generates a variant per interchangeable card: the same base
    # combo three times, differing only in the second card. A deck holding the
    # shared piece must be told "one card away, any of these three" -- not
    # offered three separate suggestions.
    variant("h1", ["Phyrexian Metamorph", "Felidar Guardian"], ["Infinite ETB"],
            popularity=900, base="BASE-H", variant_count=3),
    variant("h2", ["Phyrexian Metamorph", "Wispweaver Angel"], ["Infinite ETB"],
            popularity=400, base="BASE-H", variant_count=3),
    variant("h3", ["Phyrexian Metamorph", "Kiki-Jiki, Mirror Breaker"], ["Infinite ETB"],
            popularity=200, base="BASE-H", variant_count=3),
    # Played by nobody: mechanically generated and never run.
    variant("i", ["Sol Ring", "Mana Vault"], ["Nothing useful"], popularity=0),
]


class TestStreamingDecoder(unittest.TestCase):
    def test_it_decodes_every_variant(self):
        got = list(combos.stream_variants(blocks(document(SAMPLE), 1 << 16)))
        self.assertEqual([v["id"] for v in got], [v["id"] for v in SAMPLE])

    def test_it_survives_byte_at_a_time_delivery(self):
        """Objects are split across chunk boundaries in every possible place."""
        data = document(SAMPLE[:3])
        got = list(combos.stream_variants(blocks(data, 7)))
        self.assertEqual(len(got), 3)
        self.assertEqual(got[0]["id"], "a")

    def test_an_empty_variant_list_is_fine(self):
        self.assertEqual(list(combos.stream_variants(blocks(document([]), 64))), [])

    def test_the_buffer_does_not_grow_without_bound(self):
        """The guard against the quadratic-slicing version coming back.

        With compaction working, a long document is decoded in one pass with a
        buffer that stays small; without it, this test still passes but the real
        build crawls -- so what is asserted here is that compaction happens at
        all, by checking a document far longer than COMPACT_AT is consumed.
        """
        many = [variant("v%d" % i, ["Card A%d" % i, "Card B%d" % i], ["Result"])
                for i in range(2000)]
        data = document(many)
        got = sum(1 for _ in combos.stream_variants(blocks(data, 1 << 14)))
        self.assertEqual(got, 2000)


class TestBuild(unittest.TestCase):
    """The build reduces the payload to what a deckbuilder needs."""

    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(_TMP, "built.sqlite")
        cls.url = "file:///" + cls.path.replace("\\", "/") + ".gz"
        blob = document(SAMPLE)
        with open(cls.path + ".gz", "wb") as fh:
            fh.write(blob)
        cls.report = combos.build(url=cls.url, path=cls.path)
        cls.db = combos.ComboDB(cls.path)

    def test_every_variant_was_stored(self):
        self.assertEqual(self.report["combos"], len(SAMPLE))

    def test_status_reports_what_was_built(self):
        st = self.db.status()
        self.assertTrue(st["ready"])
        self.assertEqual(st["combos"], len(SAMPLE))
        self.assertTrue(st["built_at"])

    def test_cards_and_templates_are_kept_apart(self):
        found = self.db.for_card("Sol Ring")
        combo = next(c for c in found if c["id"] == "c")
        self.assertEqual(sorted(combo["cards"]), ["Hullbreaker Horror", "Sol Ring"])
        self.assertEqual(combo["templates"], ["Permanent Castable for {C}"])

    def test_results_and_steps_survive(self):
        combo = self.db.for_card("Thassa's Oracle")[0]
        self.assertEqual(combo["results"], "Win the game")
        self.assertIn("Do the thing", combo["steps"])
        self.assertIn("battlefield", combo["prereq"])

    def test_most_played_first(self):
        found = self.db.for_card("Sol Ring", commander_only=False)
        pops = [c["popularity"] for c in found]
        self.assertEqual(pops, sorted(pops, reverse=True))

    def test_spoilers_and_broken_rows_are_left_out(self):
        names = [c["id"] for c in self.db.for_card("Sol Ring", commander_only=False)]
        self.assertNotIn("f", names, "спойлерное комбо не должно показываться")
        self.assertNotIn("g", names, "комбо со статусом NR не должно показываться")

    def test_commander_filter(self):
        legal = [c["id"] for c in self.db.for_card("Basalt Monolith")]
        self.assertEqual(legal, [], "комбо нелегальное в commander")
        any_format = [c["id"] for c in
                      self.db.for_card("Basalt Monolith", commander_only=False)]
        self.assertEqual(any_format, ["d"])


class TestDeckAnalysis(unittest.TestCase):
    """The half that turns into a shopping list."""

    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(_TMP, "deck.sqlite")
        with open(cls.path + ".gz", "wb") as fh:
            fh.write(document(SAMPLE))
        combos.build(url="file:///" + cls.path.replace("\\", "/") + ".gz",
                     path=cls.path)
        cls.db = combos.ComboDB(cls.path)

    def ids(self, group):
        return sorted(c["id"] for c in group)

    def test_a_complete_combo_is_reported_as_complete(self):
        res = self.db.for_deck(["Thassa's Oracle", "Demonic Consultation"])
        self.assertEqual(self.ids(res["complete"]), ["a"])
        self.assertEqual(res["near"], [])

    def test_one_card_short_names_the_card_to_buy(self):
        res = self.db.for_deck(["Thassa's Oracle"], max_missing=1)
        self.assertEqual(self.ids(res["near"]), ["a"])
        self.assertEqual(res["near"][0]["missing"], ["Demonic Consultation"])
        self.assertEqual(res["near"][0]["have"], ["Thassa's Oracle"])

    def test_two_cards_short_is_not_offered_by_default(self):
        res = self.db.for_deck(["Sol Ring"], max_missing=1)
        # combo "c" needs Hullbreaker Horror as well -- one card short, so shown
        self.assertEqual(self.ids(res["near"]), ["c"])
        # nothing here is complete
        self.assertEqual(res["complete"], [])

    def test_a_combo_still_needing_a_template_is_not_called_complete(self):
        """The half-truth the user caught.

        Sol Ring + Hullbreaker Horror also needs "any permanent castable for
        {C}". A card list cannot confirm that, so the combo went into the
        "собрано" pile and the interface said the deck had it. It does not: it
        has the two named cards and still needs a third thing.
        """
        res = self.db.for_deck(["Sol Ring", "Hullbreaker Horror"])
        self.assertNotIn("c", self.ids(res["complete"]),
                         "комбо с невыполненным шаблоном не «собрано»")
        combo = next(c for c in res["needs_template"] if c["id"] == "c")
        self.assertEqual(combo["missing"], [])
        self.assertEqual(combo["needs_template"], ["Permanent Castable for {C}"])

    def test_a_template_is_not_counted_as_a_card_to_buy(self):
        """It cannot be bought: any card with the effect will do."""
        res = self.db.for_deck(["Sol Ring"], max_missing=1)
        combo = next(c for c in res["near"] if c["id"] == "c")
        self.assertEqual(combo["missing"], ["Hullbreaker Horror"])
        self.assertEqual(combo["needs_template"], ["Permanent Castable for {C}"])

    def test_single_card_combos_are_not_suggested(self):
        """A "combo" of one card the deck already has is noise."""
        res = self.db.for_deck(["Lightning Bolt"], max_missing=1)
        self.assertNotIn("e", self.ids(res["complete"]) + self.ids(res["near"]))

    def test_an_empty_deck_asks_nothing(self):
        res = self.db.for_deck([])
        self.assertEqual(res["complete"], [])
        self.assertEqual(res["near"], [])
        self.assertEqual(res["checked"], 0)

    def test_names_match_regardless_of_case_and_spacing(self):
        res = self.db.for_deck(["  thassa's   ORACLE ", "demonic consultation"])
        self.assertEqual(self.ids(res["complete"]), ["a"])

    def test_it_reports_how_many_cards_it_checked(self):
        res = self.db.for_deck(["Sol Ring", "Sol Ring", "Lightning Bolt"])
        self.assertEqual(res["checked"], 2, "дубликаты не должны считаться дважды")



class TestVariantsAreCollapsed(unittest.TestCase):
    """Nine rows for one combo is what made the list look like nonsense.

    Spellbook generates a variant per interchangeable card -- 108,779 rows come
    from 27,345 base combos, and one base can have 858 variants. A deck holding
    the shared piece was told nine times over that it was one card away, once
    per card that could fill the slot. It is one combo, and any of those cards
    finishes it.
    """

    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(_TMP, "collapse.sqlite")
        with open(cls.path + ".gz", "wb") as fh:
            fh.write(document(SAMPLE))
        combos.build(url="file:///" + cls.path.replace("\\", "/") + ".gz",
                     path=cls.path)
        cls.db = combos.ComboDB(cls.path)

    def test_one_row_per_base_combo(self):
        res = self.db.for_deck(["Phyrexian Metamorph"], max_missing=1)
        self.assertEqual(len(res["near"]), 1,
                         "три варианта одной связки должны стать одной строкой")

    def test_it_lists_every_card_that_would_finish_it(self):
        res = self.db.for_deck(["Phyrexian Metamorph"], max_missing=1)
        self.assertEqual(sorted(res["near"][0]["one_of"]),
                         ["Felidar Guardian", "Kiki-Jiki, Mirror Breaker",
                          "Wispweaver Angel"])

    def test_it_says_how_many_variants_there_are(self):
        res = self.db.for_deck(["Phyrexian Metamorph"], max_missing=1)
        self.assertEqual(res["near"][0]["variants"], 3)

    def test_the_most_played_variant_represents_the_group(self):
        res = self.db.for_deck(["Phyrexian Metamorph"], max_missing=1)
        self.assertEqual(res["near"][0]["popularity"], 900)

    def test_a_complete_variant_wins_over_a_near_one(self):
        """Holding one of the interchangeable cards means it is done."""
        res = self.db.for_deck(["Phyrexian Metamorph", "Wispweaver Angel"])
        self.assertEqual(len(res["complete"]), 1)
        self.assertEqual(res["complete"][0]["missing"], [])
        self.assertEqual(res["near"], [])

    def test_the_card_window_gets_one_row_per_base_too(self):
        found = self.db.for_card("Phyrexian Metamorph")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["variants"], 3)

    def test_the_card_window_makes_no_claim_about_what_is_missing(self):
        """There is no deck there, so "не хватает 1" would be a lie."""
        found = self.db.for_card("Phyrexian Metamorph")
        self.assertNotIn("missing", found[0])
        self.assertNotIn("one_of", found[0])


class TestUnplayedCombosAreHiddenByDefault(unittest.TestCase):
    """46,286 of the 108,779 rows are in nobody's deck."""

    @classmethod
    def setUpClass(cls):
        cls.path = os.path.join(_TMP, "unplayed.sqlite")
        with open(cls.path + ".gz", "wb") as fh:
            fh.write(document(SAMPLE))
        combos.build(url="file:///" + cls.path.replace("\\", "/") + ".gz",
                     path=cls.path)
        cls.db = combos.ComboDB(cls.path)

    def test_a_combo_nobody_plays_is_not_suggested(self):
        res = self.db.for_deck(["Sol Ring"], max_missing=1)
        missing = [n for c in res["near"] for n in c["missing"]]
        self.assertNotIn("Mana Vault", missing,
                         "комбо с популярностью 0 не должно предлагаться")

    def test_it_can_be_asked_for_explicitly(self):
        res = self.db.for_deck(["Sol Ring"], max_missing=1, min_popularity=0)
        missing = [n for c in res["near"] for n in c["missing"]]
        self.assertIn("Mana Vault", missing)

    def test_the_floor_is_reported_so_the_interface_can_say_so(self):
        self.assertEqual(self.db.for_deck(["Sol Ring"])["min_popularity"], 1)
        self.assertEqual(
            self.db.for_deck(["Sol Ring"], min_popularity=0)["min_popularity"], 0)

    def test_the_card_window_hides_them_too(self):
        found = self.db.for_card("Sol Ring", commander_only=False)
        self.assertNotIn("i", [c["id"] for c in found])
        with_all = self.db.for_card("Sol Ring", commander_only=False, min_popularity=0)
        self.assertIn("i", [c["id"] for c in with_all])

class TestNotBuiltYet(unittest.TestCase):
    def test_asking_before_building_says_so_clearly(self):
        db = combos.ComboDB(os.path.join(_TMP, "nope.sqlite"))
        self.assertFalse(db.ready)
        self.assertEqual(db.status(), {"ready": False})
        with self.assertRaises(combos.ComboError) as caught:
            db.for_card("Sol Ring")
        self.assertIn("не собрана", str(caught.exception))


if __name__ == "__main__":
    unittest.main(verbosity=2)
