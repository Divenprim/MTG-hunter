"""Документация должна описывать то, что есть, а не то, что было.

README в этом проекте -- не витрина, а справочник: по нему вспоминают, где
что лежит и почему сделано именно так. Справочник, который отстал, хуже
отсутствующего: он уверенно отправляет не туда.

Проверяется механически то, что механически проверяемо:

  * упомянутый файл существует. «Смотрите `app/stock.py`» в тексте про
    модуль, который переименовали, -- тупик;
  * упомянутый маршрут есть в main.py;
  * названия вкладок в тексте совпадают с теми, что человек видит на
    экране. Поймано на живом: текст звал вкладку «Похожие колоды», а на
    экране она «Под ваш состав»;
  * у каждой большой возможности есть свой раздел. Добор у продавцов жил в
    программе три версии и не был описан ни строкой.
"""

import io
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with io.open(os.path.join(ROOT, *parts), encoding="utf-8") as fh:
        return fh.read()


README = read("README.md")
MAIN = read("app", "main.py")
HTML = read("web", "index.html")

DOCS = ("README.md", "REVIEW_PLAN.md")

# Возможности, у которых должен быть свой кусок текста. Слева -- то, что
# ищется в README, справа -- признак того, что возможность вообще есть.
FEATURES = (
    ("Что ещё есть у продавцов из плана", "/api/hunt/restock"),
    ("Что купить первым", "/api/shopping"),
    ("deckFormat", "deckFormat"),
    ("По картам архетипа", "/api/cooccur/signature"),
    ("По сколько копий", "cooccur.copies("),
    ("что держат в сайде", "cooccur.sideboard("),
    ("Сайдборд", "buy-noside"),
    ("Цена чего именно", "rub_plain"),
    ("Обновить выборку", "/api/cooccur/refresh"),
    ("Есть столько-то рублей", "buy-budget"),
    ("Сравнить со своей колодой", "/api/cooccur/neighbour"),
    ("Чем архетип отличается от формата", "against_format"),
    ("Сверено с чужими сайдбордами", "_cached_sample"),
    ("Что изменилось в ценах", "/api/prices/moves"),
    ("Готов за столько-то", "coll-moves"),
    ("Дёшево сегодня или дёшево вообще", "price_bands"),
)


def made_by_code():
    """Имена того, что программа заводит сама, прямо из исходников.

    Берутся две вещи: файлы с расширением (`user.sqlite`, `settings.json`,
    `ui_shot.png`) и папки данных, которые код складывает из `DATA_DIR` и
    имени (`archidekt`, `image-cache`). Если имя названо в коде -- такой
    файл бывает, просто не в свежей копии репозитория.
    """
    out = set()
    for folder in ("app", "release", "tests"):
        here = os.path.join(ROOT, folder)
        for name in sorted(os.listdir(here)):
            if not name.endswith(".py"):
                continue
            text = read(folder, name)
            out.update(re.findall(r"[\w-]+\.(?:sqlite|json|log|png|csv|txt)", text))
            out.update(re.findall(r"""["']([\w-]+)["']""", text))
    text = read("start.py")
    out.update(re.findall(r"[\w-]+\.(?:sqlite|json|log|png|csv|txt)", text))
    out.update(re.findall(r"""["']([\w-]+)["']""", text))
    return out


def routes_in_code():
    return {re.sub(r"\{[^}]+\}", "{x}", r)
            for r in re.findall(r'@app\.\w+\("([^"]+)"', MAIN)}


class TestPointersLead(unittest.TestCase):
    """Всё, на что документация показывает пальцем, должно существовать."""

    def test_mentioned_files_exist(self):
        """Либо файл лежит на диске, либо его создаёт код.

        Часть путей в README -- это не исходники, а то, что заводится при
        работе: `data/user.sqlite`, `data/image-cache`, снимок экрана из
        браузерного сценария. В чистой копии репозитория их нет, и сборка
        в Actions спотыкалась ровно об это: текст был верен, а проверка
        требовала, чтобы будущее уже случилось. Поэтому для такого пути
        спрашивается другое -- заводит ли его кто-нибудь в коде. README,
        показавший на файл, которого не бывает вовсе, по-прежнему ошибка.
        """
        made = made_by_code()
        for doc in DOCS:
            text = read(doc)
            said = set(re.findall(r"`((?:app|web|tests|data)/[\w./-]+)`", text))
            gone = [f for f in sorted(said)
                    if not os.path.exists(os.path.join(ROOT, *f.split("/")))
                    and f.rstrip("/").rsplit("/", 1)[-1] not in made]
            self.assertEqual(gone, [], "%s: этих файлов нет" % doc)

    def test_mentioned_routes_exist(self):
        known = routes_in_code()
        for doc in DOCS:
            text = read(doc)
            said = set(re.findall(r"`(/api/[\w/{}.-]+)`", text))
            gone = [r for r in sorted(said)
                    if re.sub(r"\{[^}]+\}", "{x}", r) not in known]
            self.assertEqual(gone, [], "%s: этих маршрутов нет" % doc)


class TestNamesMatchTheScreen(unittest.TestCase):
    """Вкладку надо звать так, как её зовёт экран."""

    def test_tab_names_in_readme_are_real(self):
        shown = set(re.findall(r">([^<>{}]{3,40})</button>", HTML))
        shown = {s.strip() for s in shown}
        # Имена вкладок, которые README называет в кавычках-ёлочках рядом со
        # словом «вкладка». Берём только их: в тексте полно кавычек вокруг
        # обычных слов.
        said = set(re.findall(r"вкладк\w*\s+«([^»]{3,40})»", README))
        # В тексте строки переносятся по ширине, и название вкладки может
        # оказаться разорванным переводом строки. Для сравнения пробелы
        # схлопываются -- иначе проверка ловит вёрстку абзаца, а не ошибку.
        tidy = lambda s: " ".join(s.split())
        shown = {tidy(s) for s in shown}
        unknown = sorted(tidy(n) for n in said if tidy(n) not in shown)
        self.assertEqual(
            unknown, [],
            "в README названы вкладки, которых нет на экране: %s" % unknown)


class TestNothingBigIsUndocumented(unittest.TestCase):
    """У большой возможности должен быть свой раздел."""

    def test_each_feature_has_a_section(self):
        for words, proof in FEATURES:
            if proof not in MAIN and proof not in HTML:
                continue          # возможности нет -- и описывать нечего
            # assertIn печатает в отчёт всю строку целиком, а README --
            # это двести двадцать килобайт. Сообщение должно называть
            # пропажу, а не вываливать справочник.
            self.assertTrue(
                words in README,
                "возможность «%s» есть в коде, а в README про неё ни слова"
                % words)


if __name__ == "__main__":
    unittest.main(verbosity=2)
