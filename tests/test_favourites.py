"""Tests for the favourites wishlist.

Runs against a temporary MTGH_DATA_DIR, so it can never touch the real store.
That isolation is the point: a cleanup step once deleted the live
favourites.json because test data and real data shared a file.
"""

import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import favourites  # noqa: E402


class FavouritesTestCase(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.mkdtemp(prefix="mtgh-test-")
        self._saved = os.environ.get("MTGH_DATA_DIR")
        os.environ["MTGH_DATA_DIR"] = self._dir
        favourites.reset_connection()

    def tearDown(self):
        favourites.reset_connection()
        if self._saved is None:
            os.environ.pop("MTGH_DATA_DIR", None)
        else:
            os.environ["MTGH_DATA_DIR"] = self._saved
        shutil.rmtree(self._dir, ignore_errors=True)

    def first_folder(self, doc=None):
        return (doc or favourites.load())["folders"][0]


class TestDefaultFolder(FavouritesTestCase):
    def test_default_folder_is_persisted_with_a_stable_id(self):
        """Regression: an unsaved default folder got a new random id on every
        read, so adding a card always failed with "folder not found"."""
        first = self.first_folder()["id"]
        second = self.first_folder()["id"]
        self.assertEqual(first, second)

    def test_legacy_json_is_imported_and_kept_aside(self):
        """Nobody's existing favourites may be lost by the move to SQLite --
        and the old file is renamed, not deleted, in case the import is wrong."""
        import json

        legacy = os.path.join(self._dir, "favourites.json")
        with open(legacy, "w", encoding="utf-8") as fh:
            json.dump({"folders": [{
                "id": "abc123456789",
                "name": "Старое избранное",
                "created": "2026-01-01 00:00:00",
                "cards": [{"id": "c1", "name": "The Ur-Dragon", "quantity": 2}],
            }]}, fh, ensure_ascii=False)

        favourites.reset_connection()
        doc = favourites.load()
        names = [f["name"] for f in doc["folders"]]
        self.assertIn("Старое избранное", names)
        folder = next(f for f in doc["folders"] if f["name"] == "Старое избранное")
        self.assertEqual(folder["cards"][0]["name"], "The Ur-Dragon")
        self.assertEqual(folder["cards"][0]["quantity"], 2)
        self.assertFalse(os.path.exists(legacy))
        self.assertTrue(os.path.exists(legacy + ".imported"))


class TestFolders(FavouritesTestCase):
    def test_create_and_rename(self):
        doc = favourites.create_folder("Модерн")
        self.assertEqual(len(doc["folders"]), 2)
        fid = doc["folders"][1]["id"]
        doc = favourites.rename_folder(fid, "Модерн 2026")
        self.assertEqual(doc["folders"][1]["name"], "Модерн 2026")

    def test_duplicate_name_is_refused(self):
        favourites.create_folder("Дубль")
        with self.assertRaises(favourites.FavouritesError):
            favourites.create_folder("дубль")

    def test_blank_name_is_refused(self):
        with self.assertRaises(favourites.FavouritesError):
            favourites.create_folder("   ")

    def test_last_folder_cannot_be_deleted(self):
        with self.assertRaises(favourites.FavouritesError):
            favourites.delete_folder(self.first_folder()["id"])

    def test_delete_removes_the_folder(self):
        doc = favourites.create_folder("На выброс")
        fid = doc["folders"][1]["id"]
        doc = favourites.delete_folder(fid)
        self.assertEqual(len(doc["folders"]), 1)

    def test_unknown_folder_reports_readably(self):
        with self.assertRaises(favourites.FavouritesError):
            favourites.rename_folder("nope", "x")


class TestCards(FavouritesTestCase):
    def test_add_card(self):
        fid = self.first_folder()["id"]
        doc = favourites.add_card(fid, "Tiamat", quantity=2, set_code="afr",
                                  collector_number="235")
        card = doc["folders"][0]["cards"][0]
        self.assertEqual(card["name"], "Tiamat")
        self.assertEqual(card["quantity"], 2)
        self.assertEqual(card["set_code"], "afr")

    def test_same_card_same_printing_stacks(self):
        fid = self.first_folder()["id"]
        favourites.add_card(fid, "Sol Ring", quantity=1, set_code="c19",
                            collector_number="221")
        doc = favourites.add_card(fid, "Sol Ring", quantity=3, set_code="c19",
                                  collector_number="221")
        self.assertEqual(len(doc["folders"][0]["cards"]), 1)
        self.assertEqual(doc["folders"][0]["cards"][0]["quantity"], 4)

    def test_different_printing_is_a_separate_want(self):
        """A Secret Lair foil is not the same shopping item as the reprint."""
        fid = self.first_folder()["id"]
        favourites.add_card(fid, "Sol Ring", set_code="c19", collector_number="221")
        doc = favourites.add_card(fid, "Sol Ring", set_code="sld", collector_number="1")
        self.assertEqual(len(doc["folders"][0]["cards"]), 2)

    def test_unspecified_printing_stacks_separately_from_a_pinned_one(self):
        fid = self.first_folder()["id"]
        favourites.add_card(fid, "Sol Ring")
        doc = favourites.add_card(fid, "Sol Ring", set_code="c19", collector_number="221")
        self.assertEqual(len(doc["folders"][0]["cards"]), 2)

    def test_update_quantity_and_note(self):
        fid = self.first_folder()["id"]
        doc = favourites.add_card(fid, "Brainstorm")
        cid = doc["folders"][0]["cards"][0]["id"]
        doc = favourites.update_card(fid, cid, quantity=4, note="для леги")
        card = doc["folders"][0]["cards"][0]
        self.assertEqual(card["quantity"], 4)
        self.assertEqual(card["note"], "для леги")

    def test_quantity_never_drops_below_one(self):
        fid = self.first_folder()["id"]
        doc = favourites.add_card(fid, "Brainstorm")
        cid = doc["folders"][0]["cards"][0]["id"]
        doc = favourites.update_card(fid, cid, quantity=0)
        self.assertEqual(doc["folders"][0]["cards"][0]["quantity"], 1)

    def test_remove_card(self):
        fid = self.first_folder()["id"]
        doc = favourites.add_card(fid, "Counterspell")
        cid = doc["folders"][0]["cards"][0]["id"]
        doc = favourites.remove_card(fid, cid)
        self.assertEqual(doc["folders"][0]["cards"], [])

    def test_remove_unknown_card_reports_readably(self):
        with self.assertRaises(favourites.FavouritesError):
            favourites.remove_card(self.first_folder()["id"], "nope")

    def test_empty_name_is_refused(self):
        with self.assertRaises(favourites.FavouritesError):
            favourites.add_card(self.first_folder()["id"], "  ")


class TestMoveAndExport(FavouritesTestCase):
    def test_move_between_folders(self):
        src = self.first_folder()["id"]
        doc = favourites.create_folder("Потом")
        dst = doc["folders"][1]["id"]
        doc = favourites.add_card(src, "Ragavan, Nimble Pilferer", quantity=2)
        cid = doc["folders"][0]["cards"][0]["id"]

        doc = favourites.move_card(src, cid, dst)
        self.assertEqual(doc["folders"][0]["cards"], [])
        self.assertEqual(len(doc["folders"][1]["cards"]), 1)
        self.assertEqual(doc["folders"][1]["cards"][0]["quantity"], 2)

    def test_move_merges_when_the_target_already_has_it(self):
        src = self.first_folder()["id"]
        doc = favourites.create_folder("Потом")
        dst = doc["folders"][1]["id"]
        favourites.add_card(dst, "Sol Ring", quantity=1)
        doc = favourites.add_card(src, "Sol Ring", quantity=2)
        cid = doc["folders"][0]["cards"][0]["id"]

        doc = favourites.move_card(src, cid, dst)
        self.assertEqual(len(doc["folders"][1]["cards"]), 1)
        self.assertEqual(doc["folders"][1]["cards"][0]["quantity"], 3)

    def test_folder_as_wants_matches_the_hunt_shape(self):
        fid = self.first_folder()["id"]
        favourites.add_card(fid, "Lightning Bolt", quantity=4)
        wants = favourites.folder_as_wants(fid)
        self.assertEqual(wants, [
            {"name": "Lightning Bolt", "quantity": 4, "set_code": None, "section": "main"}
        ])

    def test_summary_counts_copies_across_folders(self):
        fid = self.first_folder()["id"]
        favourites.add_card(fid, "A", quantity=2)
        doc = favourites.create_folder("Вторая")
        favourites.add_card(doc["folders"][1]["id"], "B", quantity=3)
        s = favourites.summary()
        self.assertEqual(s["folders"], 2)
        self.assertEqual(s["cards"], 2)
        self.assertEqual(s["copies"], 5)


class TestBulkAdd(FavouritesTestCase):
    """Filing a dozen cards from a deck must be one call: 13 separate requests
    would be slow and could half-fail."""

    def test_bulk_add_into_an_existing_folder(self):
        fid = self.first_folder()["id"]
        doc, report = favourites.add_many(
            [{"name": "Lightning Bolt", "quantity": 2},
             {"name": "Tiamat", "quantity": 1}],
            folder_id=fid,
        )
        self.assertEqual(report["added"], 2)
        self.assertEqual(report["stacked"], 0)
        self.assertEqual(len(doc["folders"][0]["cards"]), 2)

    def test_bulk_add_creates_the_folder_by_name(self):
        doc, report = favourites.add_many(
            [{"name": "Sol Ring", "quantity": 3}], folder_name="Модерн"
        )
        self.assertEqual(report["folder_name"], "Модерн")
        self.assertEqual(len(doc["folders"]), 2)
        self.assertEqual(doc["folders"][1]["cards"][0]["quantity"], 3)

    def test_bulk_add_reuses_a_folder_with_that_name(self):
        favourites.create_folder("Модерн")
        doc, report = favourites.add_many(
            [{"name": "Sol Ring"}], folder_name="модерн"
        )
        self.assertEqual(len(doc["folders"]), 2, "must not create a duplicate")
        self.assertEqual(report["folder_name"], "Модерн")

    def test_bulk_add_stacks_onto_what_is_already_there(self):
        fid = self.first_folder()["id"]
        favourites.add_many([{"name": "Sol Ring", "quantity": 1}], folder_id=fid)
        doc, report = favourites.add_many(
            [{"name": "Sol Ring", "quantity": 2}], folder_id=fid
        )
        self.assertEqual(report["stacked"], 1)
        self.assertEqual(report["added"], 0)
        self.assertEqual(doc["folders"][0]["cards"][0]["quantity"], 3)

    def test_bulk_add_keeps_distinct_printings_apart(self):
        fid = self.first_folder()["id"]
        doc, _ = favourites.add_many(
            [{"name": "Sol Ring", "set_code": "c19", "collector_number": "221"},
             {"name": "Sol Ring", "set_code": "sld", "collector_number": "1"}],
            folder_id=fid,
        )
        self.assertEqual(len(doc["folders"][0]["cards"]), 2)

    def test_bulk_add_needs_cards(self):
        with self.assertRaises(favourites.FavouritesError):
            favourites.add_many([], folder_id=self.first_folder()["id"])

    def test_bulk_add_needs_a_folder(self):
        with self.assertRaises(favourites.FavouritesError):
            favourites.add_many([{"name": "Sol Ring"}])

    def test_bulk_add_skips_blank_names(self):
        fid = self.first_folder()["id"]
        doc, report = favourites.add_many(
            [{"name": "  "}, {"name": "Tiamat"}], folder_id=fid
        )
        self.assertEqual(report["added"], 1)
        self.assertEqual(len(doc["folders"][0]["cards"]), 1)


class TestBackups(FavouritesTestCase):
    """Every mutation leaves a snapshot, so a mistake is recoverable."""

    def test_a_snapshot_is_written_before_each_change(self):
        fid = self.first_folder()["id"]
        before = len(favourites.backups())
        favourites.add_card(fid, "Sol Ring")
        self.assertGreater(len(favourites.backups()), before)

    def test_restore_brings_a_deleted_card_back(self):
        fid = self.first_folder()["id"]
        favourites.add_card(fid, "Sol Ring", quantity=3)
        doc = favourites.add_card(fid, "Tiamat")
        card_id = doc["folders"][0]["cards"][0]["id"]

        favourites.remove_card(fid, card_id)
        self.assertEqual(len(favourites.load()["folders"][0]["cards"]), 1)

        # the newest snapshot is the state just before the removal
        newest = favourites.backups()[0]["id"]
        restored = favourites.restore(newest)
        names = {c["name"] for c in restored["folders"][0]["cards"]}
        self.assertEqual(names, {"Sol Ring", "Tiamat"})

    def test_restore_snapshots_the_current_state_too(self):
        fid = self.first_folder()["id"]
        favourites.add_card(fid, "Sol Ring")
        target = favourites.backups()[0]["id"]
        favourites.restore(target)
        reasons = [b["reason"] for b in favourites.backups()]
        self.assertIn("перед восстановлением", reasons)

    def test_restoring_a_missing_snapshot_is_a_readable_error(self):
        with self.assertRaises(favourites.FavouritesError):
            favourites.restore(999999)

    def test_deleting_a_folder_can_be_undone(self):
        """The exact accident that started this: a folder full of cards gone."""
        doc = favourites.create_folder("Модерн")
        fid = doc["folders"][1]["id"]
        favourites.add_card(fid, "Ragavan, Nimble Pilferer", quantity=1)
        favourites.delete_folder(fid)
        self.assertEqual(len(favourites.load()["folders"]), 1)

        newest = favourites.backups()[0]["id"]
        restored = favourites.restore(newest)
        names = [f["name"] for f in restored["folders"]]
        self.assertIn("Модерн", names)


if __name__ == "__main__":
    unittest.main(verbosity=2)
