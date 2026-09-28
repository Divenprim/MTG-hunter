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

import os
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


if __name__ == "__main__":
    unittest.main()
