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
from datetime import datetime, timedelta, timezone

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

    def one_deck(self, deck_id, min_cards=60):
        # Порог приходит от выборки: у командирской сотня разных карт, у
        # 60-карточной бывает два десятка. Заглушке он безразличен, но
        # принять его она обязана -- иначе проверка разойдётся с кодом.
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


# --------------------------------------------------------------------------- #
# Выборка по архетипу
#
# Проверяется то, из-за чего выборка и переписана: для 60-карточной колоды
# «весь модерн» -- это не её соседи, а все архетипы разом.
# --------------------------------------------------------------------------- #

class TestArchetypeKey(unittest.TestCase):

    def test_two_cards_become_one_key_whatever_the_order(self):
        one = archidekt.cards_key("modern", ["Thoughtseize", "The Rack"])
        two = archidekt.cards_key("modern", ["The Rack", "Thoughtseize"])
        self.assertEqual(one, two)
        self.assertEqual(archidekt._cache_path(one),
                         archidekt._cache_path(two))

    def test_the_search_asks_for_decks_that_run_all_of_them(self):
        """Повторённый cardName -- это И. Через запятую Archidekt не понимает."""
        key = archidekt.cards_key("modern", ["Thoughtseize", "The Rack"])
        url = archidekt.search_url(key, 1)
        self.assertIn("deckFormat=2", url)
        self.assertEqual(url.count("cardName="), 2)
        self.assertIn("cardName=The%20Rack", url)
        self.assertNotIn(",", url)

    def test_no_cards_means_the_whole_format(self):
        self.assertEqual(archidekt.cards_key("modern", []),
                         archidekt.format_key("modern"))

    def test_a_format_archidekt_does_not_serve_is_said_plainly(self):
        key = archidekt.cards_key("vintage", ["Black Lotus"])
        with self.assertRaises(archidekt.ArchidektError):
            archidekt.search_url(key, 1)

    def test_long_names_do_not_become_an_unwritable_filename(self):
        key = archidekt.cards_key("modern", [
            "Urza's Saga", "Wrenn and Six", "Lightning Bolt of a Very Long Name"])
        path = archidekt._cache_path(key)
        self.assertLess(len(os.path.basename(path)), 100)
        # Отпечаток берётся от ключа, так что два разных набора не сойдутся
        # в один файл.
        other = archidekt.cards_key("modern", [
            "Urza's Saga", "Wrenn and Six", "Lightning Bolt of Another Long Name"])
        self.assertNotEqual(path, archidekt._cache_path(other))


class TestNotFetchingWhatIsVisiblyUseless(unittest.TestCase):
    """Отсев по выдаче поиска: запрос, который можно не делать, не делается."""

    KEY = "cards:modern|Thoughtseize"

    def test_a_private_deck_is_skipped(self):
        self.assertEqual(
            archidekt._worth_fetching(self.KEY, {"private": True, "size": 75}),
            "private")

    def test_a_stub_is_skipped(self):
        self.assertEqual(
            archidekt._worth_fetching(self.KEY, {"size": 12}), "small")

    def test_a_deck_nobody_has_touched_for_years_is_skipped(self):
        row = {"size": 75, "updatedAt": "2021-09-19T04:46:41Z"}
        self.assertEqual(archidekt._worth_fetching(self.KEY, row), "old")

    def test_a_live_deck_is_fetched(self):
        row = {"size": 75,
               "updatedAt": datetime.now(timezone.utc).isoformat()}
        self.assertIsNone(archidekt._worth_fetching(self.KEY, row))

    def test_a_missing_date_is_not_held_against_the_deck(self):
        self.assertIsNone(
            archidekt._worth_fetching(self.KEY, {"size": 75, "updatedAt": None}))

    def test_a_commander_deck_is_judged_by_its_own_size(self):
        # Сотня карт -- норма для командирской колоды и перебор для
        # 60-карточной; один порог на оба случая невозможен.
        self.assertEqual(archidekt._worth_fetching("cmd:Tiamat", {"size": 60}),
                         "small")
        self.assertIsNone(archidekt._worth_fetching("cmd:Tiamat", {"size": 100}))


