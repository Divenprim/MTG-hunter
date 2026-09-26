"""Файлы запуска: то, что пользователь видит раньше любой функции программы.

Проверяется не логика, а байты. Поломки здесь не видно ни в одном тесте кода,
и выглядит она так, будто сломана вся программа:

  * **кодировка.** cmd читает .bat в кодировке OEM (866 в русской Windows).
    Русская буква, записанная в батник в UTF-8, превращается на экране в
    «СЃРѕР·РґР°СЋ». Поэтому в батниках только ASCII, а всё читаемое печатает
    start.py -- он говорит с консолью на UTF-8;
  * **переводы строк.** cmd ждёт CRLF. В репозитории всё лежит с LF, и в
    архиве релиза оказывается ровно то, что в репозитории, -- поэтому
    окончания строк закреплены в .gitattributes;
  * **сообщение о ненайденном питоне** должно называть и обычную установку, и
    заглушку Microsoft Store: на Windows 11 «python» по умолчанию ведёт в
    магазин, и без этой подсказки человек ищет причину у себя.
"""

import io
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BATS = ("run.bat", "run-lan.bat", "run-ssl.bat")


def raw(name):
    with io.open(os.path.join(ROOT, name), "rb") as fh:
        return fh.read()


class TestBatchFiles(unittest.TestCase):
    def test_they_are_all_here(self):
        for name in BATS:
            self.assertTrue(os.path.exists(os.path.join(ROOT, name)), name)

    def test_nothing_but_ascii(self):
        """Русская буква в батнике -- это каракули на экране пользователя."""
        for name in BATS:
            bad = [b for b in raw(name) if b > 127]
            self.assertEqual(bad, [], "%s: %d не-ASCII байт" % (name, len(bad)))

    def test_every_line_ends_the_way_cmd_expects(self):
        for name in BATS:
            data = raw(name)
            self.assertEqual(data.count(b"\n"), data.count(b"\r\n"),
                             "%s: есть строки без CR" % name)

    def test_the_line_endings_are_nailed_down_for_the_release(self):
        """Иначе в архиве окажется то, что в репозитории, а там LF."""
        with io.open(os.path.join(ROOT, ".gitattributes"), encoding="utf-8") as fh:
            rules = fh.read()
        self.assertIn("*.bat text eol=crlf", rules)

    def test_the_console_is_told_to_expect_utf8(self):
        self.assertIn(b"chcp 65001", raw("run.bat"))

    def test_the_missing_python_message_names_both_causes(self):
        text = raw("run.bat").decode("ascii").lower()
        self.assertIn("python.org", text)
        self.assertIn("execution aliases", text)

    def test_each_one_works_on_a_fresh_copy(self):
        """«Сначала запустите run.bat» -- не ответ.

        run-ssl.bat именно это и отвечал на свежей распаковке: человек, которому
        нужен планшет, упирался в предложение запустить сначала что-то другое.
        Каждый запускающий файл либо сам умеет искать питон, либо честно
        передаёт работу тому, кто умеет.
        """
        for name in BATS:
            text = raw(name).decode("ascii")
            own = "for %%P in (" in text
            passes_on = "call " in text and "run.bat" in text
            self.assertTrue(own or passes_on, name)
            self.assertNotIn("Run run.bat first", text, name)


    def test_source_launcher_accepts_only_supported_python(self):
        """Source-mode bootstrap must not silently accept 3.13/3.14.

        The Windows OCR dependency currently has wheels for the supported
        3.12 runtime. Accepting a newer interpreter only moves the failure to
        pip and makes it look like a broken release.
        """
        text = raw("run.bat").decode("ascii")
        self.assertIn("sys.version_info[:2] == (3, 12)", text)
        self.assertNotIn('"py -3"', text)

    def test_the_launcher_is_asked_before_the_bare_name(self):
        """«python» на Windows 11 ведёт в магазин, «py» -- в питон.

        Смотреть надо на сам перебор, а не на весь файл: слово «python» есть и
        в пояснении сверху, и оно там стоит раньше.
        """
        line = [s for s in raw("run.bat").decode("ascii").splitlines()
                if s.strip().startswith("for %%P in")]
        self.assertEqual(len(line), 1, "перебор питонов не нашёлся")
        self.assertLess(line[0].index('"py -3'), line[0].index('"python"'))


class TestStartScript(unittest.TestCase):
    def setUp(self):
        with io.open(os.path.join(ROOT, "start.py"), encoding="utf-8") as fh:
            self.text = fh.read()

    def test_it_settles_the_encoding_before_printing(self):
        self.assertLess(self.text.index("def console_speaks_utf8"),
                        self.text.index("def say"))

    def test_it_keeps_a_log_to_read_afterwards(self):
        """Окно закрылось -- вопрос «что случилось» должен иметь ответ."""
        self.assertIn("setup.log", self.text)

    def test_it_uses_only_the_standard_library(self):
        """Запускается системным питоном: ставить ему нечего."""
        imports = [line.split()[1].split(".")[0]
                   for line in self.text.splitlines()
                   if line.startswith("import ")]
        for name in imports:
            self.assertIn(name, ("os", "shutil", "subprocess", "sys", "time",
                                 "ctypes"), name)


if __name__ == "__main__":
    unittest.main()
