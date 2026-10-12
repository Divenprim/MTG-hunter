"""Последняя охота переживает закрытие вкладки.

Поиск предложений -- самое дорогое действие программы: он ходит к чужому сайту
с задержкой в полторы секунды на карту, и программа сама объясняет, что это
вежливость, а не медлительность. Терять такой результат от закрытия вкладки
нельзя: повторить его -- значит дёрнуть магазин ради того, что уже спрашивали.

Раньше результат жил только в открытой вкладке браузера. Человек, проверявший
программу впервые, потратил на это единственный разрешённый поиск и остался ни
с чем -- и, что показательно, не стал гонять второй раз, потому что это
неправильно по отношению к сайту.

Здесь проверяется, что ответ действительно кладётся рядом с остальными данными
человека и возвращается оттуда. Сам поиск не запускается: наружу эти тесты не
ходят никогда.
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestLastHunt(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        kept = os.environ.get("MTGH_DATA_DIR")
        os.environ["MTGH_DATA_DIR"] = self.dir.name

        def give_back():
            if kept is None:
                os.environ.pop("MTGH_DATA_DIR", None)
            else:
                os.environ["MTGH_DATA_DIR"] = kept

        self.addCleanup(give_back)
        from app import main
        self.main = main

    def test_nothing_is_remembered_at_first(self):
        self.assertEqual(self.main.hunt_last(), {"known": False})

    def test_it_lives_with_the_rest_of_the_user_data(self):
        """Не в папке программы, а там, куда указывает MTGH_DATA_DIR.

        Иначе тесты пишут в настоящие данные человека -- ровно то, ради чего
        эта переменная и заведена.
        """
        where = self.main.last_hunt_file()
        self.assertTrue(where.startswith(self.dir.name), where)

    def test_a_saved_hunt_comes_back(self):
        answer = {"hunt_id": "abc", "wants": [{"name": "Sol Ring"}],
                  "plan": {"lots": [], "total": 0}, "candidates": []}
        self.main.save_json(self.main.last_hunt_file(),
                            {"at": "2026-10-12 12:00:00", "answer": answer})

        got = self.main.hunt_last()
        self.assertTrue(got["known"])
        self.assertEqual(got["at"], "2026-10-12 12:00:00")
        self.assertEqual(got["answer"]["hunt_id"], "abc")

    def test_a_broken_file_does_not_break_the_tab(self):
        """Испорченный файл -- это «ничего не помним», а не падение."""
        with open(self.main.last_hunt_file(), "w", encoding="utf-8") as fh:
            fh.write("не json вовсе")
        self.assertEqual(self.main.hunt_last(), {"known": False})

    def test_an_empty_answer_is_not_offered(self):
        self.main.save_json(self.main.last_hunt_file(), {"at": "x"})
        self.assertEqual(self.main.hunt_last(), {"known": False})

    def a_hunt(self):
        """Настоящий поиск целиком, но с выдуманным продавцом вместо topdeck.

        Наружу тесты не ходят никогда: подменяется только клиент, всё
        остальное -- разбор строк, отсев, сборка плана, запоминание -- родное.
        """
        from app.topdeck import Offer, Seller

        self.asked = []

        class FakeTopdeck:
            def search(inner, names):  # noqa: N805
                self.asked.append(list(names))
                who = Seller(name="проверка", kind="user", id="проверка",
                             city="Москва", refs=12)
                return [Offer(
                    name=n, eng_name=n, rus_name="", qty=4, cost=100,
                    seller=who, source="topdeck", url="", stamp="",
                    line="4 %s 100" % n) for n in names]

        kept = self.main.TopdeckClient
        self.main.TopdeckClient = lambda *a, **k: FakeTopdeck()
        self.addCleanup(setattr, self.main, "TopdeckClient", kept)

        return self.main.hunt(self.main.HuntIn(
            wants=[{"name": "Lightning Bolt", "quantity": 4}],
            use_collection=False))

    def test_a_whole_hunt_runs_and_is_remembered(self):
        """Проверять только запись и чтение файла оказалось мало.

        Запоминание стоит прямо в конце поиска, и опечатка в нём роняет всю
        охоту -- а не только память о ней. Ровно так и вышло: `time.strftime`
        без `import time` давал 500 на каждый поиск, и ни один тест этого не
        видел, потому что ни один не доходил до самого обработчика -- он ходит
        наружу.
        """
        answer = self.a_hunt()

        self.assertTrue(self.asked, "клиент не спросили ни разу")
        self.assertTrue(answer.get("hunt_id"))
        self.assertTrue(os.path.exists(self.main.last_hunt_file()))

        back = self.main.hunt_last()
        self.assertTrue(back["known"])
        self.assertEqual(back["answer"]["hunt_id"], answer["hunt_id"])

    def test_a_hunt_from_yesterday_still_takes_decisions(self):
        """Прошлый поиск -- рабочий, а не картинка.

        Проверено в браузере до починки: после перезапуска программы на экране
        восстанавливался план, но «не брать это предложение» и пересчёт
        отвечали «этот поиск больше не в памяти — запустите охоту заново». То
        есть возможность не дёргать магазин заново кончалась на первом же
        нажатии и отправляла человека дёргать магазин заново.

        Здесь память сервера очищается нарочно -- это и есть «программу
        закрыли и открыли»: ответ остаётся только в файле.
        """
        answer = self.a_hunt()
        self.main._HUNT_CACHE.clear()

        again = self.main.hunt_replan(self.main.ReplanIn(
            hunt_id=answer["hunt_id"], strategy="sellers",
            skip_offers=[], skip_wants=[], quantities={}, pins={}))
        self.assertEqual(again["hunt_id"], answer["hunt_id"])
        self.assertTrue(again["plan"]["lots"], "план не собрался")

    def test_the_offers_keep_their_names_after_being_rebuilt(self):
        """Ключ объявления обязан совпасть до знака.

        Отказы, закрепления и выбранное предложение помнятся по этому ключу.
        Разойдись он хоть на пробел -- отказ перестанет узнавать то, от чего
        отказались, и в заказ уедет не та строка.
        """
        answer = self.a_hunt()
        self.main._HUNT_CACHE.clear()

        built = self.main._held_hunt(answer["hunt_id"])
        self.assertIsNotNone(built)
        self.assertEqual([c.offer.key for c in built["candidates"]],
                         [c["key"] for c in answer["candidates"]])
        self.assertEqual([c.offer.line for c in built["candidates"]],
                         [c["line"] for c in answer["candidates"]])

    def test_a_different_hunt_is_not_served_from_the_file(self):
        """Чужой номер -- это «не помним», а не последняя охота под его именем."""
        self.a_hunt()
        self.main._HUNT_CACHE.clear()
        self.assertIsNone(self.main._held_hunt("нет-такого"))


if __name__ == "__main__":
    unittest.main()