class TestOldAndNewCaches(unittest.TestCase):
    """Сотни уже скачанных колод не выбрасываются из-за формы записи."""

    def test_a_list_of_names_still_reads(self):
        self.assertEqual(archidekt.deck_main(["Bolt", "Bolt", "Island"]),
                         {"Bolt": 1, "Island": 1})
        self.assertEqual(archidekt.deck_side(["Bolt"]), {})

    def test_a_parsed_deck_keeps_copies_and_sideboard(self):
        entry = {"main": {"Bolt": 4}, "side": {"REB": 2}, "updated": "2026-10-01"}
        self.assertEqual(archidekt.deck_main(entry), {"Bolt": 4})
        self.assertEqual(archidekt.deck_side(entry), {"REB": 2})
        self.assertEqual(archidekt.deck_meta(entry)["updated"], "2026-10-01")

    def test_what_the_search_knew_is_kept_beside_the_cards(self):
        record = archidekt._as_record(
            {"main": {"Bolt": 4}, "side": {}},
            {"name": "Burn", "updated": "2026-10-01", "views": 12, "size": 75})
        self.assertEqual(record["main"], {"Bolt": 4})
        self.assertEqual(record["name"], "Burn")
        self.assertEqual(record["views"], 12)

    def test_freshness_is_measured_and_said(self):
        old = (datetime.now(timezone.utc) - timedelta(days=800)).isoformat()
        new = datetime.now(timezone.utc).isoformat()
        data = {"decks": {
            "1": {"main": {"a": 1}, "side": {}, "updated": old},
            "2": {"main": {"b": 1}, "side": {}, "updated": new},
            "3": ["c"],                       # старая запись -- даты нет
        }}
        fresh = archidekt.freshness(data)
        self.assertEqual(fresh["known"], 2)
        self.assertEqual(fresh["fresh_year"], 1)
        self.assertGreater(fresh["oldest_days"], 700)


class TestRefresh(unittest.TestCase):
    """Выборка должна уметь не только расти, но и обновляться."""

    KEY = "cards:modern|Refresh Test"

    def setUp(self):
        path = archidekt._cache_path(self.KEY)
        if os.path.exists(path):
            os.remove(path)
        old = (datetime.now(timezone.utc) - timedelta(days=900)).isoformat()
        new = datetime.now(timezone.utc).isoformat()
        data = archidekt.load(self.KEY)
        data["decks"] = {
            "1": {"main": {"a": 1}, "side": {}, "updated": old},
            "2": {"main": {"b": 1}, "side": {}, "updated": new},
            "3": ["c"],                      # запись старого кеша, без даты
        }
        data["ids"] = [1, 2, 3]
        data["pages_done"] = 6
        data["exhausted"] = True
        archidekt._save(self.KEY, data)

    def test_stale_decks_leave_and_fresh_ones_stay(self):
        got = archidekt.refresh(self.KEY)
        self.assertEqual(got["dropped"], 1)
        self.assertEqual(got["decks"], 2)
        self.assertNotIn("1", archidekt.load(self.KEY)["decks"])

    def test_a_dropped_deck_is_not_fetched_again(self):
        archidekt.refresh(self.KEY)
        data = archidekt.load(self.KEY)
        self.assertEqual(data["skipped"].get("1"), "old")
        self.assertNotIn(1, data["ids"])

    def test_decks_without_a_date_are_left_alone_and_counted(self):
        """Это записи старых сборов: выбросить их -- отправить качать заново."""
        got = archidekt.refresh(self.KEY)
        self.assertEqual(got["undated"], 1)
        self.assertIn("3", archidekt.load(self.KEY)["decks"])

    def test_the_search_starts_from_the_first_page_again(self):
        archidekt.refresh(self.KEY)
        data = archidekt.load(self.KEY)
        self.assertEqual(data["pages_done"], 0)
        self.assertFalse(data.get("exhausted"))


def sixty_sample():
    """Выборка 60-карточных колод: с копиями и сайдбордом."""
    decks = {}
    for i in range(12):
        decks["m%d" % i] = {
            "main": {"Thoughtseize": 4, "The Rack": 4, "Swamp": 20,
                     "Shrieking Affliction": 3 if i % 2 else 4},
            "side": {"Leyline of the Void": 3, "Fatal Push": 2},
            "updated": datetime.now(timezone.utc).isoformat(),
        }
    return {"decks": decks}


class TestCopies(unittest.TestCase):

    def test_a_card_you_run_short_of_is_pointed_out(self):
        result = cooccur.copies({"Thoughtseize": 2, "The Rack": 4},
                                sixty_sample(), near=12)
        rows = {r["name"]: r for r in result["cards"]}
        self.assertEqual(rows["Thoughtseize"]["usual"], 4)
        self.assertEqual(rows["Thoughtseize"]["diff"], 2)
        # То, чего у вас ровно столько же, в списке не стоит: это не совет.
        self.assertNotIn("The Rack", rows)

    def test_basics_are_not_counted(self):
        result = cooccur.copies({"Swamp": 4}, sixty_sample(), near=12)
        self.assertEqual(result["cards"], [])

    def test_a_card_too_few_neighbours_run_says_nothing(self):
        sample = sixty_sample()
        sample["decks"]["m0"]["main"]["Dismember"] = 2
        result = cooccur.copies({"Dismember": 1}, sample, near=12)
        self.assertNotIn("Dismember", {r["name"] for r in result["cards"]})

    def test_a_commander_sample_is_flat_and_says_so(self):
        """Там всё по одной копии, и разговор о числе копий бессмысленный."""
        result = cooccur.copies({"Sol Ring": 1}, sample_of(), near=10)
        self.assertTrue(result["flat"])


