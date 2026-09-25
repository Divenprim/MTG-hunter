"""Цены понемногу и история цены.

Спросить цену у topdeck -- это запрос на карту. Для колоды нажать кнопку не
жалко; для коллекции в две тысячи это сорок минут стука в чужой сервер, и так
не делают. Поэтому дополнение медленное -- и проверяется здесь то, что делает
его приличным:

  * **пока выключено, наружу не уходит ничего.** Это главное обещание;
  * **очередь по делу**: сперва карты без цены, потом те, что давно не
    проверялись; свежие не трогаются вовсе;
  * **пауза настоящая**, и первая -- до первого запроса, а не после: программа
    открылась -- в эту же секунду наружу никто не стучится;
  * **чужая ошибка не роняет работу**: сервер мог икнуть, и это повод подождать
    подольше, а не бросить дело.

И про историю: замер в день, старое прореживается. Сорок записей на карту --
это единицы мегабайт на всю коллекцию, пятьсот -- сотни ни за чем.

Сети здесь нет: topdeck заменён поддельным опросом, который просто записывает,
о чём его спросили.
"""

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_TMP = tempfile.mkdtemp(prefix="mtgh-watch-")
os.environ["MTGH_DATA_DIR"] = _TMP

from app import pricewatch  # noqa: E402
from app.decks import DeckStore  # noqa: E402


class Asked:
    """Поддельный опрос цен: помнит, о чём спрашивали, и ставит цену."""

    def __init__(self, fail_times: int = 0, price: int = 100):
        self.batches: list[list[str]] = []
        self.fail_times = fail_times
        self.price = price

    def __call__(self, names, store, db, client):
        names = list(names)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise RuntimeError("topdeck не ответил")
        self.batches.append(names)
        for name in names:
            store.store_price(name, self.price, self.price * 2, 5)
        return {"updated": len(names)}

    @property
    def asked(self) -> list[str]:
        return [name for batch in self.batches for name in batch]


class WatchCase(unittest.TestCase):
    """Общее для всех: чистая база и ни одного забытого потока.

    Забытый поток -- это не мелочь: он продолжает ходить в базу, и следующая
    же запись упирается в «database is locked». Поэтому каждый заведённый здесь
    наблюдатель останавливается и дожидается.
    """

    # Хранилище одно на весь модуль. Заводить по новому на каждый тест значит
    # держать несколько соединений к одному файлу, и они начинают ждать друг
    # друга: SQLite пишет по одному.
    store = DeckStore()

    def setUp(self):
        with self.store.conn:
            self.store.conn.execute("DELETE FROM price_cache")
            self.store.conn.execute("DELETE FROM price_history")
        self.watchers = []

    def tearDown(self):
        for watch in self.watchers:
            watch.stop()
            watch.join()

    def watcher(self, asked, names, pause=0.05):
        watch = pricewatch.PriceWatch(asked, lambda: names, lambda: self.store,
                                      lambda: None, lambda: None, pause=pause)
        self.watchers.append(watch)
        return watch


class TestQueue(WatchCase):

    def test_cards_without_a_price_come_first(self):
        self.store.store_price("Known Card", 50, 60, 2)
        watch = self.watcher(Asked(), ["Known Card", "Unknown Card"])
        self.assertEqual(watch.pending()[0], "Unknown Card")

    def test_a_fresh_price_is_left_alone(self):
        self.store.store_price("Known Card", 50, 60, 2)
        watch = self.watcher(Asked(), ["Known Card"])
        self.assertEqual(watch.pending(), [])

    def test_a_stale_price_comes_back_into_the_queue(self):
        long_ago = time.strftime(
            "%Y-%m-%d %H:%M:%S",
            time.localtime(time.time() - (pricewatch.STALE_DAYS + 5) * 86400))
        self.store.store_price("Old Card", 50, 60, 2)
        with self.store.conn:
            self.store.conn.execute(
                "UPDATE price_cache SET checked_at = ? WHERE name_norm = ?",
                (long_ago, "old card"))
        watch = self.watcher(Asked(), ["Old Card"])
        self.assertEqual(watch.pending(), ["Old Card"])


