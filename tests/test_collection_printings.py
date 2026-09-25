"""Коллекция по печатям: не «четыре Молнии», а «две из MSC и две из M10».

Сканер печать знает -- он различает Ashaya из DSC и из CMM, -- а коллекция
раньше обе писала одной строкой «имя -- сколько». Печать терялась ровно в тот
момент, когда её узнали, и потом цена бралась у случайной печати.

Проверяется то, на чём это может тихо соврать:

  * **старые записи не пропадают.** У кого коллекция уже есть, она должна
    пережить переход: копии остаются, печать честно помечается неизвестной --
    выдумывать за пользователя сет нельзя, он потом увидит чужую цену;
  * **та же печать складывается, другая -- заводит свою строку;**
  * **сводка по именам не расходится со строками печатей.** Ею пользуются
    колоды и охота, и разъехаться они не должны даже на мгновение;
  * **снимки читаются оба вида** -- и старые словари, и новые строки: снимок,
    сделанный до перехода, обязан восстанавливаться и после.

Данных пользователя тесты не касаются: MTGH_DATA_DIR уводит их в свой каталог.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = tempfile.mkdtemp(prefix="mtgh-printings-")
os.environ["MTGH_DATA_DIR"] = _TMP

from app import collection as store  # noqa: E402
from app import holdings  # noqa: E402
from app.cards import DB_PATH, CardDB  # noqa: E402
from tests.test_holdings import FakeStore  # noqa: E402


class TestStacks(unittest.TestCase):
    def setUp(self):
        store.reset_connection()
        conn = store._conn()
        with conn:
            conn.execute("DELETE FROM collection_item")
            conn.execute("DELETE FROM collection")

    def test_a_printing_is_kept(self):
        store.add_items([{"name": "Lightning Bolt", "set_code": "MSC",
                          "collector_number": "806", "quantity": 2}])
        row = store.items()[0]
        self.assertEqual((row["set_code"], row["collector_number"], row["count"]),
                         ("msc", "806", 2))

    def test_the_same_printing_adds_up(self):
        for _ in range(3):
            store.add_items([{"name": "Lightning Bolt", "set_code": "msc",
                              "collector_number": "806", "quantity": 1}])
        self.assertEqual(len(store.items()), 1)
        self.assertEqual(store.items()[0]["count"], 3)

    def test_another_printing_is_its_own_row(self):
        store.add_items([
            {"name": "Lightning Bolt", "set_code": "msc",
             "collector_number": "806", "quantity": 2},
            {"name": "Lightning Bolt", "set_code": "m10",
             "collector_number": "146", "quantity": 1}])
        rows = store.items()
        self.assertEqual(len(rows), 2)
        self.assertEqual(sorted(r["count"] for r in rows), [1, 2])

    def test_a_card_without_a_printing_is_marked_unknown_not_guessed(self):
        """Выдумать сет -- значит показать цену чужой печати."""
        store.add_items([{"name": "Sol Ring", "quantity": 1}])
        self.assertEqual(store.items()[0]["set_code"], "")

    def test_the_name_summary_matches_the_stacks(self):
        store.add_items([
            {"name": "Lightning Bolt", "set_code": "msc",
             "collector_number": "806", "quantity": 2},
            {"name": "Lightning Bolt", "set_code": "m10",
             "collector_number": "146", "quantity": 3},
            {"name": "Sol Ring", "quantity": 1}])
        self.assertEqual(store.load(), {"Lightning Bolt": 5, "Sol Ring": 1})

    def test_the_display_name_stays_as_it_was_written(self):
        """Карту могли ввести по-русски -- переписывать её незачем."""
        store.add_items([{"name": "Удар Молнии", "quantity": 1}])
        store.add_items([{"name": "удар молнии", "set_code": "msc",
                          "collector_number": "806", "quantity": 1}])
        self.assertEqual(sorted(store.load()), ["Удар Молнии"])

    def test_the_text_list_keeps_printings(self):
        store.replace_items([
            {"name": "Lightning Bolt", "set_code": "MSC",
             "collector_number": "806", "quantity": 4}])
        self.assertEqual(store.items()[0]["set_code"], "msc")

    def test_replacing_by_name_forgets_printings_and_says_nothing_else(self):
        store.add_items([{"name": "Lightning Bolt", "set_code": "msc",
                          "collector_number": "806", "quantity": 4}])
        store.replace({"Lightning Bolt": 4})
        rows = store.items()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["set_code"], "")
        self.assertEqual(rows[0]["count"], 4)


class TestOldData(unittest.TestCase):
    """Коллекция, заведённая до перехода, обязана пережить его."""

    def setUp(self):
        store.reset_connection()
        conn = store._conn()
        with conn:
            conn.execute("DELETE FROM collection_item")
            conn.execute("DELETE FROM collection")

    def test_old_rows_become_stacks_without_a_printing(self):
        conn = store._conn()
        with conn:
            conn.execute(
                "INSERT INTO collection (name_norm, name, count, updated) "
                "VALUES ('opt','Opt',3,'2026-01-01 00:00:00')")
        store._migrate_items(conn)
        rows = store.items()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["name"], rows[0]["count"], rows[0]["set_code"]),
                         ("Opt", 3, ""))

    def test_migration_does_not_run_twice(self):
        store.add_items([{"name": "Opt", "quantity": 1}])
        conn = store._conn()
        with conn:
            conn.execute(
                "INSERT OR REPLACE INTO collection (name_norm, name, count, "
                "updated) VALUES ('brainstorm','Brainstorm',4,'2026-01-01')")
        store._migrate_items(conn)
        self.assertEqual([r["name"] for r in store.items()], ["Opt"])

    def test_a_new_snapshot_restores_with_its_printings(self):
        store.add_items([{"name": "Opt", "set_code": "khm",
                          "collector_number": "62", "quantity": 2}])
        store.replace({"Sol Ring": 1})          # снимок с Opt делается здесь
        newest = store.backups()[0]["id"]
        store.restore(newest)
        self.assertEqual(store.load(), {"Opt": 2})
        self.assertEqual(store.items()[0]["set_code"], "khm")

    def test_an_old_snapshot_is_a_dictionary_and_still_restores(self):
        """Снимок до перехода -- словарь «имя -- сколько». Читается и он."""
        from app.storage import snapshot

        snapshot(store._conn(), store.SNAPSHOT_KIND, {"Opt": 3}, "старый снимок")
        store.restore(store.backups()[0]["id"])
        self.assertEqual(store.load(), {"Opt": 3})
        self.assertEqual(store.items()[0]["set_code"], "")


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestWorthByPrinting(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()

    def report(self, stacks):
        collection = {}
        for row in stacks:
            collection[row["name"]] = collection.get(row["name"], 0) + row["count"]
        return holdings.report(FakeStore([]), collection, self.db, {},
                               stacks=stacks)

    def test_the_price_comes_from_the_printing_you_own(self):
        cheap = self.db.conn.execute(
            "SELECT set_code, collector_number, "
            "CAST(json_extract(prices,'$.usd') AS REAL) AS usd FROM cards "
            "WHERE name = 'Lightning Bolt' AND json_extract(prices,'$.usd') "
            "IS NOT NULL ORDER BY usd DESC LIMIT 1").fetchone()
        out = self.report([{"name": "Lightning Bolt", "count": 1,
                            "set_code": cheap["set_code"],
                            "collector_number": cheap["collector_number"]}])
        card = out["cards"][0]
        self.assertAlmostEqual(card["printings"][0]["usd"], cheap["usd"], places=2)
        self.assertAlmostEqual(card["usd_total"], cheap["usd"], places=2)

    def test_copies_without_a_printing_are_counted_at_the_floor(self):
        out = self.report([{"name": "Lightning Bolt", "count": 2,
                            "set_code": "", "collector_number": ""}])
        card = out["cards"][0]
        self.assertEqual(out["totals"]["copies_blind"], 2)
        self.assertEqual(out["totals"]["copies_exact"], 0)
        self.assertAlmostEqual(card["usd_total"], card["usd"] * 2, places=2)

    def test_both_kinds_add_up_in_one_row(self):
        out = self.report([
            {"name": "Lightning Bolt", "count": 1, "set_code": "msc",
             "collector_number": "806"},
            {"name": "Lightning Bolt", "count": 1, "set_code": "",
             "collector_number": ""}])
        card = out["cards"][0]
        self.assertEqual(len(card["printings"]), 2)
        self.assertEqual(card["usd_blind_copies"], 1)
        self.assertGreater(card["usd_total"], card["usd_exact"])

    def test_the_picture_shown_is_the_printing_you_own(self):
        out = self.report([{"name": "Lightning Bolt", "count": 1,
                            "set_code": "m10", "collector_number": "146"}])
        card = out["cards"][0]
        self.assertEqual((card["set_code"] or "").lower(), "m10")
        self.assertEqual(card["collector_number"], "146")


if __name__ == "__main__":
    unittest.main()