class TestSideboard(unittest.TestCase):

    def test_what_neighbours_keep_in_the_side_is_counted(self):
        result = cooccur.sideboard(["Thoughtseize", "The Rack"], ["Fatal Push"],
                                   sixty_sample(), near=12)
        self.assertEqual(result["known"], 12)
        rows = {r["name"]: r for r in result["cards"]}
        self.assertEqual(rows["Leyline of the Void"]["usual"], 3)
        self.assertFalse(rows["Leyline of the Void"]["mine"])
        # То, что уже лежит в вашем сайде, помечено -- и стоит в конце.
        self.assertTrue(rows["Fatal Push"]["mine"])
        self.assertEqual(result["cards"][-1]["name"], "Fatal Push")

    def test_an_old_sample_without_sideboards_says_so_instead_of_zero(self):
        """Пустой сайд и неизвестный сайд -- разные вещи."""
        result = cooccur.sideboard(["Sol Ring"], [], sample_of(), near=10)
        self.assertEqual(result["known"], 0)
        self.assertEqual(result["cards"], [])


def versus_sample():
    """Выборка, где одна колода отличается от остальных нарочно."""
    decks = {}
    for i in range(8):
        decks["m%d" % i] = {
            "main": {"Thoughtseize": 4, "The Rack": 4, "Swamp": 20,
                     "Shrieking Affliction": 4},
            "side": {"Leyline of the Void": 3},
            "name": "Rack %d" % i,
        }
    # Сосед, с которым и будем сравниваться: у него Dark Confidant вместо
    # Shrieking Affliction и три Rack вместо четырёх.
    decks["odd"] = {
        "main": {"Thoughtseize": 4, "The Rack": 3, "Swamp": 20,
                 "Dark Confidant": 4},
        "side": {"Leyline of the Void": 3, "Fatal Push": 2},
        "name": "Чужая колода",
        "updated": "2026-10-01T00:00:00Z",
    }
    return {"decks": decks}


class TestAgainstOneDeck(unittest.TestCase):
    """Ссылка на чужой список -- это не разница. Разницу считаем сами."""

    MINE = {"Thoughtseize": 4, "The Rack": 4, "Swamp": 20,
            "Shrieking Affliction": 4, "Bump in the Night": 2}

    def diff(self, **kw):
        return cooccur.against(self.MINE, "odd", versus_sample(), near=10, **kw)

    def test_what_they_have_and_you_do_not(self):
        rows = {r["name"]: r for r in self.diff()["theirs_only"]}
        self.assertIn("Dark Confidant", rows)
        # И сразу -- играет ли это кто-то ещё: одна колода может быть
        # и чудачеством.
        self.assertEqual(rows["Dark Confidant"]["others"], 0)
        self.assertEqual(rows["Dark Confidant"]["copies"], 4)

    def test_what_you_have_and_they_do_not(self):
        rows = {r["name"]: r for r in self.diff()["yours_only"]}
        # Shrieking Affliction есть у остальных восьми, Bump -- ни у кого.
        self.assertEqual(rows["Shrieking Affliction"]["others"], 8)
        self.assertEqual(rows["Bump in the Night"]["others"], 0)

    def test_what_nobody_else_plays_comes_first(self):
        """Карта, которой нет ни у одного соседа, -- главное в этой половине."""
        self.assertEqual(self.diff()["yours_only"][0]["name"],
                         "Bump in the Night")

    def test_different_counts_are_not_called_the_same(self):
        counts = {r["name"]: r for r in self.diff()["counts"]}
        self.assertEqual(counts["The Rack"], {"name": "The Rack", "mine": 4,
                                             "theirs": 3})

    def test_basic_lands_are_not_a_difference(self):
        for row in self.diff()["theirs_only"] + self.diff()["yours_only"]:
            self.assertNotEqual(row["name"], "Swamp")

    def test_their_sideboard_is_compared_with_yours(self):
        out = self.diff(side_counts={"Leyline of the Void": 3})
        rows = [r["name"] for r in out["side_only"]]
        self.assertEqual(rows, ["Fatal Push"])
        self.assertTrue(out["side_known"])

    def test_the_shared_count_and_the_link(self):
        out = self.diff()
        self.assertEqual(out["shared"], 2)          # Thoughtseize и The Rack
        self.assertEqual(out["name"], "Чужая колода")
        self.assertIn("archidekt.com/decks/odd", out["url"])
        self.assertEqual(out["updated"], "2026-10-01")

    def test_a_deck_outside_the_sample_is_not_invented(self):
        out = cooccur.against(self.MINE, "нет такой", versus_sample())
        self.assertFalse(out["found"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
