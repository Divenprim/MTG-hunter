"""What was received, and what it actually cost.

The received orders were already being stored and never read. They are the one
place the program knows the price you *paid* -- a cached topdeck price from
March is not what you paid in March -- so the history has to be exact about
money and honest about dates it does not have.

The upgrade path matters as much as the numbers: a database written by the
previous version has no `received` column at all, and opening it must migrate
rather than fail.
"""

import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import collection, orders  # noqa: E402

# The schema as the previous version wrote it: no `received`.
OLD_SCHEMA = """
CREATE TABLE purchase_orders (
    id TEXT PRIMARY KEY, seller_name TEXT NOT NULL,
    seller_kind TEXT NOT NULL DEFAULT 'user',
    total INTEGER NOT NULL DEFAULT 0, created TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', fingerprint TEXT NOT NULL);
CREATE TABLE purchase_order_items (
    order_id TEXT NOT NULL, name_norm TEXT NOT NULL, name TEXT NOT NULL,
    quantity INTEGER NOT NULL, unit_price INTEGER NOT NULL DEFAULT 0,
    subtotal INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (order_id, name_norm));
"""


class HistoryCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data = os.environ.get("MTGH_DATA_DIR")
        os.environ["MTGH_DATA_DIR"] = self.tmp.name
        collection.reset_connection()
        orders.reset_connection()

    def tearDown(self):
        collection.reset_connection()
        orders.reset_connection()
        if self.old_data is None:
            os.environ.pop("MTGH_DATA_DIR", None)
        else:
            os.environ["MTGH_DATA_DIR"] = self.old_data
        self.tmp.cleanup()

    def db_path(self):
        return os.path.join(self.tmp.name, "user.sqlite")


class TestHistory(HistoryCase):
    def received_order(self, seller="seller-a", items=None):
        order_id = orders.create(seller, "user", items or [
            {"name": "Lightning Bolt", "quantity": 4, "unit_price": 150},
            {"name": "Sol Ring", "quantity": 1, "unit_price": 400},
        ])
        self.assertTrue(orders.receive(order_id))
        return order_id

    def test_a_received_order_leaves_the_pending_list_for_the_history(self):
        self.received_order()
        self.assertEqual(orders.list_pending(), [])
        hist = orders.history()
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["seller_name"], "seller-a")
        self.assertEqual(hist[0]["cards"], 5)

    def test_the_history_keeps_what_was_paid_per_card(self):
        self.received_order()
        items = {i["name"]: i for i in orders.history()[0]["items"]}
        self.assertEqual(items["Lightning Bolt"]["unit_price"], 150)
        self.assertEqual(items["Lightning Bolt"]["subtotal"], 600)
        self.assertEqual(orders.history()[0]["total"], 1000)

    def test_the_date_of_receiving_is_recorded(self):
        self.received_order()
        self.assertTrue(orders.history()[0]["received"])

    def test_the_totals_add_up(self):
        self.received_order("seller-a")
        self.received_order("seller-b", [
            {"name": "Cultivate", "quantity": 2, "unit_price": 60}])
        spent = orders.spent()
        self.assertEqual(spent["orders"], 2)
        self.assertEqual(spent["total"], 1120)
        self.assertEqual(spent["cards"], 7)
        self.assertEqual(spent["sellers"], 2)
        self.assertTrue(spent["first"] and spent["last"])

    def test_the_newest_order_comes_first(self):
        self.received_order("seller-a")
        self.received_order("seller-b", [
            {"name": "Cultivate", "quantity": 1, "unit_price": 60}])
        conn = orders._conn()
        with conn:
            conn.execute(
                "UPDATE purchase_orders SET received = '2020-01-01 00:00:00' "
                "WHERE seller_name = 'seller-a'")
        self.assertEqual([o["seller_name"] for o in orders.history()],
                         ["seller-b", "seller-a"])

    def test_a_pending_order_is_not_in_the_history(self):
        orders.create("seller-c", "user", [
            {"name": "Sol Ring", "quantity": 1, "unit_price": 400}])
        self.assertEqual(orders.history(), [])
        self.assertEqual(orders.spent()["orders"], 0)
        self.assertEqual(len(orders.list_pending()), 1)

    def test_removing_a_mark_does_not_leave_a_history_entry(self):
        order_id = orders.create("seller-c", "user", [
            {"name": "Sol Ring", "quantity": 1, "unit_price": 400}])
        self.assertTrue(orders.remove(order_id))
        self.assertEqual(orders.history(), [])

    def test_state_carries_the_history_with_the_pending_list(self):
        self.received_order()
        state = orders.state()
        self.assertEqual(state["orders"], [])
        self.assertEqual(len(state["history"]), 1)
        self.assertEqual(state["spent"]["total"], 1000)

    def test_history_can_be_left_out_when_it_is_not_wanted(self):
        self.received_order()
        state = orders.state(with_history=False)
        self.assertNotIn("history", state)


