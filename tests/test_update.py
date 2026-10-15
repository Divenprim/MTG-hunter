"""Обновление: сравнение версий, чужой архив, чужие данные, разрешение.

Самая опасная часть программы: она переписывает саму программу файлами,
скачанными из интернета. Поэтому здесь проверяется не «работает ли», а
«чего оно точно не сделает»:

* не пойдёт наружу, пока человек не разрешил;
* не распакует архив, в котором пути ведут мимо папки;
* не тронет `user.sqlite`, сертификаты, кеш картинок и последнюю охоту;
* не решит, что «1.9.0» новее «1.10.0».

Сети здесь нет ни одного байта: ответ GitHub подаётся строкой, архив
собирается в памяти.
"""

import json
import os
import sys
import tempfile
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import update  # noqa: E402


def make_zip(path, names, root="MTG-Hunter"):
    with zipfile.ZipFile(path, "w") as zf:
        for name, body in names.items():
            full = name if root is None else root + "/" + name
            zf.writestr(full, body)
    return path


class TestVersions(unittest.TestCase):
    def test_numbers_not_letters(self):
        """«1.9.0» больше «1.10.0» по алфавиту — и программа застревает."""
        self.assertTrue(update.is_newer("1.10.0", "1.9.0"))
        self.assertFalse(update.is_newer("1.9.0", "1.10.0"))

    def test_v_prefix_and_equal(self):
        self.assertTrue(update.is_newer("v1.26.0", "1.25.0"))
        self.assertFalse(update.is_newer("v1.26.0", "1.26.0"))

    def test_nonsense_is_oldest(self):
        """Непонятный тег не должен выглядеть свежим."""
        self.assertFalse(update.is_newer("latest", "1.0.0"))


class TestReadingTheAnswer(unittest.TestCase):
    def payload(self, **over):
        body = {
            "tag_name": "v1.27.0",
            "name": "1.27.0 — portable",
            "body": "примечания",
            "published_at": "2026-10-20T10:00:00Z",
            "assets": [{
                "name": update.ASSET_NAME,
                "size": 288400848,
                "browser_download_url":
                    "https://github.com/Divenprim/MTG-hunter/releases/download/"
                    "v1.27.0/" + update.ASSET_NAME,
            }],
        }
        body.update(over)
        return json.dumps(body)

    def test_takes_what_it_needs(self):
        got = update.read_release(self.payload())
        self.assertEqual(got["version"], "v1.27.0")
        self.assertEqual(got["size"], 288400848)
        self.assertTrue(got["url"].startswith("https://github.com/Divenprim/"))

    def test_foreign_download_link_is_refused(self):
        """Ссылка из ответа — чужие данные. Качать по ней куда попало нельзя."""
        bad = self.payload(assets=[{
            "name": update.ASSET_NAME, "size": 10,
            "browser_download_url": "https://example.invalid/evil.zip",
        }])
        with self.assertRaises(update.UpdateError):
            update.read_release(bad)

    def test_release_without_build_is_not_an_error(self):
        got = update.read_release(self.payload(assets=[]))
        self.assertEqual(got["url"], "")

    def test_garbage_answer(self):
        with self.assertRaises(update.UpdateError):
            update.read_release("не json")
        with self.assertRaises(update.UpdateError):
            update.read_release("[1, 2, 3]")


class TestPermission(unittest.TestCase):
    def test_silence_means_no(self):
        """Пока не разрешили — наружу не ходим."""
        self.assertIsNone(update.update_setting({}))
        self.assertFalse(update.may_check({}))

    def test_yes_and_no(self):
        self.assertTrue(update.may_check({"update_check": "yes"}))
        self.assertFalse(update.may_check({"update_check": "no"}))

    def test_old_boolean_setting_is_understood(self):
        self.assertTrue(update.may_check({"update_check": True}))
        self.assertFalse(update.may_check({"update_check": False}))


