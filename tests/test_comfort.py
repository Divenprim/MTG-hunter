"""Отмена, «что нового», прошлая цена и «уже в пути».

Всё это про удобство, но проверять тут нечего кроме честности:

  * отмена должна возвращать ровно то, что было, и сама быть отменяемой;
  * получение заказа меняет две вещи сразу, значит и отменяться должно
    целиком, иначе карты останутся в коллекции, а заказ исчезнет;
  * прошлая цена не должна стираться проверкой, которая ничего не изменила;
  * «уже в пути» вычитается только когда попросили: карта в посылке — это не
    карта на руках.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import collection as collection_store  # noqa: E402
from app import favourites, orders, undo, whatsnew  # noqa: E402
from app.decks import DeckStore  # noqa: E402
from app.hunt import Want, compute_wants  # noqa: E402


class UserDataCase(unittest.TestCase):
    """Своя папка данных на каждый тест: настоящие данные не трогаем."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old = os.environ.get("MTGH_DATA_DIR")
        os.environ["MTGH_DATA_DIR"] = self.tmp.name
        collection_store.reset_connection()
        orders.reset_connection()
        favourites.reset_connection()

    def tearDown(self):
        collection_store.reset_connection()
        orders.reset_connection()
        favourites.reset_connection()
        if self.old is None:
            os.environ.pop("MTGH_DATA_DIR", None)
        else:
            os.environ["MTGH_DATA_DIR"] = self.old
        self.tmp.cleanup()


class TestUndoFavourites(UserDataCase):
    def folder(self, name="Тест"):
        state = favourites.create_folder(name)
        return next(f for f in state["folders"] if f["name"] == name)["id"]

    def test_a_deleted_folder_comes_back_with_its_cards(self):
        fid = self.folder()
        favourites.add_card(fid, name="Sol Ring", quantity=2)
        before = len(favourites.load()["folders"])

        favourites.delete_folder(fid)
        self.assertEqual(len(favourites.load()["folders"]), before - 1)

        undo.undo("favourites")
        after = favourites.load()["folders"]
        self.assertEqual(len(after), before)
        restored = next(f for f in after if f["name"] == "Тест")
        self.assertEqual(len(restored["cards"]), 1)
        self.assertEqual(restored["cards"][0]["quantity"], 2)

    def test_the_undo_is_itself_undoable(self):
        """Иначе промах по «Отменить» — это новая потеря."""
        fid = self.folder()
        favourites.add_card(fid, name="Sol Ring", quantity=1)
        favourites.delete_folder(fid)
        undo.undo("favourites")
        self.assertIn("Тест", [f["name"] for f in favourites.load()["folders"]])

        undo.undo("favourites")
        self.assertNotIn("Тест", [f["name"] for f in favourites.load()["folders"]])


class TestUndoCollection(UserDataCase):
    def test_a_replaced_collection_comes_back(self):
        collection_store.replace({"Sol Ring": 3})
        collection_store.replace({"Lightning Bolt": 1})
        self.assertEqual(collection_store.load(), {"Lightning Bolt": 1})

        undo.undo("collection")
        self.assertEqual(collection_store.load(), {"Sol Ring": 3})


class TestUndoOrders(UserDataCase):
    def order(self, seller="seller-a", name="Sol Ring", price=400):
        return orders.create(seller, "user", [
            {"name": name, "quantity": 1, "unit_price": price}])

    def test_a_removed_mark_comes_back_whole(self):
        self.order()
        pending = orders.list_pending()
        orders.remove(pending[0]["id"])
        self.assertEqual(orders.list_pending(), [])

        undo.undo("orders")
        back = orders.list_pending()
        self.assertEqual(len(back), 1)
        self.assertEqual(back[0]["seller_name"], "seller-a")
        self.assertEqual(back[0]["total"], 400)
        self.assertEqual(back[0]["items"][0]["name"], "Sol Ring")

    def test_receiving_is_undone_on_both_sides(self):
        """Иначе карты остались бы в коллекции, а заказ исчез."""
        order_id = self.order(name="Cultivate", price=60)
        orders.receive(order_id)
        self.assertEqual(collection_store.load(), {"Cultivate": 1})
        self.assertEqual(orders.list_pending(), [])
        self.assertEqual(len(orders.history()), 1)

        undo.undo("receive")
        self.assertEqual(collection_store.load(), {})
        self.assertEqual(len(orders.list_pending()), 1)

    def test_what_cannot_be_undone_says_so(self):
        with self.assertRaises(undo.UndoError):
            undo.undo("topdeck-request")
        with self.assertRaises(undo.UndoError):
            undo.undo("orders")      # ещё нечего отменять


