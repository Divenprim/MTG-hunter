"""Tests for commander suggestions.

EDHREC is a real service someone else pays for, so nothing here touches the
network: the payload shape is pinned down with a canned response, and the parts
worth guarding are the ones that would silently mislead a builder --

  * the slug, because a wrong one asks for the wrong commander's page;
  * the share of decks, which is the number a builder actually reads;
  * the join with local data: owned, already in the deck, cached rouble price.

The one thing that must never happen here is a topdeck request: a commander page
is 250 cards, and the client is not even given to this code path.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Isolate the on-disk cache before the modules read the data directory.
_TMP = tempfile.mkdtemp(prefix="mtgh-rec-")
os.environ["MTGH_DATA_DIR"] = _TMP

from app import edhrec, recommend  # noqa: E402
from app.cards import CardDB  # noqa: E402
from app.decks import DeckStore  # noqa: E402

DB = CardDB()


def payload(cards=None, total=1000, name="The Ur-Dragon"):
    """A response shaped like the real one, with our own numbers."""
    cards = cards or [
        {"name": "Dragon Tempest", "num_decks": 800, "potential_decks": 1000,
         "synergy": 0.69},
        {"name": "Sol Ring", "num_decks": 950, "potential_decks": 1000,
         "synergy": 0.02},
        {"name": "Lightning Bolt", "num_decks": 100, "potential_decks": 1000,
         "synergy": 0.01},
    ]
    return {
        "container": {
            "json_dict": {
                "card": {
                    "name": name,
                    "num_decks": total,
                    "type_line": "Legendary Creature — Dragon Avatar",
                    "color_identity": ["W", "U", "B", "R", "G"],
                },
                "cardlists": [
                    {"tag": "highsynergycards", "header": "High Synergy Cards",
                     "cardviews": cards},
                    {"tag": "commanders", "header": "Commanders",
                     "cardviews": [{"name": "Should Be Skipped", "num_decks": 1,
                                    "potential_decks": 1}]},
                ],
            }
        }
    }


class FakeClient:
    """Stands in for RecClient: no network, and it counts its calls."""

    def __init__(self, raw=None, fail=None):
        self.raw = raw if raw is not None else payload()
        self.fail = fail
        self.calls = 0
        self.refreshes = 0

    def fetch(self, name, refresh=False):
        self.calls += 1
        if refresh:
            self.refreshes += 1
        if self.fail:
            raise self.fail
        out = dict(self.raw)
        out["_cached"] = not refresh
        out["_fetched"] = 1_700_000_000
        return out


class TestSlug(unittest.TestCase):
    """A wrong slug quietly fetches a different commander's statistics."""

    def test_plain_name(self):
        self.assertEqual(edhrec.slug("The Ur-Dragon"), "the-ur-dragon")

    def test_comma_and_title(self):
        self.assertEqual(edhrec.slug("Miirym, Sentinel Wyrm"), "miirym-sentinel-wyrm")

    def test_apostrophe_is_dropped_not_replaced(self):
        self.assertEqual(edhrec.slug("Atraxa, Praetors' Voice"), "atraxa-praetors-voice")

    def test_typographic_apostrophe_too(self):
        self.assertEqual(edhrec.slug("Atraxa, Praetors’ Voice"), "atraxa-praetors-voice")

    def test_accents_are_folded(self):
        self.assertEqual(edhrec.slug("Márton Stromgald"), "marton-stromgald")

    def test_two_faced_commander_uses_its_front_face(self):
        self.assertEqual(edhrec.slug("Brazen Borrower // Petty Theft"), "brazen-borrower")

    def test_ampersand_becomes_a_word(self):
        self.assertEqual(edhrec.slug("Hanna & Sisay"), "hanna-and-sisay")

    def test_no_trailing_or_double_dashes(self):
        self.assertEqual(edhrec.slug("  Tiamat!!  "), "tiamat")


class TestParse(unittest.TestCase):
    def setUp(self):
        self.rec = edhrec.parse(payload())

    def test_commander_and_deck_count(self):
        self.assertEqual(self.rec["commander"]["name"], "The Ur-Dragon")
        self.assertEqual(self.rec["commander"]["decks"], 1000)

    def test_the_share_of_decks_is_computed(self):
        card = self.rec["sections"][0]["cards"][0]
        self.assertEqual(card["name"], "Dragon Tempest")
        self.assertEqual(card["share"], 0.8)
        self.assertEqual(card["decks"], 800)
        self.assertEqual(card["pool"], 1000)

    def test_the_commander_list_itself_is_skipped(self):
        names = [c["name"] for s in self.rec["sections"] for c in s["cards"]]
        self.assertNotIn("Should Be Skipped", names)

    def test_sections_get_russian_titles(self):
        self.assertEqual(self.rec["sections"][0]["title"],
                         "Высокая синергия с командиром")

    def test_an_unknown_section_keeps_its_own_header(self):
        raw = payload()
        raw["container"]["json_dict"]["cardlists"][0]["tag"] = "somethingnew"
        raw["container"]["json_dict"]["cardlists"][0]["header"] = "Something New"
        rec = edhrec.parse(raw)
        self.assertEqual(rec["sections"][0]["title"], "Something New")

    def test_a_zero_pool_does_not_divide_by_zero(self):
        rec = edhrec.parse(payload(
            cards=[{"name": "X", "num_decks": 0, "potential_decks": 0}], total=0))
        self.assertIsNone(rec["sections"][0]["cards"][0]["share"])

    def test_empty_payload_is_not_a_crash(self):
        rec = edhrec.parse({})
        self.assertEqual(rec["sections"], [])
        self.assertEqual(rec["commander"]["decks"], 0)


