"""Скрипты сборки релиза должны запускаться так, как их запускает сборка.

Эти файлы не участвуют в работе программы, их не покрывает ни один тест кода,
и падают они там, где их никто не видит -- в чужой машине посреди ночного
прогона. Цена уже известна: `merge_art_hashes.py` считал шесть частей базы
отпечатков часами, все шесть посчитались, а слияние упало на самой первой
строке -- `from app import artscan`. Запущенный как `python
release/merge_art_hashes.py`, он видит в sys.path папку `release`, а не корень
репозитория, и пакета `app` из неё нет.

Готовой базы отпечатков поэтому не появилось. А без неё не собирается ни один
пользовательский релиз: сборка требует её обязательным шагом и падает, если
файла нет.

Проверка простая: каждый скрипт зовётся с `--help` из корня репозитория, ровно
как в сборке. `--help` ничего не делает и выходит с нулём -- значит до разбора
аргументов дело дошло, значит все импорты на месте. Ошибка импорта сюда не
пролезет.
"""

import importlib
import io
import os
import re
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RELEASE = os.path.join(ROOT, "release")


def scripts() -> list[str]:
    if not os.path.isdir(RELEASE):
        return []
    return sorted(name for name in os.listdir(RELEASE)
                  if name.endswith(".py") and not name.startswith("_"))


@unittest.skipUnless(scripts(), "нет папки release")
class TestReleaseScripts(unittest.TestCase):

    def test_there_are_release_scripts_to_check(self):
        self.assertTrue(scripts(), "проверять нечего -- это само по себе странно")

    def test_each_one_starts_the_way_the_build_starts_it(self):
        for name in scripts():
            with self.subTest(script=name):
                done = subprocess.run(
                    [sys.executable, os.path.join("release", name), "--help"],
                    cwd=ROOT, capture_output=True, text=True, timeout=120)
                self.assertEqual(
                    done.returncode, 0,
                    "%s не запускается из корня репозитория:\n%s"
                    % (name, (done.stderr or done.stdout)[-800:]))

    def test_the_one_that_broke_imports_the_app(self):
        """Отдельно и по имени: именно на этом импорте всё и встало."""
        done = subprocess.run(
            [sys.executable, "-c",
             "import os, sys;"
             "sys.path.insert(0, os.path.join('release'));"
             "import merge_art_hashes as m;"
             "print(m.artscan.__name__)"],
            cwd=ROOT, capture_output=True, text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-800:])
        self.assertIn("artscan", done.stdout)


class TestImportsWrittenInsideStrings(unittest.TestCase):
    """Импорт, который лежит строкой, проверкой запуска не ловится.

    Сквозная проверка портатива поднимает кусочки программы отдельными
    процессами: `python -c "from app.main import _serve_ca; ..."`. Для
    самого скрипта это строка, и `--help` на ней ничего не скажет. А
    страница с сертификатом для телефона тем временем переехала в
    `app.lan`, импорт перестал существовать, процесс умирал на первой
    строке -- и сборка релиза сообщала «соединение отвергнуто», то есть
    про что угодно, кроме случившегося.

    Поэтому имена спрашиваются у самих модулей: как написано в скрипте --
    хоть кодом, хоть строкой, -- так и проверяется.
    """

    WRITTEN = re.compile(r"from (app(?:\.\w+)*) import ([\w, ]+)")

    def names_in(self, name: str) -> list[tuple[str, str]]:
        text = io.open(os.path.join(RELEASE, name), encoding="utf-8").read()
        out = []
        for module, names in self.WRITTEN.findall(text):
            for one in names.split(","):
                one = one.strip()
                if one:
                    out.append((module, one))
        return out

    def test_every_name_a_release_script_imports_exists(self):
        seen = 0
        for script in scripts():
            for module, name in self.names_in(script):
                seen += 1
                with self.subTest(script=script, name="%s.%s" % (module, name)):
                    mod = importlib.import_module(module)
                    if hasattr(mod, name):
                        continue
                    # `from app import artscan` -- это сосед-модуль, а не
                    # имя внутри пакета: пока его не ввезли, пакет про него
                    # не знает.
                    try:
                        importlib.import_module("%s.%s" % (module, name))
                    except ImportError:
                        self.fail("%s берёт %s из %s, а там этого нет"
                                  % (script, name, module))
        self.assertGreater(seen, 0, "ни одного импорта app в release/")

    def test_the_certificate_page_is_where_the_smoke_test_looks(self):
        """Отдельно и по имени: на этом встала сборка 1.37.0."""
        from app import lan

        self.assertTrue(hasattr(lan, "_serve_ca"))
        text = io.open(os.path.join(RELEASE, "smoke_portable.py"),
                       encoding="utf-8").read()
        self.assertIn("from app.lan import _serve_ca", text)


if __name__ == "__main__":
    unittest.main()
