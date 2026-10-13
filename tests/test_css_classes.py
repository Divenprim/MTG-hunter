"""Один класс — одна раскладка.

Заведено после трёх случаев подряд, и ни один не видно из кода поодиночке:

  * `.deckrow` был объявлен дважды — flex от старой разметки и сетка на шесть
    колонок. Выигрывала сетка, она же и верная, а первый блок читался как
    действующий и не работал ни строкой;
  * `.altrow` был объявлен дважды — сетка для списка «где ещё есть эта карта»
    и flex для подсказок сканера. Выигрывал flex, потому что написан ниже, и
    выдача охоты потеряла выравнивание по столбцам. Этого никто не заметил:
    экран всё ещё выглядел как список;
  * `.linkish` я чуть не завёл третьим — придумал класс, который уже был, и
    моё объявление перебило бы чужое в семи местах.

Беда в том, что ни одно из этих мест не выглядит сломанным: CSS не ругается,
а молча берёт то правило, что ниже. Поэтому проверка машинная.

Переопределять класс в медиазапросе — нормально, это и есть их работа, и они
отсюда вырезаны целиком. Речь только о верхнем уровне.
"""

import io
import os
import re
import sys
import unittest
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSS = io.open(os.path.join(ROOT, "web", "style.css"), encoding="utf-8").read()

# Пары, где второе объявление — намеренное уточнение первого, а не второй
# смысл того же имени. Список именно явный: молчаливое исключение по образцу
# пропустило бы ровно те случаи, ради которых проверка написана.
EXPECTED = {
    # .tiny — размер подписи, button.tiny — та же мелкость для кнопки.
    ("tiny", frozenset((".tiny", "button.tiny"))),
}


def _without_media(css: str) -> str:
    """Вырезать @media вместе с телом: внутри них переопределять -- нормально."""
    out = []
    i = 0
    while i < len(css):
        if css.startswith("@media", i) or css.startswith("@supports", i):
            brace = css.index("{", i)
            depth = 1
            j = brace + 1
            while depth and j < len(css):
                if css[j] == "{":
                    depth += 1
                elif css[j] == "}":
                    depth -= 1
                j += 1
            i = j
            continue
        out.append(css[i])
        i += 1
    return "".join(out)


def duplicates(css: str) -> dict:
    """Классы, объявленные на верхнем уровне дважды одними свойствами."""
    top = _without_media(css)
    byclass = defaultdict(list)
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", top):
        selector = " ".join(selector.split())
        hit = re.fullmatch(r"(?:button|a|span|div|p|label|ul|li)?\.([\w-]+)",
                           selector)
        if not hit:
            continue
        props = {part.split(":")[0].strip()
                 for part in body.split(";") if ":" in part}
        byclass[hit.group(1)].append((selector, props))

    out = {}
    for name, defs in byclass.items():
        if len(defs) < 2:
            continue
        shared = set.intersection(*[d[1] for d in defs])
        if not shared:
            continue
        out[name] = {"selectors": frozenset(d[0] for d in defs),
                     "shared": sorted(shared)}
    return out


class OneClassOneLayout(unittest.TestCase):

    def test_no_class_is_defined_twice(self):
        found = duplicates(CSS)
        unexpected = {
            name: info for name, info in found.items()
            if (name, info["selectors"]) not in EXPECTED
        }
        self.assertEqual(unexpected, {}, (
            "класс объявлен дважды на верхнем уровне одними свойствами: "
            "побеждает тот, что ниже по файлу, молча. Разведите имена — "
            "или впишите пару в EXPECTED, если это намеренное уточнение"))

    def test_the_check_itself_catches_a_collision(self):
        """Проверка, которая ничего не ловит, хуже отсутствующей."""
        made_up = CSS + "\n.probe { display: flex; }\n.probe { display: grid; }\n"
        self.assertIn("probe", duplicates(made_up))

    def test_media_queries_are_not_counted(self):
        """Переопределить класс под узкий экран -- это их работа."""
        made_up = (CSS + "\n.probe2 { display: flex; }\n"
                   "@media (max-width: 760px) { .probe2 { display: grid; } }\n")
        self.assertNotIn("probe2", duplicates(made_up))


if __name__ == "__main__":
    unittest.main(verbosity=2)
