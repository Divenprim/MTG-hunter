"""Порядок загрузки скриптов не должен быть скрытым требованием.

Заведено после того, как разделение `app.js` на файлы сломало поиск целиком, и
ни один из девятисот тестов этого не заметил.

Выглядело это так. В app.js осталась строка

    $("#filters-apply").addEventListener("click", applyFilterPanel);

а сама `applyFilterPanel` уехала в `filters.js`, который грузится **после**.
Строка берёт функцию значением в момент загрузки, а её ещё нет: страница
падает прямо здесь, и всё, что в app.js ниже этой строки, не выполняется
вовсе. Поиск переставал работать, окно карты тоже, а в консоли лежали три
ошибки, из которых только первая настоящая.

Отсюда правило: имя, которое файл берёт **значением на верхнем уровне**,
должно быть объявлено в нём самом или в файле, загруженном раньше. Вызовы
внутри обработчиков так не проверяются и не должны: к моменту нажатия
загружено уже всё.
"""

import io
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")
HTML = io.open(os.path.join(WEB, "index.html"), encoding="utf-8").read()

ORDER = re.findall(r'<script src="/static/([^"]+)"></script>', HTML)

DECLARES = re.compile(
    r"^(?:async\s+)?function\s+(\w+)|^(?:let|const|var)\s+(\w+)", re.M)

# Имя, переданное значением: addEventListener("click", имя) и
# addEventListener("click", имя, {...}).
AS_VALUE = re.compile(r"addEventListener\(\s*[\"'][^\"']+[\"']\s*,\s*(\w+)\s*[,)]")


def declared_in(text: str) -> set:
    out = set()
    for a, b in DECLARES.findall(text):
        out.add(a or b)
    return out


def top_level(text: str) -> str:
    """Только строки верхнего уровня: внутри функций порядок уже не важен."""
    keep = []
    depth = 0
    for line in text.split("\n"):
        if depth == 0:
            keep.append(line)
        depth += line.count("{") - line.count("}")
        depth = max(0, depth)
    return "\n".join(keep)


class ScriptOrder(unittest.TestCase):

    def setUp(self):
        self.text = {}
        for name in ORDER:
            path = os.path.join(WEB, name)
            if os.path.exists(path):
                with io.open(path, encoding="utf-8") as fh:
                    self.text[name] = fh.read()

    def test_every_script_in_the_page_exists(self):
        for name in ORDER:
            with self.subTest(file=name):
                self.assertTrue(os.path.exists(os.path.join(WEB, name)))

    def test_a_name_taken_as_a_value_is_already_declared(self):
        seen = set()
        for name in ORDER:
            text = self.text.get(name, "")
            seen |= declared_in(text)
            everywhere = set()
            for other in self.text.values():
                everywhere |= declared_in(other)
            for used in AS_VALUE.findall(top_level(text)):
                if used not in everywhere:
                    continue          # браузерное или чужое -- не наше дело
                with self.subTest(file=name, name=used):
                    self.assertIn(used, seen, (
                        "%s берёт %s значением при загрузке, а объявлено оно "
                        "в файле, который грузится позже: строка упадёт, и "
                        "всё ниже неё в этом файле не выполнится"
                        % (name, used)))

    def test_boot_is_last(self):
        """Запуск зовёт всех, поэтому и грузится после всех."""
        self.assertEqual(ORDER[-1], "boot.js")

    def test_the_check_itself_catches_the_real_case(self):
        """Та самая строка, на которой всё сломалось."""
        broken = {"a.js": 'addEventListener("click", applyFilterPanel);',
                  "b.js": "function applyFilterPanel() {}"}
        seen = set()
        caught = []
        for name in ("a.js", "b.js"):
            seen |= declared_in(broken[name])
            for used in AS_VALUE.findall(top_level(broken[name])):
                if used not in seen:
                    caught.append((name, used))
        self.assertEqual(caught, [("a.js", "applyFilterPanel")])


if __name__ == "__main__":
    unittest.main(verbosity=2)
