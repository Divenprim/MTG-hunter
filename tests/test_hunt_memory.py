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


if __name__ == "__main__":
    unittest.main()
