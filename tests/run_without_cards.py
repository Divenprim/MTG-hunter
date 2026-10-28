"""Прогон тех проверок, которым не нужна офлайн-база карт.

Зачем это есть. Полная база карт -- триста мегабайт, которые собираются из
Scryfall; в сборке релиза она строится, а на main -- нет, и тащить её туда
на каждый толчок значило бы полчаса и чужой трафик за каждую запятую.

Но и оставлять main без проверок нельзя: почти тысяча тестов жила бы
исключительно на машине разработчика. Раньше здесь был полный набор без
условий -- и сборка main падала всегда, тремя сотнями ошибок «no such
table: card_names». Красная сборка, которая красная всегда, не значит
ничего: её перестают читать.

Поэтому: запускается всё, а модули, упавшие ИМЕННО на отсутствии базы,
считаются пропущенными и перечисляются поимённо. Список нигде не хранится
-- он выводится из того, что произошло, и не может разойтись с жизнью.
Любая другая ошибка -- настоящая, и прогон падает.

    python tests/run_without_cards.py
"""

import io
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

# Признаки того, что тест споткнулся о недостающую базу карт, а не о код.
NO_BASE = re.compile(
    r"no such table: (?:cards|card_names|card_tags|card_faces|ru_printings"
    r"|card_external_ids|cards_fts|tags)"
    r"|cards\.sqlite|Card database is missing|нет базы карт", re.I)


def module_of(case) -> str:
    """Имя модуля проверки: «test_query».

    Берётся у самого объекта, а не разбором его подписи: у случая с
    параметрами подпись выглядит как «... [fmt='modern']», и разбор
    выдавал модули с именами вроде «fmt='modern'».
    """
    real = getattr(case, "test_case", case)
    name = getattr(real.__class__, "__module__", "") or ""
    if name.startswith("unittest"):
        # Модуль не загрузился вовсе: unittest подставляет свой случай, и
        # имя сломанного файла лежит в подписи.
        return str(real).split()[0].split(".")[-1]
    return name or str(real)


def main() -> int:
    loader = unittest.TestLoader()
    # Папка tests пакетом не является (нет __init__.py), поэтому её и
    # делаем корнем поиска -- как это делает `unittest discover -s tests`.
    suite = loader.discover(start_dir=HERE, pattern="test_*.py")
    runner = unittest.TextTestRunner(stream=sys.stderr, verbosity=1)
    result = runner.run(suite)

    # Разбор идёт по модулям, а не по отдельным падениям. Причина: без
    # базы карт маршрут отвечает 503, а тест, который разбирает ответ,
    # падает на `KeyError: 'text'` -- про базу в таком следе нет ни слова,
    # хотя дело именно в ней. Модуль, у которого хоть одно падение прямо
    # называет недостающую базу, без неё нерабочий целиком.
    troubles = list(result.errors) + list(result.failures)
    sick = {module_of(case) for case, trace in troubles if NO_BASE.search(trace)}
    skipped = [(c, t) for c, t in troubles if module_of(c) in sick]
    real = [(c, t) for c, t in troubles if module_of(c) not in sick]

    print()
    print("Прогон без офлайн-базы карт: %d проверок." % result.testsRun)
    if skipped:
        modules = sorted({module_of(c) for c, _ in skipped})
        print("Пропущено из-за отсутствия базы карт: %d в модулях %s"
              % (len(skipped), ", ".join(modules)))
        print("Эти проверки идут в сборке релиза, где база собирается.")
    if real:
        print()
        print("Настоящих падений: %d" % len(real))
        for case, trace in real[:10]:
            print("  * %s" % case)
            print("    " + trace.strip().splitlines()[-1][:200])
        return 1
    print("Настоящих падений нет.")
    return 0


if __name__ == "__main__":
    # Отчёт самого unittest печатается в stderr, итог -- в stdout: в логе
    # сборки видно и то и другое, и видно, что чем является.
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                                  errors="replace", line_buffering=True)
    raise SystemExit(main())