class TestRunning(WatchCase):
    def setUp(self):
        super().setUp()
        self.names = ["Card %02d" % i for i in range(1, 16)]

    def test_nothing_goes_out_until_it_is_turned_on(self):
        """Главное обещание: выключено -- значит выключено."""
        asked = Asked()
        watch = self.watcher(asked, self.names)
        time.sleep(0.3)
        self.assertEqual(asked.asked, [])
        self.assertFalse(watch.status()["running"])

    def test_the_first_request_waits_for_the_pause(self):
        asked = Asked()
        watch = self.watcher(asked, self.names, pause=0.6)
        watch.start()
        time.sleep(0.2)
        self.assertEqual(asked.asked, [], "запрос ушёл раньше паузы")
        watch.stop()

    def test_it_asks_in_small_batches_and_stops_when_done(self):
        asked = Asked()
        watch = self.watcher(asked, self.names)
        watch.start()
        for _ in range(60):
            if not watch.status()["running"]:
                break
            time.sleep(0.1)
        self.assertEqual(sorted(asked.asked), sorted(self.names))
        self.assertTrue(all(len(b) <= pricewatch.BATCH for b in asked.batches),
                        [len(b) for b in asked.batches])
        self.assertFalse(watch.status()["running"])

    def test_turning_it_off_stops_it(self):
        asked = Asked()
        watch = self.watcher(asked, self.names, pause=0.25)
        watch.start()
        time.sleep(0.4)
        watch.stop()
        asked.batches = []
        time.sleep(0.6)
        self.assertEqual(asked.batches, [], "после выключения всё равно спросил")

    def test_a_failure_is_remembered_and_work_continues(self):
        asked = Asked(fail_times=1)
        watch = self.watcher(asked, self.names[:6], pause=0.05)
        watch.start()
        for _ in range(80):
            if asked.asked:
                break
            time.sleep(0.05)
        watch.stop()
        self.assertTrue(asked.asked, "после ошибки работа не возобновилась")
        self.assertIn("topdeck", watch.status()["last_error"])


class TestHistory(WatchCase):

    def test_a_price_check_writes_a_point(self):
        self.store.store_price("Lightning Bolt", 100, 150, 12)
        points = self.store.price_history("Lightning Bolt")
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["rub_min"], 100)

    def test_the_same_day_is_one_point(self):
        """Цена не меняется по часам -- полсотни строк за вторник не нужны."""
        for price in (100, 90, 80):
            self.store.store_price("Lightning Bolt", price, 150, 12)
        points = self.store.price_history("Lightning Bolt")
        self.assertEqual(len(points), 1)
        self.assertEqual(points[0]["rub_min"], 80)

    def test_a_card_nobody_sells_is_not_recorded(self):
        """Цены нет -- и записывать нечего: ноль это не цена."""
        self.store.store_price("Nobody Sells This", None, None, 0)
        self.assertEqual(self.store.price_history("Nobody Sells This"), [])

    def test_old_points_are_thinned_out_to_one_a_month(self):
        with self.store.conn:
            for day in range(1, 400):
                at = time.strftime("%Y-%m-%d",
                                   time.localtime(time.time() - day * 86400))
                self.store.conn.execute(
                    "INSERT OR REPLACE INTO price_history (name_norm, at, "
                    "rub_min, rub_median, offers) VALUES (?,?,?,?,?)",
                    ("bolt", at, 100 + day, 150, 5))
        self.store._prune_history("bolt")
        points = self.store.price_history("Bolt", limit=999)
        self.assertLessEqual(len(points), 40)
        months = {p["at"][:7] for p in points}
        self.assertGreater(len(months), 6, "история сжалась до пары месяцев")

    def test_recent_days_survive_the_thinning(self):
        with self.store.conn:
            for day in range(0, 120):
                at = time.strftime("%Y-%m-%d",
                                   time.localtime(time.time() - day * 86400))
                self.store.conn.execute(
                    "INSERT OR REPLACE INTO price_history (name_norm, at, "
                    "rub_min, rub_median, offers) VALUES (?,?,?,?,?)",
                    ("bolt", at, 100, 150, 5))
        self.store._prune_history("bolt")
        points = [p["at"] for p in self.store.price_history("Bolt", limit=999)]
        today = time.strftime("%Y-%m-%d")
        self.assertIn(today, points)
        fresh = [at for at in points
                 if at >= time.strftime("%Y-%m-%d",
                                        time.localtime(time.time() - 20 * 86400))]
        self.assertGreaterEqual(len(fresh), 20, "свежие дни поредели")


if __name__ == "__main__":
    unittest.main()
