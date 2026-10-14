"""Запись маленьких json-файлов: либо случилась, либо сказала о себе.

Заведено после того, как замер показал, что результат охоты может не доехать
до диска. Запись идёт через временный файл и `os.replace`, а Windows не даёт
подменить файл, который кто-то держит открытым на чтение. Держит его
`GET /api/hunt/last` -- то есть ровно та пара, что встречается в жизни: одна
вкладка перечитывает прошлую охоту, вторая сохраняет новую.

Замер до починки: **39 отказов из 40 попыток записи**, и ни один не был
пойман -- исключение вылетало из ручки `/api/hunt`. Человек ждал полторы
секунды на пачку имён, видел план на экране, а после перезапуска охоты не
было.

Проверяется не «есть ли retry», а то, ради чего он написан: после записи на
диске лежит записанное.
"""

import json
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import storage                                   # noqa: E402


class WritesSurviveAReader(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="mtgh-json-")
        self.path = os.path.join(self.dir, "last-hunt.json")

    def test_a_write_lands_while_another_tab_reads(self):
        """Две вкладки программы: одна читает, вторая пишет."""
        storage.save_json(self.path, {"at": "начало"})
        stop = threading.Event()
        reads = []

        def reader():
            while not stop.is_set():
                # Так читает ручка: открыл, прочитал, закрыл.
                reads.append(storage.load_json(self.path, None))
                time.sleep(0.002)

        thread = threading.Thread(target=reader, daemon=True)
        thread.start()
        try:
            for i in range(40):
                storage.save_json(self.path, {"at": i})
                time.sleep(0.003)
        finally:
            stop.set()
            thread.join(timeout=3)

        self.assertEqual(storage.load_json(self.path, None), {"at": 39})
        # Читатель ни разу не должен был увидеть пустоту: файл либо старый,
        # либо новый, но он есть всегда.
        self.assertNotIn(None, reads)
        self.assertTrue(reads, "читатель не успел ни разу")

    def test_two_writers_do_not_share_a_draft(self):
        """Общее имя черновика означало, что писатели затирают друг друга."""
        done = []

        def writer(tag):
            for i in range(25):
                storage.save_json(self.path, {"кто": tag, "i": i})
            done.append(tag)

        threads = [threading.Thread(target=writer, args=(t,))
                   for t in ("первый", "второй")]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(sorted(done), ["второй", "первый"])
        got = storage.load_json(self.path, None)
        self.assertIsInstance(got, dict, "файл должен остаться разбираемым")
        self.assertIn(got["кто"], ("первый", "второй"))

    def test_no_drafts_are_left_behind(self):
        storage.save_json(self.path, {"a": 1})
        left = [n for n in os.listdir(self.dir) if n.endswith(".tmp")]
        self.assertEqual(left, [])

    def test_a_write_that_cannot_happen_is_not_silent(self):
        """Молча потерять запись хуже, чем сказать о ней."""
        real = os.replace

        def always_busy(src, dst):
            raise PermissionError("файл занят")

        os.replace = always_busy
        try:
            with self.assertRaises(PermissionError):
                storage.save_json(self.path, {"a": 1})
        finally:
            os.replace = real
        # И черновик за собой убрали даже в этом случае.
        self.assertEqual([n for n in os.listdir(self.dir)
                          if n.endswith(".tmp")], [])

    def test_a_busy_moment_is_waited_out(self):
        """Чтение держит файл миллисекунды -- второй попытки обычно хватает."""
        real = os.replace
        tries = {"n": 0}

        def busy_twice(src, dst):
            tries["n"] += 1
            if tries["n"] <= 2:
                raise PermissionError("файл занят")
            return real(src, dst)

        os.replace = busy_twice
        try:
            storage.save_json(self.path, {"a": "дошло"})
        finally:
            os.replace = real
        self.assertEqual(storage.load_json(self.path, None), {"a": "дошло"})
        self.assertEqual(tries["n"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
