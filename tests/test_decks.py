"""Tests for deck storage, validation and goldfishing.

Runs against a temporary user database, never the real data/user.sqlite.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import deckbuild, goldfish  # noqa: E402
from app.cards import CardDB  # noqa: E402
from app.decks import DeckError, DeckStore  # noqa: E402

DB = CardDB()


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        os.unlink(self.path)
        self.store = DeckStore(self.path)

    def tearDown(self):
        try:
            self.store.conn.close()
        except Exception:  # noqa: BLE001
            pass
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.path + suffix)
            except OSError:
                pass

    def commander_deck(self, cards):
        deck_id = self.store.create_deck("Тест", "commander")
        self.store.add_many(deck_id, cards)
        return deck_id

    def enriched(self, deck_id, collection=None):
        deck = self.store.get_deck(deck_id)
        return deckbuild.enrich(deck, DB, self.store, collection or {})


class TestStorage(StoreTestCase):
    def test_create_and_list(self):
        self.store.create_deck("Первая", "modern")
        decks = self.store.list_decks()
        self.assertEqual(len(decks), 1)
        self.assertEqual(decks[0]["format"], "modern")

    def test_blank_name_refused(self):
        with self.assertRaises(DeckError):
            self.store.create_deck("   ")

    def test_same_card_same_section_stacks(self):
        deck_id = self.store.create_deck("Стопка")
        self.store.add_card(deck_id, "Sol Ring")
        self.store.add_card(deck_id, "Sol Ring", quantity=3)
        cards = self.store.get_deck(deck_id)["cards"]
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["quantity"], 4)

    def test_same_card_different_section_is_separate(self):
        deck_id = self.store.create_deck("Секции")
        self.store.add_card(deck_id, "Sol Ring", section="main")
        self.store.add_card(deck_id, "Sol Ring", section="side")
        self.assertEqual(len(self.store.get_deck(deck_id)["cards"]), 2)

    def test_quantity_floor_is_one(self):
        deck_id = self.store.create_deck("Кол-во")
        card_id = self.store.add_card(deck_id, "Sol Ring")
        self.store.update_card(deck_id, card_id, quantity=0)
        self.assertEqual(self.store.get_deck(deck_id)["cards"][0]["quantity"], 1)

    def test_unknown_deck_reports_readably(self):
        with self.assertRaises(DeckError):
            self.store.get_deck("nope")


class TestVersions(StoreTestCase):
    def test_restore_brings_cards_back(self):
        deck_id = self.commander_deck([{"name": "Sol Ring"}, {"name": "Cultivate"}])
        version = self.store.save_version(deck_id, "снимок")
        card_id = self.store.get_deck(deck_id)["cards"][0]["id"]
        self.store.remove_card(deck_id, card_id)
        self.assertEqual(len(self.store.get_deck(deck_id)["cards"]), 1)

        self.store.restore_version(deck_id, version)
        names = {c["name"] for c in self.store.get_deck(deck_id)["cards"]}
        self.assertEqual(names, {"Sol Ring", "Cultivate"})

    def test_restore_saves_the_current_state_first(self):
        """Restoring must never be the action that loses work."""
        deck_id = self.commander_deck([{"name": "Sol Ring"}])
        version = self.store.save_version(deck_id, "первая")
        self.store.add_card(deck_id, "Cultivate")
        self.store.restore_version(deck_id, version)
        labels = [v["label"] for v in self.store.list_versions(deck_id)]
        self.assertIn("перед откатом", labels)


class TestValidation(StoreTestCase):
    def test_colour_identity_violation(self):
        deck_id = self.commander_deck([
            {"name": "Atraxa, Praetors' Voice", "section": "commander"},
            {"name": "Lightning Bolt", "section": "main"},
        ])
        problems = self.enriched(deck_id)["problems"]
        self.assertTrue(
            any("цветовой идентичности" in p["text"] for p in problems), problems
        )

    def test_card_inside_identity_is_fine(self):
        deck_id = self.commander_deck([
            {"name": "Atraxa, Praetors' Voice", "section": "commander"},
            {"name": "Cultivate", "section": "main"},
        ])
        problems = self.enriched(deck_id)["problems"]
        self.assertFalse(any("цветовой идентичности" in p["text"] for p in problems))

    def test_singleton_violation(self):
        deck_id = self.commander_deck([
            {"name": "Atraxa, Praetors' Voice", "section": "commander"},
            {"name": "Cultivate", "quantity": 2, "section": "main"},
        ])
        problems = self.enriched(deck_id)["problems"]
        self.assertTrue(any("синглтонный" in p["text"] for p in problems), problems)

    def test_basic_lands_are_exempt_from_singleton(self):
        deck_id = self.commander_deck([
            {"name": "Atraxa, Praetors' Voice", "section": "commander"},
            {"name": "Plains", "quantity": 20, "section": "main"},
        ])
        problems = self.enriched(deck_id)["problems"]
        self.assertFalse(
            any("Plains" in p["text"] and "синглтон" in p["text"] for p in problems)
        )

    def test_missing_commander_is_reported(self):
        deck_id = self.commander_deck([{"name": "Sol Ring"}])
        problems = self.enriched(deck_id)["problems"]
        self.assertTrue(any("Не выбран командир" in p["text"] for p in problems))

    def test_non_legendary_commander_is_reported(self):
        deck_id = self.commander_deck([
            {"name": "Sol Ring", "section": "commander"},
        ])
        problems = self.enriched(deck_id)["problems"]
        self.assertTrue(any("не легендарная" in p["text"] for p in problems), problems)

    def test_four_of_limit_in_constructed(self):
        deck_id = self.store.create_deck("Модерн", "modern")
        self.store.add_card(deck_id, "Lightning Bolt", quantity=5)
        problems = self.enriched(deck_id)["problems"]
        self.assertTrue(any("максимум 4" in p["text"] for p in problems), problems)

    def test_unknown_card_name_is_an_error(self):
        deck_id = self.store.create_deck("Опечатка", "modern")
        self.store.add_card(deck_id, "Lightnign Bolt")
        problems = self.enriched(deck_id)["problems"]
        self.assertTrue(any("нет в базе" in p["text"] for p in problems), problems)

    def test_banned_card_is_an_error(self):
        """Channel is banned in Modern."""
        deck_id = self.store.create_deck("Бан", "modern")
        self.store.add_card(deck_id, "Channel")
        problems = self.enriched(deck_id)["problems"]
        self.assertTrue(
            any("забанена" in p["text"] or "не входит" in p["text"] for p in problems),
            problems,
        )


class TestOwnershipAndStats(StoreTestCase):
    def test_missing_counts_against_the_collection(self):
        deck_id = self.store.create_deck("Нехватка", "modern")
        self.store.add_card(deck_id, "Lightning Bolt", quantity=4)
        deck = self.enriched(deck_id, {"lightning bolt": 1})
        row = deck["cards"][0]
        self.assertEqual(row["owned"], 1)
        self.assertEqual(row["missing"], 3)

    def test_russian_name_in_collection_counts(self):
        deck_id = self.store.create_deck("Русский", "modern")
        self.store.add_card(deck_id, "Lightning Bolt", quantity=2)
        deck = self.enriched(deck_id, {"удар молнии": 2})
        self.assertEqual(deck["cards"][0]["missing"], 0)

    def test_stats_separate_lands_from_the_curve(self):
        deck_id = self.store.create_deck("Кривая", "modern")
        self.store.add_card(deck_id, "Plains", quantity=10)
        self.store.add_card(deck_id, "Lightning Bolt", quantity=4)
        stats = self.enriched(deck_id)["stats"]
        self.assertEqual(stats["lands"], 10)
        self.assertEqual(sum(stats["curve"].values()), 4)


class TestAutoCategory(StoreTestCase):
    def test_categories_come_from_functional_tags(self):
        deck_id = self.store.create_deck("Категории", "commander")
        self.store.add_many(deck_id, [
            {"name": "Cultivate"}, {"name": "Demonic Tutor"},
            {"name": "Swords to Plowshares"}, {"name": "Plains"},
        ])
        deck = self.enriched(deck_id)
        deckbuild.auto_categorise(deck, DB, self.store)
        got = {c["name"]: c["category"] for c in self.store.get_deck(deck_id)["cards"]}
        self.assertEqual(got["Plains"], "земли")
        self.assertTrue(got["Cultivate"], "Cultivate got no category")
        self.assertTrue(got["Swords to Plowshares"], "removal got no category")

    def test_a_category_you_typed_is_not_overwritten(self):
        deck_id = self.store.create_deck("Своё", "commander")
        card_id = self.store.add_card(deck_id, "Cultivate", category="моя категория")
        deck = self.enriched(deck_id)
        deckbuild.auto_categorise(deck, DB, self.store)
        cards = {c["id"]: c for c in self.store.get_deck(deck_id)["cards"]}
        self.assertEqual(cards[card_id]["category"], "моя категория")


class TestGoldfish(StoreTestCase):
    def land_deck(self, lands=17, spells=23):
        deck_id = self.store.create_deck("Голдфиш", "modern")
        self.store.add_card(deck_id, "Plains", quantity=lands)
        self.store.add_card(deck_id, "Lightning Bolt", quantity=spells)
        return self.enriched(deck_id)

    def test_commanders_are_not_in_the_library(self):
        deck_id = self.commander_deck([
            {"name": "Atraxa, Praetors' Voice", "section": "commander"},
            {"name": "Plains", "quantity": 10, "section": "main"},
        ])
        library = goldfish.build_library(self.enriched(deck_id))
        self.assertEqual(len(library), 10)
        self.assertNotIn("Atraxa, Praetors' Voice", [c["name"] for c in library])

    def test_simulation_is_deterministic_with_a_seed(self):
        deck = self.land_deck()
        a = goldfish.simulate(deck, games=200, seed=7)
        b = goldfish.simulate(deck, games=200, seed=7)
        self.assertEqual(a["avg_lands_in_hand"], b["avg_lands_in_hand"])
        self.assertEqual(a["land_distribution"], b["land_distribution"])

    def test_land_count_matches_the_deck(self):
        deck = self.land_deck(lands=17, spells=23)
        result = goldfish.simulate(deck, games=300, seed=1)
        self.assertEqual(result["library"], 40)
        self.assertEqual(result["lands_in_library"], 17)

    def test_more_lands_means_more_lands_in_hand(self):
        few = goldfish.simulate(self.land_deck(10, 30), games=800, seed=3)
        many = goldfish.simulate(self.land_deck(30, 10), games=800, seed=3)
        self.assertLess(few["avg_lands_in_hand"], many["avg_lands_in_hand"])

    def test_distribution_sums_to_the_number_of_games(self):
        result = goldfish.simulate(self.land_deck(), games=250, seed=5)
        self.assertEqual(sum(result["land_distribution"].values()), 250)

    def test_tiny_deck_reports_a_readable_error(self):
        deck_id = self.store.create_deck("Мало", "modern")
        self.store.add_card(deck_id, "Plains", quantity=3)
        result = goldfish.simulate(self.enriched(deck_id))
        self.assertIn("error", result)

    def test_assumptions_are_returned(self):
        """They are printed in the UI; a simulation that hides them is worse
        than none."""
        result = goldfish.simulate(self.land_deck(), games=100, seed=2)
        self.assertTrue(result["assumptions"])

    def test_deal_returns_a_hand_and_the_rest(self):
        deck = self.land_deck()
        dealt = goldfish.deal(deck, hand_size=7, seed=11)
        self.assertEqual(len(dealt["hand"]), 7)
        self.assertEqual(dealt["library_size"], 33)


if __name__ == "__main__":
    unittest.main(verbosity=2)
