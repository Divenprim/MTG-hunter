"""Замеры цены как ответ на вопрос «брать сейчас или подождать».

Цены в этой программе копятся сами: каждый ответ topdeck записывается
замером, рядом с нынешней ценой лежит прошлая. Проверяется здесь не то,
что числа складываются, а то, что из них делается вывод -- и только там,
где его можно сделать:

  * **«подешевело» -- это про прошлый замер**, а не про настроение: было
    90, стало 70, и в списке стоит именно столько;
  * **цель по цене считает программа.** Человек назвал цену, по которой
    готов купить; дальше его дело -- увидеть, что цена пришла, а не
    помнить, сколько он хотел;
  * **«дешевле обычного» требует трёх замеров.** По двум точкам виден не
    ход цены, а то, что её спросили дважды, и тогда здесь молчат;
  * **то, что внутри знакомого коридора, не зовётся находкой** -- 180 за
    карту, ходившую от 170 до 220, это обычный вторник.
"""

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = tempfile.mkdtemp(prefix="mtgh-moves-")
os.environ["MTGH_DATA_DIR"] = _TMP

from app import pricemoves                                  # noqa: E402
from app.decks import DeckStore                             # noqa: E402


class StoreCase(unittest.TestCase):
    """Общая заготовка: пустые цены и пустая история перед каждым разом."""

    def setUp(self):
        self.store = DeckStore()
        with self.store.conn:
            self.store.conn.execute("DELETE FROM price_cache")
            self.store.conn.execute("DELETE FROM price_history")

    def point(self, name, at, rub, median=None, offers=3):
        """Замер задним числом -- так, как он лёг бы в тот день."""
        with self.store.conn:
            self.store.conn.execute(
                "INSERT INTO price_history (name_norm, at, rub_min, rub_median, "
                "offers) VALUES (?,?,?,?,?) ON CONFLICT(name_norm, at) DO UPDATE "
                "SET rub_min = excluded.rub_min",
                (name.lower(), at, rub, median or rub * 2, offers))


class TestWhatChanged(StoreCase):
    """Что подешевело и что подорожало с прошлого замера."""

    def test_only_the_cards_that_moved_are_listed(self):
        self.store.store_price("Beast Within", 90, 120, 7)
        self.store.store_price("Beast Within", 70, 100, 6)
        self.store.store_price("Counterspell", 80, 90, 9)
        self.store.store_price("Counterspell", 80, 90, 9)
        moves = self.store.price_moves()
        self.assertEqual([m["name_norm"] for m in moves], ["beast within"])
        self.assertEqual(moves[0]["move"], -20)
        self.assertEqual(moves[0]["prev_rub_min"], 90)

    def test_the_biggest_fall_comes_first(self):
        for name, was, now in (("Cheap Thing", 100, 90),
                               ("Big Thing", 3000, 2000),
                               ("Dear Thing", 50, 400)):
            self.store.store_price(name, was, was * 2, 4)
            self.store.store_price(name, now, now * 2, 4)
        moves = self.store.price_moves()
        self.assertEqual(moves[0]["name_norm"], "big thing")
        self.assertEqual(moves[-1]["name_norm"], "dear thing")
        self.assertEqual(moves[0]["percent"], -33)

    def test_the_digest_counts_everything_and_shows_a_few(self):
        for i in range(9):
            self.store.store_price("Down %02d" % i, 100, 200, 4)
            self.store.store_price("Down %02d" % i, 80, 160, 4)
        self.store.store_price("Up One", 100, 200, 4)
        self.store.store_price("Up One", 130, 260, 4)
        digest = pricemoves.digest(self.store.price_moves(), show=3)
        self.assertEqual(digest["cheaper"], 9)
        self.assertEqual(digest["dearer"], 1)
        self.assertEqual(len(digest["down"]), 3)


