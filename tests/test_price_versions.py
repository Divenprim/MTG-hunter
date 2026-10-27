"""Цена чего именно: печать, фойл, состояние.

Кеш цен вёлся по имени -- одна строка на карту. Это и есть та беда, из-за
которой «выгода» врала: по «700 ₽» не видно, убитая это копия, фойл или
обычная карта, а разница между ними -- вся разница между «выгодно» и «не та
вещь». Разобрать это можно только в момент узнавания цены, пока печать,
фойл и состояние ещё написаны в строке продавца.

Проверяется:

  * объявления складываются в версии, а не в кучу: одна версия -- одна
    строка, с самой дешёвой ценой и числом объявлений;
  * «цена обычной копии» считается отдельно и не путается с нижней ценой;
  * «неизвестно» не выдаётся за «обычная»: продавец, не написавший
    состояние, ничего не обещал;
  * повторное узнавание переписывает версии целиком -- то, чего в выдаче
    больше нет, сегодня не продаётся.

Настоящий topdeck не трогается: объявления собраны руками.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import deckbuild  # noqa: E402
from app.cards import normalize_name  # noqa: E402
from app.decks import DeckStore  # noqa: E402
from app.lineparse import SetIndex  # noqa: E402
from app.topdeck import Offer, Seller  # noqa: E402

SELLER = Seller(name="ПРОВЕРКА-Один", kind="user", city="Москва")


def offer(line, cost, name="Thoughtseize"):
    return Offer(name=name, eng_name=name, rus_name="", qty=1, cost=cost,
                 seller=SELLER, source="topdeck", url="https://example/1",
                 stamp="", line=line, city="Москва")


class TestSplittingOffers(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.index = SetIndex.load()

    def split(self, *offers):
        return deckbuild._variants(list(offers), self.index)

    def test_foil_and_plain_do_not_share_a_price(self):
        rows = self.split(offer("Thoughtseize 2XM NM", 900),
                          offer("Thoughtseize foil MM3 NM", 4200))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["rub_min"], 900)
        self.assertFalse(rows[0]["foil"])
        self.assertTrue(rows[1]["foil"])

    def test_condition_separates_too(self):
        rows = self.split(offer("Thoughtseize THS NM eng", 1200),
                          offer("Thoughtseize THS MP eng", 700))
        self.assertEqual({r["condition"] for r in rows}, {"NM", "MP"})

    def test_the_same_version_is_one_row_with_the_cheapest_price(self):
        rows = self.split(offer("Thoughtseize 2XM NM", 1100),
                          offer("Thoughtseize 2XM NM", 900))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["rub_min"], 900)
        self.assertEqual(rows[0]["rub_max"], 1100)
        self.assertEqual(rows[0]["offers"], 2)

    def test_offers_without_a_price_are_not_versions(self):
        rows = self.split(offer("Thoughtseize обмен", 0))
        self.assertEqual(rows, [])

    def test_without_a_set_index_nothing_is_invented(self):
        self.assertEqual(deckbuild._variants([offer("x", 10)], None), [])


class TestStoringVersions(unittest.TestCase):

    def setUp(self):
        fd, self.path = tempfile.mkstemp(suffix=".sqlite")
        os.close(fd)
        os.unlink(self.path)
        self.store = DeckStore(self.path)

    def tearDown(self):
        try:
            self.store.conn.close()
        except Exception:                                   # noqa: BLE001
            pass
        for suffix in ("", "-wal", "-shm"):
            try:
                os.unlink(self.path + suffix)
            except OSError:
                pass

    def variants(self, name="Thoughtseize"):
        return self.store.get_variants([name]).get(normalize_name(name), [])

    def price(self, name):
        return self.store.get_prices([name])[normalize_name(name)]

    def test_the_plain_price_is_not_the_floor(self):
        """Нижняя цена -- от убитой копии; обычная стоит своё."""
        self.store.store_price(
            "Thoughtseize", rub_min=700, rub_median=1100, offers=3,
            variants=[
                {"set_code": "ths", "foil": False, "condition": "MP",
                 "rub_min": 700, "offers": 1},
                {"set_code": "2xm", "foil": False, "condition": "NM",
                 "rub_min": 1100, "offers": 2},
            ])
        row = self.price("Thoughtseize")
        self.assertEqual(row["rub_min"], 700)
        self.assertEqual(row["rub_plain"], 1100)

    def test_a_foil_floor_does_not_become_the_plain_price(self):
        self.store.store_price(
            "Ragavan, Nimble Pilferer", rub_min=3000, rub_median=3000, offers=2,
            variants=[
                {"set_code": "mh2", "foil": True, "condition": "NM",
                 "rub_min": 3000, "offers": 1},
                {"set_code": "mh2", "foil": False, "condition": "NM",
                 "rub_min": 5200, "offers": 1},
            ])
        row = self.price("Ragavan, Nimble Pilferer")
        self.assertEqual(row["rub_plain"], 5200)

    def test_unknown_condition_counts_as_plain_but_is_kept_unknown(self):
        """Продавец не написал состояние -- обычно это NM, но обещать нельзя."""
        self.store.store_price(
            "Ponder", rub_min=50, rub_median=50, offers=1,
            variants=[{"set_code": "", "foil": False, "condition": "",
                       "rub_min": 50, "offers": 1}])
        row = self.price("Ponder")
        self.assertEqual(row["rub_plain"], 50)
        self.assertEqual(self.variants("Ponder")[0]["condition"], "")

    def test_without_versions_the_plain_price_stays_unknown(self):
        """Цена, узнанная старой версией: к чему она относится -- неизвестно."""
        self.store.store_price("Ponder", rub_min=50, rub_median=50, offers=1)
        row = self.price("Ponder")
        self.assertEqual(row["rub_min"], 50)
        self.assertIsNone(row["rub_plain"])

    def test_a_new_check_replaces_the_versions(self):
        self.store.store_price(
            "Thoughtseize", rub_min=700, rub_median=700, offers=1,
            variants=[{"set_code": "ths", "foil": False, "condition": "MP",
                       "rub_min": 700, "offers": 1}])
        self.store.store_price(
            "Thoughtseize", rub_min=1100, rub_median=1100, offers=1,
            variants=[{"set_code": "2xm", "foil": False, "condition": "NM",
                       "rub_min": 1100, "offers": 1}])
        rows = self.variants()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["set_code"], "2xm")

    def test_versions_come_back_cheapest_first(self):
        self.store.store_price(
            "Thoughtseize", rub_min=700, rub_median=900, offers=3,
            variants=[
                {"set_code": "mm3", "foil": True, "condition": "NM",
                 "rub_min": 4200, "offers": 1},
                {"set_code": "ths", "foil": False, "condition": "MP",
                 "rub_min": 700, "offers": 1},
            ])
        self.assertEqual([r["rub_min"] for r in self.variants()], [700, 4200])

    def test_plain_variant_knows_what_a_plain_copy_is(self):
        self.assertTrue(DeckStore.plain_variant({"foil": False, "condition": "NM"}))
        self.assertTrue(DeckStore.plain_variant({"foil": False, "condition": ""}))
        self.assertFalse(DeckStore.plain_variant({"foil": True, "condition": "NM"}))
        self.assertFalse(DeckStore.plain_variant({"foil": False, "condition": "HP"}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