class TestPurchasesOfOneCard(HistoryCase):
    def setUp(self):
        super().setUp()
        first = orders.create("seller-a", "user", [
            {"name": "Lightning Bolt", "quantity": 4, "unit_price": 150}])
        orders.receive(first)
        second = orders.create("seller-b", "user", [
            {"name": "Lightning Bolt", "quantity": 1, "unit_price": 90}])
        orders.receive(second)

    def test_every_purchase_of_the_card_is_listed(self):
        rows = orders.purchases_of("Lightning Bolt")
        self.assertEqual(len(rows), 2)
        self.assertEqual({r["seller_name"] for r in rows}, {"seller-a", "seller-b"})
        self.assertEqual({r["unit_price"] for r in rows}, {150, 90})

    def test_the_name_is_matched_the_way_the_collection_stores_it(self):
        self.assertEqual(len(orders.purchases_of("lightning bolt")), 2)
        self.assertEqual(len(orders.purchases_of("  LIGHTNING BOLT  ")), 2)

    def test_a_card_never_bought_has_no_purchases(self):
        self.assertEqual(orders.purchases_of("Black Lotus"), [])
        self.assertEqual(orders.purchases_of(""), [])

    def test_a_pending_order_is_not_a_purchase_yet(self):
        orders.create("seller-c", "user", [
            {"name": "Black Lotus", "quantity": 1, "unit_price": 100000}])
        self.assertEqual(orders.purchases_of("Black Lotus"), [])


class TestUpgradeFromThePreviousVersion(HistoryCase):
    def setUp(self):
        super().setUp()
        conn = sqlite3.connect(self.db_path())
        conn.executescript(OLD_SCHEMA)
        conn.execute(
            "INSERT INTO purchase_orders "
            "(id, seller_name, seller_kind, total, created, status, fingerprint) "
            "VALUES ('old1', 'seller-b', 'user', 900, '2026-07-01 10:00:00', "
            "'received', 'ffff')")
        conn.execute(
            "INSERT INTO purchase_order_items VALUES "
            "('old1', 'lightning bolt', 'Lightning Bolt', 4, 150, 600)")
        conn.commit()
        conn.close()
        orders.reset_connection()

    def test_the_column_is_added_instead_of_failing(self):
        columns = {
            r["name"] for r in
            orders._conn().execute("PRAGMA table_info(purchase_orders)")
        }
        self.assertIn("received", columns)

    def test_an_order_received_before_the_column_existed_still_shows(self):
        """Without a date rather than with an invented one."""
        hist = orders.history()
        self.assertEqual(len(hist), 1)
        self.assertEqual(hist[0]["seller_name"], "seller-b")
        self.assertIsNone(hist[0]["received"])
        self.assertEqual(orders.spent()["total"], 900)
        self.assertEqual(orders.spent()["first"], "2026-07-01 10:00:00")

    def test_new_orders_work_on_the_migrated_database(self):
        order_id = orders.create("seller-a", "user", [
            {"name": "Sol Ring", "quantity": 1, "unit_price": 400}])
        self.assertTrue(orders.receive(order_id))
        self.assertEqual(len(orders.history()), 2)
        self.assertEqual(orders.spent()["orders"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