class TestArchiveIsUntrusted(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "a.zip")

    def tearDown(self):
        self.dir.cleanup()

    def test_path_outside_the_folder(self):
        make_zip(self.path, {"../../evil.txt": "x", "app/main.py": "ok"})
        with zipfile.ZipFile(self.path) as zf:
            with self.assertRaises(update.UpdateError):
                update.check_names(zf.namelist())

    def test_absolute_path(self):
        with zipfile.ZipFile(self.path, "w") as zf:
            zf.writestr("MTG-Hunter/app/main.py", "ok")
            zf.writestr("C:/Windows/System32/evil.dll", "x")
        with zipfile.ZipFile(self.path) as zf:
            with self.assertRaises(update.UpdateError):
                update.check_names(zf.namelist())

    def test_someone_elses_collection_inside(self):
        """Архив с чужим user.sqlite — не наш архив."""
        make_zip(self.path, {"app/main.py": "ok", "data/user.sqlite": "чужое"})
        with zipfile.ZipFile(self.path) as zf:
            with self.assertRaises(update.UpdateError):
                update.check_names(zf.namelist())

    def test_two_roots(self):
        with zipfile.ZipFile(self.path, "w") as zf:
            zf.writestr("MTG-Hunter/app/main.py", "ok")
            zf.writestr("Other/app/main.py", "ok")
        with zipfile.ZipFile(self.path) as zf:
            with self.assertRaises(update.UpdateError):
                update.check_names(zf.namelist())

    def test_good_archive_passes(self):
        make_zip(self.path, {"app/main.py": "ok", "web/app.js": "ok",
                             "data/sets.json": "{}"})
        with zipfile.ZipFile(self.path) as zf:
            update.check_names(zf.namelist())        # без исключения


