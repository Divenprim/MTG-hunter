"""Pending orders stay separate from owned cards until explicitly received."""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import collection, orders, undo  # noqa: E402


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

    def test_a_received_order_survives_the_next_edit(self):
        """Полученный заказ пропадал от первой же отсканированной карты.

        Получение писало в сводную таблицу, а она не источник правды:
        `_resum` пересобирает её из строк печатей при каждой правке
        коллекции. Всё записанное мимо источника стиралось первой же
        правкой -- молча, со следом только в снимке, о котором никто не знает.

        Тесты этого не ловили, потому что смотрели коллекцию через ту же
        сводку, которую ошибочный код и заполнял: ни один не добавлял карту
        ПОСЛЕ получения заказа.
        """
        # В коллекции уже должна быть хоть одна строка печати: на пустой
        # беда не воспроизводится. Перенос старых строк срабатывает только
        # когда строк печатей нет вовсе, и он-то случайно и спасал данные --
        # из-за чего первая версия этого теста проходила и на сломанном коде.
        collection.replace_items([
            {"name": "Lightning Bolt", "set_code": "m10",
             "collector_number": "146", "finish": "foil", "count": 2},
        ])
        order_id = orders.create("Seller", "user", self.items())
        self.assertTrue(orders.receive(order_id))
        self.assertIn("Sol Ring", collection.load())

        collection.add_items([{"name": "Island", "quantity": 1}])
        self.assertIn("Sol Ring", collection.load(),
                      "полученный заказ стёрся при добавлении другой карты")

    def test_undoing_a_receipt_keeps_printings(self):
        """Отмена получения обнуляла сет, номер и фойл у всей коллекции.

        Снимок снимался со сводки -- словаря «имя -- сколько», -- а она про
        печати ничего не знает. Восстановление из такого снимка переписывало
        коллекцию без печатей: ровно то, ради чего её и переводили на
        построчный учёт.
        """
        collection.replace_items([
            {"name": "Lightning Bolt", "set_code": "m10",
             "collector_number": "146", "finish": "foil", "count": 2},
        ])
        order_id = orders.create("Seller", "user", self.items())
        self.assertTrue(orders.receive(order_id))
        undo.undo("receive")

        kept = [i for i in collection.items() if i["name"] == "Lightning Bolt"]
        self.assertEqual(len(kept), 1, collection.items())
        self.assertEqual(kept[0]["set_code"], "m10", "печать стёрлась")
        self.assertEqual(kept[0]["collector_number"], "146")
        self.assertEqual(kept[0]["finish"], "foil")

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