class TestEnrich(unittest.TestCase):
    """The join with our own data is the whole point of doing this locally."""

    def setUp(self):
        self.store = DeckStore()
        self.rec = edhrec.parse(payload())

    def cards(self, rec):
        return {c["name"]: c for s in rec["sections"] for c in s["cards"]}

    def test_local_card_data_is_attached(self):
        got = self.cards(recommend.enrich(self.rec, DB, self.store))
        bolt = got["Lightning Bolt"]
        self.assertTrue(bolt["known"])
        self.assertEqual(bolt["card"]["name"], "Lightning Bolt")
        self.assertTrue(bolt["card"]["image_normal"])
        self.assertEqual(bolt["card"]["ru_name"], "Удар Молнии")

    def test_an_unknown_name_is_flagged_not_dropped(self):
        """A card newer than our database must still be visible."""
        rec = edhrec.parse(payload(
            cards=[{"name": "Wholly Invented Card", "num_decks": 5, "potential_decks": 10}]))
        got = self.cards(recommend.enrich(rec, DB, self.store))
        self.assertIn("Wholly Invented Card", got)
        self.assertFalse(got["Wholly Invented Card"]["known"])

    def test_the_collection_marks_what_you_own(self):
        got = self.cards(recommend.enrich(
            self.rec, DB, self.store, collection={"lightning bolt": 3}))
        self.assertEqual(got["Lightning Bolt"]["owned"], 3)
        self.assertEqual(got["Sol Ring"]["owned"], 0)

    def test_ownership_matches_regardless_of_case_or_spacing(self):
        got = self.cards(recommend.enrich(
            self.rec, DB, self.store, collection={"  LIGHTNING   Bolt ": 1}))
        self.assertEqual(got["Lightning Bolt"]["owned"], 1)

    def test_cards_already_in_the_deck_are_marked(self):
        deck = {"cards": [{"name": "Sol Ring", "quantity": 1, "section": "main"}]}
        got = self.cards(recommend.enrich(self.rec, DB, self.store, deck=deck))
        self.assertEqual(got["Sol Ring"]["in_deck"], 1)
        self.assertEqual(got["Dragon Tempest"]["in_deck"], 0)

    def test_staples_are_labelled(self):
        got = self.cards(recommend.enrich(self.rec, DB, self.store))
        self.assertTrue(got["Sol Ring"]["staple"])
        self.assertFalse(got["Dragon Tempest"]["staple"])

    def test_a_card_outside_the_colour_identity_is_flagged(self):
        rec = edhrec.parse(payload())
        rec["commander"]["color_identity"] = ["W"]
        got = self.cards(recommend.enrich(rec, DB, self.store))
        self.assertTrue(got["Lightning Bolt"].get("off_identity"))

    def test_totals_are_reported(self):
        deck = {"cards": [{"name": "Sol Ring", "quantity": 1}]}
        rec = recommend.enrich(self.rec, DB, self.store,
                               collection={"lightning bolt": 1}, deck=deck)
        self.assertEqual(rec["totals"]["cards"], 3)
        self.assertEqual(rec["totals"]["owned"], 1)
        self.assertEqual(rec["totals"]["in_deck"], 1)


class TestForCommander(unittest.TestCase):
    def test_it_uses_the_client_it_is_given_and_asks_once(self):
        client = FakeClient()
        recommend.for_commander("The Ur-Dragon", DB, DeckStore(), client=client)
        self.assertEqual(client.calls, 1)
        self.assertEqual(client.refreshes, 0)

    def test_refresh_is_passed_through(self):
        client = FakeClient()
        recommend.for_commander("The Ur-Dragon", DB, DeckStore(),
                                refresh=True, client=client)
        self.assertEqual(client.refreshes, 1)

    def test_an_edhrec_failure_surfaces_as_such(self):
        client = FakeClient(fail=edhrec.EdhrecError("нет такого командира"))
        with self.assertRaises(edhrec.EdhrecError):
            recommend.for_commander("Nobody", DB, DeckStore(), client=client)


class TestCacheOnDisk(unittest.TestCase):
    """A page fetched once must not be fetched again for two weeks."""

    def test_the_cache_file_is_written_and_read(self):
        path = edhrec._cache_path("Cache Test Commander")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload(name="Cache Test Commander"), fh)

        client = edhrec.RecClient()
        raw = client.fetch("Cache Test Commander")   # no network: cache hit
        self.assertTrue(raw.get("_cached"))
        self.assertEqual(edhrec.parse(raw)["commander"]["name"], "Cache Test Commander")

    def test_an_expired_cache_is_not_used(self):
        path = edhrec._cache_path("Expiry Test")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload(name="Expiry Test"), fh)
        os.utime(path, (0, 0))  # 1970
        self.assertIsNone(edhrec._read_cache(path, edhrec.CACHE_TTL))
        # ...but it is still there to fall back on when the site is unreachable.
        self.assertIsNotNone(edhrec._read_cache(path, -1))

    def test_the_cache_lives_under_the_data_dir(self):
        self.assertTrue(edhrec._cache_path("X").startswith(_TMP))


if __name__ == "__main__":
    unittest.main(verbosity=2)
