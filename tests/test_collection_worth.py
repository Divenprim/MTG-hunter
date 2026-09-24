"""Коллекция как имущество: чего она стоит и как это менялось.

Список имён с числами отвечает на вопрос «сколько», но не на «что» и не на
«почём». Здесь проверяется то, что к нему добавлено:

  * **карточные данные** -- картинка, печать, цена. Долларовая берётся из
    локальной базы (она есть почти у каждой карты) и потому считается по всей
    коллекции сразу, без единого запроса наружу;
  * **какая цена берётся.** Печать в коллекции не записана -- коллекция
    ведётся по именам, -- поэтому берётся самая дешёвая. Это нижняя граница, и
    называть её оценкой сверху было бы враньём;
  * **история.** Строка в день, а не на каждое открытие страницы: иначе
    «история» -- это журнал заходов, а не кривая стоимости;
  * **выгрузка.** Список текстом -- ровно в том виде, в каком коллекция
    вводится: то, что выгружено, должно вводиться обратно без правки.

Данных пользователя тесты не касаются: MTGH_DATA_DIR уводит их в свой каталог.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = tempfile.mkdtemp(prefix="mtgh-worth-")
os.environ["MTGH_DATA_DIR"] = _TMP

from app import collection as collection_store  # noqa: E402
from app import holdings  # noqa: E402
from app.cards import DB_PATH, CardDB  # noqa: E402
from tests.test_holdings import FakeStore, deck  # noqa: E402


class TestValueHistory(unittest.TestCase):
    def setUp(self):
        collection_store.reset_connection()
        conn = collection_store._conn()
        with conn:
            conn.execute("DELETE FROM collection_value")

    def test_a_day_keeps_one_row(self):
        """Страницу открывают десять раз в день -- строка должна остаться одна."""
        for usd in (10.0, 20.0, 30.0):
            collection_store.record_value(5, 9, usd, 700, 3)
        history = collection_store.value_history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["usd"], 30.0)

    def test_what_was_written_comes_back(self):
        collection_store.record_value(7, 12, 44.5, 1300, 4)
        row = collection_store.value_history()[0]
        self.assertEqual((row["cards"], row["copies"], row["usd"], row["rub"],
                          row["priced"]), (7, 12, 44.5, 1300, 4))

    def test_an_empty_history_is_an_empty_list(self):
        self.assertEqual(collection_store.value_history(), [])


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestEnrichedCards(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = CardDB()

    def report(self, collection, decks=(), prices=None):
        return holdings.report(FakeStore(list(decks)), collection, self.db,
                               prices or {})

    def test_a_card_brings_its_picture_and_printing(self):
        out = self.report({"Lightning Bolt": 4})
        card = out["cards"][0]
        self.assertTrue(card["known"])
        self.assertTrue(card["image_small"])
        self.assertTrue(card["set_code"])
        self.assertTrue(card["rarity"])

    def test_the_price_is_the_cheapest_printing(self):
        """Какая печать у вас -- неизвестно, поэтому берётся нижняя граница."""
        out = self.report({"Lightning Bolt": 1})
        mine = out["cards"][0]["usd"]
        every = [
            float(r["usd"]) for r in self.db.conn.execute(
                "SELECT CAST(json_extract(prices, '$.usd') AS REAL) AS usd "
                "FROM cards WHERE name = 'Lightning Bolt' "
                "AND json_extract(prices, '$.usd') IS NOT NULL")]
        self.assertAlmostEqual(mine, min(every), places=2)

    def test_a_stack_costs_as_much_as_it_holds(self):
        out = self.report({"Lightning Bolt": 4})
        card = out["cards"][0]
        self.assertAlmostEqual(card["usd_total"], card["usd"] * 4, places=2)

    def test_the_total_adds_up_the_stacks(self):
        out = self.report({"Lightning Bolt": 4, "Sol Ring": 2})
        mine = [c for c in out["cards"] if c["owned"]]
        self.assertAlmostEqual(out["totals"]["usd"],
                               round(sum(c["usd_total"] for c in mine), 2),
                               places=2)
        self.assertEqual(out["totals"]["usd_known"], 2)

    def test_roubles_are_counted_only_where_they_are_known(self):
        """Цена в рублях спрашивается у topdeck поштучно, и её знают не про всё."""
        out = self.report({"Lightning Bolt": 4, "Sol Ring": 2},
                          prices={"lightning bolt": {"rub_min": 150}})
        self.assertEqual(out["totals"]["rub"], 600)
        self.assertEqual(out["totals"]["rub_known"], 1)

    def test_a_card_the_base_does_not_know_is_marked_so(self):
        out = self.report({"Такой Карты Нет": 3})
        card = out["cards"][0]
        self.assertFalse(card["known"])
        self.assertIsNone(card["usd"])
        self.assertEqual(out["totals"]["usd"], 0)

    def test_cards_wanted_by_decks_do_not_inflate_the_worth(self):
        """Карта из колоды, которой на руках нет, стоимости не добавляет."""
        out = self.report({}, decks=[deck("d1", "колода",
                                          [("Lightning Bolt", 4, "main")])])
        self.assertEqual(out["totals"]["usd"], 0)
        self.assertEqual(out["totals"]["cards"], 0)
        self.assertEqual(out["cards"][0]["listed"], 4)


@unittest.skipUnless(os.path.exists(DB_PATH), "нет собранной базы карт")
class TestExport(unittest.TestCase):
    """Выгрузка через сам сервер: проверяется то, что получит человек."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient

        from app.main import app

        collection_store.reset_connection()
        collection_store.replace({"Lightning Bolt": 4, "Sol Ring": 1,
                                  "Fog, Bank": 2})
        cls.client = TestClient(app)

    @classmethod
    def tearDownClass(cls):
        collection_store.replace({})

    def test_the_text_list_is_what_the_import_expects(self):
        out = self.client.get("/api/collection/export").json()
        lines = [l for l in out["text"].splitlines() if l.strip()]
        self.assertEqual(len(lines), 3)
        for line in lines:
            count, name = line.split(" ", 1)
            self.assertTrue(count.isdigit(), line)
            self.assertTrue(name.strip(), line)
        self.assertIn("4 Lightning Bolt", lines)

    def test_it_says_how_much_it_gave_out(self):
        out = self.client.get("/api/collection/export").json()
        self.assertEqual(out["cards"], 3)
        self.assertEqual(out["copies"], 7)

    def test_the_csv_keeps_its_columns_when_a_name_has_a_comma(self):
        """«Fog, Bank» не должна разорвать строку на два столбца."""
        out = self.client.get("/api/collection/export?kind=csv").json()
        rows = out["text"].splitlines()
        head = rows[0].split(",")
        for row in rows[1:]:
            cells, cell, quoted = [], "", False
            for ch in row:
                if ch == '"':
                    quoted = not quoted
                elif ch == "," and not quoted:
                    cells.append(cell)
                    cell = ""
                else:
                    cell += ch
            cells.append(cell)
            self.assertEqual(len(cells), len(head), row)

    def test_the_history_endpoint_answers(self):
        out = self.client.get("/api/collection/value").json()
        self.assertIn("history", out)
        self.assertIsInstance(out["history"], list)


if __name__ == "__main__":
    unittest.main()