class TestTheUsualLevel(StoreCase):
    """«Дешевле обычного» -- вывод из замеров, а не из одного числа."""

    def test_two_points_say_nothing(self):
        self.point("Lone Card", "2026-09-01", 200)
        self.point("Lone Card", "2026-09-20", 180)
        bands = self.store.price_bands(["Lone Card"])
        self.assertEqual(bands, {})
        self.assertEqual(pricemoves.unusual(150, bands.get("lone card")), {})

    def test_three_points_give_the_corridor(self):
        for at, rub in (("2026-08-01", 220), ("2026-09-01", 170),
                        ("2026-10-01", 200)):
            self.point("Known Card", at, rub)
        band = self.store.price_bands(["Known Card"])["known card"]
        self.assertEqual((band["low"], band["high"], band["points"]), (170, 220, 3))
        self.assertEqual(pricemoves.unusual(140, band)["verdict"], "cheap")

    def test_inside_the_corridor_is_not_a_find(self):
        for at, rub in (("2026-08-01", 220), ("2026-09-01", 170),
                        ("2026-10-01", 200)):
            self.point("Known Card", at, rub)
        band = self.store.price_bands(["Known Card"])["known card"]
        self.assertEqual(pricemoves.unusual(180, band)["verdict"], "usual")
        self.assertEqual(pricemoves.unusual(400, band)["verdict"], "dear")

    def test_a_hair_below_the_floor_is_still_the_usual_price(self):
        """Два процента ниже -- это округление у продавца, а не находка."""
        for at, rub in (("2026-08-01", 220), ("2026-09-01", 200),
                        ("2026-10-01", 210)):
            self.point("Known Card", at, rub)
        band = self.store.price_bands(["Known Card"])["known card"]
        self.assertEqual(pricemoves.unusual(196, band)["verdict"], "usual")


class TestTheNamedPrice(unittest.TestCase):
    """Цель по цене: человек назвал сумму, дальше смотрит программа."""

    def folders(self, *cards):
        return [{"id": "f1", "name": "Хочу купить",
                 "cards": [dict(c, id="c%d" % i) for i, c in enumerate(cards)]}]

    def test_a_card_at_or_below_the_named_price_is_a_hit(self):
        state = pricemoves.goals(
            self.folders({"name": "Beast Within", "target": 60, "quantity": 2},
                         {"name": "Counterspell", "target": 50}),
            {"beast within": {"rub_min": 40}, "counterspell": {"rub_min": 80}})
        self.assertEqual([r["name"] for r in state["hit"]], ["Beast Within"])
        self.assertEqual(state["hit"][0]["under"], 20)
        self.assertEqual([r["name"] for r in state["waiting"]], ["Counterspell"])

    def test_almost_there_is_said_separately(self):
        state = pricemoves.goals(
            self.folders({"name": "Close One", "target": 500}),
            {"close one": {"rub_min": 540}})
        self.assertEqual([r["name"] for r in state["near"]], ["Close One"])
        self.assertEqual(state["near"][0]["over"], 40)

    def test_a_card_without_a_price_is_not_called_expensive(self):
        state = pricemoves.goals(
            self.folders({"name": "Unknown Card", "target": 300}), {})
        self.assertEqual([r["name"] for r in state["unknown"]], ["Unknown Card"])
        self.assertEqual(state["waiting"], [])

    def test_cards_without_a_target_are_left_alone(self):
        state = pricemoves.goals(
            self.folders({"name": "Just Wanted"}, {"name": "Zero", "target": 0}),
            {"just wanted": {"rub_min": 10}})
        self.assertEqual(state["goals"], 0)

    def test_the_same_card_in_two_folders_keeps_two_targets(self):
        folders = [
            {"id": "f1", "name": "Фойл", "cards": [
                {"id": "a", "name": "Beast Within", "target": 2000}]},
            {"id": "f2", "name": "Игровая", "cards": [
                {"id": "b", "name": "Beast Within", "target": 50}]},
        ]
        state = pricemoves.goals(folders, {"beast within": {"rub_min": 60}})
        self.assertEqual([r["folder"] for r in state["hit"]], ["Фойл"])
        self.assertEqual([r["folder"] for r in state["waiting"]], ["Игровая"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
