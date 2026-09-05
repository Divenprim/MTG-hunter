"""Pending orders stay separate from owned cards until explicitly received."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import collection, orders  # noqa: E402


class TestPendingOrders(unittest.TestCase):
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

    @staticmethod
    def items():
        return [
            {"name": "Lightning Bolt", "quantity": 2, "unit_price": 150},
            {"name": "Sol Ring", "quantity": 1, "unit_price": 80},
        ]

    def test_order_is_pending_not_owned(self):
        order_id = orders.create("Seller", "user", self.items())
        self.assertTrue(order_id)
        self.assertEqual(collection.load(), {})
        self.assertEqual(orders.ordered_counts(), {"lightning bolt": 2, "sol ring": 1})
        self.assertEqual(orders.list_pending()[0]["total"], 380)

    def test_same_pending_order_is_idempotent(self):
        first = orders.create("Seller", "user", self.items())
        second = orders.create("Seller", "user", self.items())
        self.assertEqual(first, second)
        self.assertEqual(len(orders.list_pending()), 1)

    def test_same_card_at_two_prices_keeps_every_copy_and_the_exact_total(self):
        order_id = orders.create("Seller", "user", [
            {"name": "Lightning Bolt", "quantity": 1, "unit_price": 150},
            {"name": "Lightning Bolt", "quantity": 1, "unit_price": 155},
        ])
        saved = orders.list_pending()[0]
        self.assertEqual(saved["id"], order_id)
        self.assertEqual(saved["items"][0]["quantity"], 2)
        self.assertEqual(saved["total"], 305)

    def test_mark_can_be_removed_without_touching_collection(self):
        order_id = orders.create("Seller", "user", self.items())
        self.assertTrue(orders.remove(order_id))
        self.assertEqual(orders.list_pending(), [])
        self.assertEqual(collection.load(), {})

    def test_receive_adds_to_collection_exactly_once(self):
        collection.replace({"Lightning Bolt": 1})
        order_id = orders.create("Seller", "user", self.items())
        self.assertTrue(orders.receive(order_id))
        self.assertFalse(orders.receive(order_id))
        self.assertEqual(
            collection.load(), {"Lightning Bolt": 3, "Sol Ring": 1}
        )
        self.assertEqual(orders.list_pending(), [])


if __name__ == "__main__":
    unittest.main()
