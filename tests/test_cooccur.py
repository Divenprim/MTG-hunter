"""Tests for the sample of real decks and the statistics over it.

Nothing here touches the network. The sampler is driven with a stub that hands
out canned decks and counts what it was asked for, because the two things that
matter about it are not arithmetic:

  * it must never fetch a deck twice -- the cache is the whole reason someone
    else's server can be asked at all;
  * it must fetch in chunks and stop, so closing the panel stops the traffic.

For the statistics, the property worth pinning down is that a staple and a
signature card look different: both may be in most of the neighbouring decks,
but only the signature card is rarer in the sample at large.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Isolate the on-disk cache before the modules read the data directory.
_TMP = tempfile.mkdtemp(prefix="mtgh-coocc-")
os.environ["MTGH_DATA_DIR"] = _TMP

from app import archidekt, cooccur  # noqa: E402

COMMANDER = "Tiamat"

# Every deck runs the staples; only the "dragon" decks run the dragon cards.
STAPLES = ["Sol Ring", "Command Tower", "Arcane Signet"]
DRAGONS = ["Dragon Tempest", "Terror of the Peaks", "Old Gnawbone"]
OTHER = ["Rhystic Study", "Counterspell", "Swords to Plowshares"]
FILLER = ["Mountain", "Forest", "Island"]


def dragon_deck(n):
    return STAPLES + DRAGONS + FILLER + ["Filler Dragon %d" % n]


def plain_deck(n):
    return STAPLES + OTHER + FILLER + ["Filler Plain %d" % n]


class StubSampler:
    """Hands out canned decks and remembers every id it was asked for."""

    def __init__(self, deck_count=40, fail=()):
        self.asked = []
        self.pages = 0
        self.fail = {str(x) for x in fail}
        self.deck_count = deck_count

    def more_ids(self, commander, data):
        self.pages += 1
        if self.pages > 2:
            data["exhausted"] = True
            return 0
        start = (self.pages - 1) * 20
        added = 0
        for i in range(start, start + 20):
            if i >= self.deck_count:
                data["exhausted"] = True
                break
            data["ids"].append(i)
            added += 1
        data["pages_done"] = self.pages
        return added

    def one_deck(self, deck_id):
        self.asked.append(str(deck_id))
        if str(deck_id) in self.fail:
            return None
        n = int(deck_id)
        return dragon_deck(n) if n % 2 == 0 else plain_deck(n)


def sample_of(dragons=10, plain=10):
    decks = {}
    for i in range(dragons):
        decks["d%d" % i] = dragon_deck(i)
    for i in range(plain):
        decks["p%d" % i] = plain_deck(i)
    return {"commander": COMMANDER, "decks": decks}


class TestSampling(unittest.TestCase):
    def setUp(self):
        # Each test starts with an empty cache of its own.
        path = archidekt._cache_path(COMMANDER)
        if os.path.exists(path):
            os.remove(path)

    def test_one_call_fetches_one_chunk_and_returns(self):
        stub = StubSampler()
        state = archidekt.collect(COMMANDER, target=100, chunk=5, sampler=stub)
        self.assertEqual(state["decks"], 5)
        self.assertEqual(len(stub.asked), 5)
        self.assertFalse(state["done"])

    def test_the_next_call_continues_and_repeats_nothing(self):
        stub = StubSampler()
        archidekt.collect(COMMANDER, target=100, chunk=5, sampler=stub)
        archidekt.collect(COMMANDER, target=100, chunk=5, sampler=stub)
        self.assertEqual(len(stub.asked), 10)
        self.assertEqual(len(set(stub.asked)), 10, "колода скачана дважды")
        self.assertEqual(archidekt.state(COMMANDER, 100)["decks"], 10)

    def test_reaching_the_target_stops_the_fetching(self):
        stub = StubSampler()
        archidekt.collect(COMMANDER, target=7, chunk=5, sampler=stub)
        state = archidekt.collect(COMMANDER, target=7, chunk=5, sampler=stub)
        self.assertEqual(state["decks"], 7)
        self.assertTrue(state["done"])
        self.assertEqual(len(stub.asked), 7, "качали больше, чем просили")

        # And a further call must not fetch anything at all.
        archidekt.collect(COMMANDER, target=7, chunk=5, sampler=stub)
        self.assertEqual(len(stub.asked), 7)

    def test_a_deck_that_cannot_be_read_is_not_retried(self):
        stub = StubSampler(fail=[0, 1])
        archidekt.collect(COMMANDER, target=4, chunk=4, sampler=stub)
        archidekt.collect(COMMANDER, target=4, chunk=4, sampler=stub)
        self.assertEqual(len(set(stub.asked)), len(stub.asked), "повтор неудачной колоды")
        state = archidekt.state(COMMANDER, 4)
        self.assertEqual(state["failed"], 2)
        self.assertEqual(state["decks"], 4)

    def test_an_exhausted_search_does_not_spin(self):
        stub = StubSampler(deck_count=6)
        state = archidekt.collect(COMMANDER, target=100, chunk=50, sampler=stub)
        self.assertEqual(state["decks"], 6)
        self.assertLessEqual(stub.pages, 3, "поиск крутился без нужды")

    def test_the_target_is_capped(self):
        stub = StubSampler(deck_count=1000)
        state = archidekt.collect(COMMANDER, target=99999, chunk=1, sampler=stub)
        self.assertEqual(state["target"], archidekt.MAX_TARGET)

    def test_state_reads_the_disk_and_fetches_nothing(self):
        stub = StubSampler()
        archidekt.collect(COMMANDER, target=3, chunk=3, sampler=stub)
        before = len(stub.asked)
        for _ in range(3):
            archidekt.state(COMMANDER, 150)
            archidekt.load(COMMANDER)
        self.assertEqual(len(stub.asked), before)


class TestNeighbourhood(unittest.TestCase):
    def test_the_closest_decks_are_the_ones_like_yours(self):
        sample = sample_of()
        decks = cooccur.sample_decks(sample)
        # Six cards, so the dragon decks clear MIN_OVERLAP and the plain ones
        # (three staples in common) do not.
        mine = cooccur._keys(DRAGONS + STAPLES)
        close, fallback = cooccur.neighbourhood(mine, decks, near=10)
        self.assertFalse(fallback)
        self.assertEqual(len(close), 10)
        for _score, deck_id, _keys in close:
            self.assertTrue(deck_id.startswith("d"), deck_id)

    def test_basics_do_not_make_decks_similar(self):
        """Everybody plays Mountains; a deck of lands has no neighbours."""
        sample = sample_of()
        decks = cooccur.sample_decks(sample)
        _close, fallback = cooccur.neighbourhood(
            cooccur._keys(["Mountain", "Forest", "Island"]), decks, near=10)
        self.assertTrue(fallback, "выборка не должна казаться похожей на земли")


class TestSuggest(unittest.TestCase):
    def test_a_staple_and_a_signature_card_look_different(self):
        """Both are in every neighbouring deck; only one is rare elsewhere."""
        sample = sample_of(dragons=10, plain=30)
        result = cooccur.suggest(DRAGONS[:1], sample, near=10, min_share=0.1)
        by_name = {row["name"]: row for row in result["cards"]}

        staple = by_name["Sol Ring"]
        signature = by_name["Terror of the Peaks"]
        self.assertEqual(staple["near_share"], 1.0)
        self.assertEqual(signature["near_share"], 1.0)
        self.assertAlmostEqual(staple["lift"], 1.0, places=2)
        self.assertGreater(signature["lift"], 3.0)

    def test_what_you_already_play_is_not_suggested(self):
        sample = sample_of()
        result = cooccur.suggest(STAPLES + DRAGONS, sample, near=10, min_share=0.1)
        names = {row["name"] for row in result["cards"]}
        self.assertNotIn("Sol Ring", names)
        self.assertNotIn("Dragon Tempest", names)

    def test_the_commander_is_never_suggested(self):
        """Even for an empty deck: it is yours by definition."""
        sample = sample_of()
        sample["decks"]["d0"] = sample["decks"]["d0"] + [COMMANDER]
        result = cooccur.suggest([], sample, near=10, min_share=0.0,
                                 exclude=[COMMANDER])
        self.assertNotIn(COMMANDER, {row["name"] for row in result["cards"]})

    def test_a_thin_neighbourhood_is_admitted_not_hidden(self):
        """A deck too small to resemble anything gets the whole sample, said
        out loud -- not a top-30 of decks that merely came first."""
        sample = sample_of()
        result = cooccur.suggest(["Black Lotus"], sample, near=10)
        self.assertTrue(result["fallback"])

        few = cooccur.suggest(DRAGONS, sample, near=10)
        self.assertTrue(few["fallback"], "три карты -- это ещё не сходство")

    def test_an_empty_sample_is_not_an_error(self):
        result = cooccur.suggest(STAPLES, {"decks": {}}, near=10)
        self.assertEqual(result["cards"], [])
        self.assertEqual(result["decks"], 0)

    def test_a_russian_name_matches_the_english_sample(self):
        sample = sample_of()
        # "Удар Молнии" is not in the sample; the point is that normalisation
        # is applied to both sides rather than a raw string compare.
        result = cooccur.suggest(["сол ринг"], sample, near=10, min_share=0.1)
        self.assertIn("Sol Ring", {row["name"] for row in result["cards"]})
        result = cooccur.suggest(["Sol Ring"], sample, near=10, min_share=0.1)
        self.assertNotIn("Sol Ring", {row["name"] for row in result["cards"]})


class TestPairs(unittest.TestCase):
    def test_a_card_that_travels_with_another_is_found(self):
        sample = sample_of(dragons=10, plain=30)
        result = cooccur.pairs_for("Dragon Tempest", sample, min_together=2)
        by_name = {row["name"]: row for row in result["cards"]}
        self.assertEqual(result["with_card"], 10)
        self.assertEqual(by_name["Terror of the Peaks"]["share"], 1.0)
        self.assertGreater(by_name["Terror of the Peaks"]["lift"], 3.0)

    def test_a_card_in_almost_every_deck_is_flagged_as_such(self):
        """Pairs with a near-universal card are arithmetic, not a discovery."""
        sample = sample_of()
        result = cooccur.pairs_for("Sol Ring", sample, min_together=2)
        self.assertTrue(result["ubiquitous"])

        result = cooccur.pairs_for("Dragon Tempest", sample, min_together=2)
        self.assertFalse(result["ubiquitous"])

    def test_a_card_absent_from_the_sample_says_so(self):
        result = cooccur.pairs_for("Black Lotus", sample_of())
        self.assertEqual(result["with_card"], 0)
        self.assertEqual(result["cards"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
