"""Картинки не должны пропадать целыми экранами.

Пользователь сказал: «картинки пропадают, даже если в миниатюре видны».
Замер объяснил, почему.

Предохранитель у источника картинок срабатывал после **двух** неудач и
закрывал весь источник на две минуты. А страница открывает полсотни запросов
за картинками разом: пара медленных на обычном домашнем канале -- и все
несохранённые картинки становятся пустыми. Миниатюра при этом видна, потому
что она скачалась раньше и лежит на диске, а крупная -- нет.

Замер до починки: двадцать карточек на экране → две попытки достучаться →
двадцать пустых картинок. И, что хуже, когда связь возвращалась, не
пробовалась ни одна: ноль попыток при живой сети.

Вторая половина беды -- запись в кеш: общее имя черновика и проглоченная
ошибка. Удачно скачанная картинка могла не попасть на диск, и тогда каждый
её показ снова зависел от сети.
"""

import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests                                           # noqa: E402

from app import imagecache                                # noqa: E402


class Dead:
    """Сеть, которая молчит."""

    def __init__(self, tries):
        self.tries = tries

    def get(self, url, **kw):
        self.tries.append(url)
        raise requests.ConnectionError("нет связи")


class Alive:
    """Сеть, которая отвечает картинкой."""

    def __init__(self, tries):
        self.tries = tries

    def get(self, url, **kw):
        self.tries.append(url)

        class Resp:
            status_code = 200
            headers = {"Content-Type": "image/jpeg"}
            content = b"\xff\xd8\xff" + b"x" * 1024

        return Resp()


class Breaker(unittest.TestCase):

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="mtgh-img-")
        self._cache = imagecache.CACHE_DIR
        imagecache.CACHE_DIR = __import__("pathlib").Path(self.dir)
        self._row = imagecache._row
        self._cands = imagecache._candidates
        self._session = imagecache._session
        imagecache._row = lambda *a, **k: ("https://cards.scryfall.io/x.jpg", "Fog")
        with imagecache._STATE_LOCK:
            imagecache._HOST_STATE.clear()
            imagecache._NEGATIVE_UNTIL.clear()

    def tearDown(self):
        imagecache.CACHE_DIR = self._cache
        imagecache._row = self._row
        imagecache._candidates = self._cands
        imagecache._session = self._session
        with imagecache._STATE_LOCK:
            imagecache._HOST_STATE.clear()
            imagecache._NEGATIVE_UNTIL.clear()

    def each_card_its_own_url(self):
        imagecache._candidates = (
            lambda db, cid, up, size: ["https://cards.scryfall.io/%s.jpg" % cid])

    def test_a_couple_of_slow_requests_do_not_blank_the_page(self):
        """Две медленные картинки -- это не «источник лёг»."""
        tries = []
        imagecache._session = lambda: Dead(tries)
        self.each_card_its_own_url()
        sources = [imagecache.get_image(None, "c%d" % i, size="small")[2]
                   for i in range(3)]
        self.assertEqual(sources.count("placeholder"), 3,
                         "при мёртвой сети картинок и не будет")
        self.assertEqual(len(tries), 3,
                         "после двух неудач источник закрываться не должен")

    def test_a_dead_source_is_still_closed_eventually(self):
        """Ждать таймаут на каждой из полусотни картинок тоже нельзя."""
        tries = []
        imagecache._session = lambda: Dead(tries)
        self.each_card_its_own_url()
        for i in range(20):
            imagecache.get_image(None, "c%d" % i, size="small")
        self.assertEqual(len(tries), imagecache.HOST_FAILURE_LIMIT,
                         "источник должен закрыться после порога неудач")
        self.assertEqual(imagecache.cache_stats()["blocked_hosts"], 1)

    def test_when_the_network_comes_back_one_request_is_tried(self):
        """Прежде не пробовалась ни одна -- и картинок не было до конца паузы."""
        dead = []
        imagecache._session = lambda: Dead(dead)
        self.each_card_its_own_url()
        for i in range(imagecache.HOST_FAILURE_LIMIT + 2):
            imagecache.get_image(None, "c%d" % i, size="small")
        self.assertEqual(imagecache.cache_stats()["blocked_hosts"], 1)

        # Пауза истекла, связь вернулась.
        with imagecache._STATE_LOCK:
            failures, _until = imagecache._HOST_STATE["cards.scryfall.io"]
            imagecache._HOST_STATE["cards.scryfall.io"] = (failures, 0.0)
        alive = []
        imagecache._session = lambda: Alive(alive)
        _data, _mt, source = imagecache.get_image(None, "новая", size="normal")
        self.assertEqual(len(alive), 1, "пробную попытку надо сделать")
        self.assertEqual(source, "network")
        # И источник снова открыт целиком.
        _d, _m, second = imagecache.get_image(None, "ещё-одна", size="normal")
        self.assertEqual(second, "network")

    def test_a_downloaded_image_is_actually_cached(self):
        """Иначе каждый показ снова зависит от сети -- «была и пропала»."""
        alive = []
        imagecache._session = lambda: Alive(alive)
        self.each_card_its_own_url()
        first = imagecache.get_image(None, "c1", size="small")[2]
        second = imagecache.get_image(None, "c1", size="small")[2]
        self.assertEqual(first, "network")
        self.assertEqual(second, "cache", "картинка не легла в кеш")
        self.assertEqual(len(alive), 1, "второй раз в сеть ходить незачем")

    def test_a_busy_file_does_not_cost_the_cache_entry(self):
        """Windows не даёт подменить файл, который браузер читает.

        Ошибку глотали молча: картинка показывалась, в кеш не попадала, и
        следующий показ снова шёл в сеть. Отсюда и «была и пропала» -- каждый
        раз всё зависело от того, дошёл ли запрос.
        """
        alive = []
        imagecache._session = lambda: Alive(alive)
        self.each_card_its_own_url()
        real = os.replace
        busy = {"n": 0}

        def busy_once(src, dst):
            busy["n"] += 1
            if busy["n"] == 1:
                raise PermissionError("файл читают")
            return real(src, dst)

        os.replace = busy_once
        try:
            first = imagecache.get_image(None, "занятая", size="small")[2]
        finally:
            os.replace = real
        self.assertEqual(first, "network")
        self.assertGreater(busy["n"], 1, "подмену надо повторить, а не бросить")
        self.assertEqual(imagecache.get_image(None, "занятая", size="small")[2],
                         "cache", "картинка так и не легла в кеш")
        self.assertEqual(len(alive), 1, "второй раз в сеть ходить незачем")

    def test_the_cooldown_is_short_enough_to_be_survivable(self):
        """Две минуты пустых картинок -- это «программа сломалась» на вид."""
        self.assertLessEqual(imagecache.HOST_COOLDOWN_SECONDS, 60)
        self.assertGreaterEqual(imagecache.HOST_FAILURE_LIMIT, 4)

    def test_two_tabs_asking_at_once_do_not_spoil_the_draft(self):
        """Общее имя черновика означало, что писатели затирают друг друга."""
        alive = []
        imagecache._session = lambda: Alive(alive)
        self.each_card_its_own_url()
        done = []

        def ask():
            done.append(imagecache.get_image(None, "общая", size="normal")[2])

        threads = [threading.Thread(target=ask) for _ in range(6)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)
        self.assertEqual(len(done), 6)
        self.assertEqual(imagecache.get_image(None, "общая", size="normal")[2],
                         "cache")
        left = [n for n in os.listdir(self.dir) if n.endswith(".tmp")]
        self.assertEqual(left, [], "черновики остались на диске")


if __name__ == "__main__":
    unittest.main(verbosity=2)