class TestWhatGetsReplaced(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.target = os.path.join(self.dir.name, "program")
        self.new = os.path.join(self.dir.name, "new", "MTG-Hunter")
        for path in (self.target, self.new):
            os.makedirs(os.path.join(path, "app"))
            os.makedirs(os.path.join(path, "data"))

        # что лежит у человека
        self._write(self.target, "app/main.py", "старый код")
        self._write(self.target, "start.py", "старый запуск")
        self._write(self.target, "data/user.sqlite", "МОИ КОЛОДЫ")
        self._write(self.target, "data/settings.json", '{"price_auto": true}')
        self._write(self.target, "data/last-hunt.json", "моя охота")
        self._write(self.target, "data/cert/server.pem", "мой ключ")
        self._write(self.target, "data/image-cache/a.jpg", "картинка")
        self._write(self.target, "data/sets.json", "старые сеты")

        # что приехало в обновлении
        self._write(self.new, "app/main.py", "новый код")
        self._write(self.new, "start.py", "новый запуск")
        self._write(self.new, "data/sets.json", "новые сеты")
        self._write(self.new, "data/cards.sqlite", "новая база карт")

    def tearDown(self):
        self.dir.cleanup()

    def _write(self, root, rel, body):
        path = os.path.join(root, rel.replace("/", os.sep))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(body)

    def _read(self, root, rel):
        path = os.path.join(root, rel.replace("/", os.sep))
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_code_is_replaced(self):
        update.apply_update(self.new, self.target)
        self.assertEqual(self._read(self.target, "app/main.py"), "новый код")
        self.assertEqual(self._read(self.target, "start.py"), "новый запуск")

    def test_shared_databases_are_replaced(self):
        update.apply_update(self.new, self.target)
        self.assertEqual(self._read(self.target, "data/sets.json"), "новые сеты")
        self.assertEqual(self._read(self.target, "data/cards.sqlite"),
                         "новая база карт")

    def test_nothing_of_mine_is_touched(self):
        """Главное обещание обновления."""
        update.apply_update(self.new, self.target)
        self.assertEqual(self._read(self.target, "data/user.sqlite"),
                         "МОИ КОЛОДЫ")
        self.assertEqual(self._read(self.target, "data/settings.json"),
                         '{"price_auto": true}')
        self.assertEqual(self._read(self.target, "data/last-hunt.json"),
                         "моя охота")
        self.assertEqual(self._read(self.target, "data/cert/server.pem"),
                         "мой ключ")
        self.assertEqual(self._read(self.target, "data/image-cache/a.jpg"),
                         "картинка")

    def test_files_the_update_does_not_carry_stay(self):
        """В сборке нет моего файла — значит он просто остаётся."""
        self._write(self.target, "data/мои-заметки.txt", "не трогать")
        update.apply_update(self.new, self.target)
        self.assertEqual(self._read(self.target, "data/мои-заметки.txt"),
                         "не трогать")

    def test_whole_directory_is_swapped_not_merged(self):
        """Файл, которого в новой версии нет, не должен пережить обновление.

        Иначе удалённый модуль остаётся на диске и продолжает грузиться.
        """
        self._write(self.target, "app/старый_модуль.py", "удалён в новой версии")
        update.apply_update(self.new, self.target)
        self.assertFalse(os.path.exists(
            os.path.join(self.target, "app", "старый_модуль.py")))


class TestUnpack(unittest.TestCase):
    def test_unpack_returns_the_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_zip(os.path.join(tmp, "a.zip"),
                            {"app/main.py": "код", "data/sets.json": "{}"})
            root = update.unpack(path, os.path.join(tmp, "out"))
            self.assertTrue(os.path.isfile(os.path.join(root, "app", "main.py")))

    def test_unpack_refuses_a_bad_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = make_zip(os.path.join(tmp, "a.zip"),
                            {"../evil.py": "x", "app/main.py": "код"})
            with self.assertRaises(update.UpdateError):
                update.unpack(path, os.path.join(tmp, "out"))


class TestNothingLeavesWithoutPermission(unittest.TestCase):
    """Самая важная проверка файла: пока не разрешили — наружу ни байта.

    Проверяется не намерение, а факт: `start.check_for_update` зовётся с
    подменённой сетью, и подмена считает обращения. Настройки уводятся во
    временную папку, чтобы не трогать чужой settings.json.
    """

    def setUp(self):
        import start
        self.start = start
        self.dir = tempfile.TemporaryDirectory()
        self.kept_settings = start.SETTINGS
        self.kept_fetch = start._fetch
        self.kept_say = start.say
        start.SETTINGS = os.path.join(self.dir.name, "settings.json")
        start.say = lambda *a, **k: None
        # Спрашивалку подменяем явно, а не полагаемся на то, что у тестов нет
        # консоли: под живым терминалом тест иначе ждал бы ввода и висел.
        # None -- «спросить негде», то самое положение, которое и проверяем.
        self.kept_ask = start._ask
        start._ask = lambda question: None
        self.calls = []

        def fake_fetch(url, timeout=20):
            self.calls.append(url)
            raise AssertionError("запрос наружу без разрешения")

        start._fetch = fake_fetch

    def tearDown(self):
        self.start.SETTINGS = self.kept_settings
        self.start._fetch = self.kept_fetch
        self.start.say = self.kept_say
        self.start._ask = self.kept_ask
        self.dir.cleanup()

    def _settings(self, data):
        with open(self.start.SETTINGS, "w", encoding="utf-8") as fh:
            json.dump(data, fh)

    def test_refused_means_no_requests(self):
        self._settings({"update_check": "no"})
        self.start.check_for_update()
        self.assertEqual(self.calls, [])

    def test_unanswered_means_no_requests(self):
        """Ответа ещё не было, спросить негде — значит не проверяем."""
        self._settings({})
        self.start.check_for_update()
        self.assertEqual(self.calls, [])

    def test_unanswered_does_not_answer_for_the_user(self):
        """Неинтерактивный запуск не должен записать «человек отказался»."""
        self._settings({"price_auto": True})
        self.start.check_for_update()
        with open(self.start.SETTINGS, encoding="utf-8") as fh:
            after = json.load(fh)
        self.assertNotIn("update_check", after)

    def test_permission_given_means_one_request(self):
        self._settings({"update_check": "yes"})
        asked = []

        def fetch(url, timeout=20):
            asked.append(url)
            return json.dumps({"tag_name": "v0.0.1", "assets": []})

        self.start._fetch = fetch
        self.start.check_for_update()
        self.assertEqual(asked, [update.RELEASES_URL])


class TestSizes(unittest.TestCase):
    def test_human_size(self):
        self.assertEqual(update.human_size(288400848), "275 МБ")
        self.assertEqual(update.human_size(1048576), "1.0 МБ")


if __name__ == "__main__":
    unittest.main()