class TestUndoAvailability(UserDataCase):
    def test_it_lists_only_what_has_a_snapshot(self):
        self.assertEqual(undo.available(), [])
        collection_store.replace({"Sol Ring": 1})
        kinds = [row["kind"] for row in undo.available()]
        self.assertEqual(kinds, ["collection"])

    def test_the_newest_change_is_first(self):
        collection_store.replace({"Sol Ring": 1})
        favourites.create_folder("Тест")
        self.assertEqual(undo.available()[0]["kind"], "favourites")


class TestWhatsNew(unittest.TestCase):
    def test_a_fresh_install_gets_one_entry_not_the_whole_history(self):
        self.assertEqual(len(whatsnew.since(None)), 1)
        self.assertEqual(len(whatsnew.since("0.0.1")), 1)

    def test_everything_newer_than_what_was_seen(self):
        versions = [e["version"] for e in whatsnew.NOTES]
        seen = versions[2]
        self.assertEqual([e["version"] for e in whatsnew.since(seen)], versions[:2])

    def test_the_current_version_is_covered(self):
        """Иначе обновление молчит именно про то, что изменилось."""
        from app.main import app

        self.assertIsNotNone(
            whatsnew.notes_for(app.version),
            "нет записи про версию %s" % app.version)

    def test_versions_compare_as_numbers_not_strings(self):
        self.assertTrue(whatsnew.is_newer("1.10.0", "1.9.0"))
        self.assertFalse(whatsnew.is_newer("1.9.0", "1.10.0"))
        self.assertFalse(whatsnew.is_newer("1.5.0", "1.5.0"))
        self.assertTrue(whatsnew.is_newer("1.5.0", None))

    def test_the_notes_are_not_empty(self):
        for entry in whatsnew.NOTES:
            self.assertTrue(entry["lines"], entry["version"])
            self.assertTrue(entry["title"], entry["version"])


class TestPreviousPrice(unittest.TestCase):
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
        if os.path.exists(self.path):
            os.unlink(self.path)

    def price(self, name="Sol Ring"):
        return self.store.get_prices([name])[name.lower()]

    def test_the_first_price_has_no_previous_one(self):
        self.store.store_price("Sol Ring", 90, 100, 3)
        self.assertIsNone(self.price()["prev_rub_min"])

    def test_a_changed_price_remembers_the_old_one(self):
        self.store.store_price("Sol Ring", 90, 100, 3)
        self.store.store_price("Sol Ring", 70, 80, 4)
        row = self.price()
        self.assertEqual(row["rub_min"], 70)
        self.assertEqual(row["prev_rub_min"], 90)
        self.assertTrue(row["prev_checked_at"])

    def test_an_unchanged_price_does_not_erase_the_old_one(self):
        """«Было 90» должно пережить проверку, сказавшую «всё ещё 70»."""
        self.store.store_price("Sol Ring", 90, 100, 3)
        self.store.store_price("Sol Ring", 70, 80, 4)
        self.store.store_price("Sol Ring", 70, 80, 4)
        self.assertEqual(self.price()["prev_rub_min"], 90)

    def test_going_up_is_remembered_too(self):
        self.store.store_price("Sol Ring", 70, 80, 4)
        self.store.store_price("Sol Ring", 120, 130, 2)
        row = self.price()
        self.assertEqual(row["rub_min"], 120)
        self.assertEqual(row["prev_rub_min"], 70)


class TestOrderedWants(unittest.TestCase):
    @staticmethod
    def deck():
        return [
            Want(name="Sol Ring", quantity=4, section="main"),
            Want(name="Cultivate", quantity=2, section="main"),
        ]

    def test_ordered_copies_are_only_subtracted_when_asked(self):
        wants = compute_wants(self.deck(), {}, ordered={"sol ring": 3})
        by_name = {w.name: w.quantity for w in wants}
        self.assertEqual(by_name["Sol Ring"], 1)
        self.assertEqual(by_name["Cultivate"], 2)

        # Без ordered поведение прежнее: ищем всё.
        wants = compute_wants(self.deck(), {})
        self.assertEqual({w.name: w.quantity for w in wants}["Sol Ring"], 4)

    def test_owned_and_ordered_add_up(self):
        wants = compute_wants(self.deck(), {"Sol Ring": 2}, ordered={"sol ring": 1})
        self.assertEqual({w.name: w.quantity for w in wants}["Sol Ring"], 1)

    def test_a_card_fully_covered_drops_out_of_the_list(self):
        wants = compute_wants(self.deck(), {}, ordered={"sol ring": 4})
        self.assertEqual([w.name for w in wants], ["Cultivate"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
