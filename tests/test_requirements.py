"""Список зависимостей: то, что ломает установку у всех сразу.

Здесь проверяется не код, а файл, с которого начинается первый запуск. Два
случая, на которых программа не запускалась ни на одной чистой машине, и ни
один из них не виден ни в коде, ни в тестах логики:

  * **требование, которое pip не может выполнить.** У winsdk на PyPI выпущены
    одни пре-релизы (1.0.0b1 … 1.0.0b10), а pip под «>=1.0.0» пре-релизы не
    берёт. Установка обрывалась на этой строке, run.bat печатал «setup
    failed», и программа не стартовала. На машине разработчика всё работало:
    там пакет уже стоял;
  * **тестовые пакеты в общем списке.** playwright с браузером весит больше
    самой программы, а пользователю он не нужен ни разу.

Чего здесь нет и не будет: проверки «похожее имя -- значит опечатка». Она тут
была и оказалась неправа: httpx2 -- настоящий пакет, и starlette с версии 1.6
просит именно его («import httpx2 as httpx»). Угадывать опечатки по написанию
имени -- плохая затея, и проверка, которая это делала, удалена.

Сети тут нет и быть не должно. Обе проверки делаются по тому, что уже стоит в
окружении: если установленная версия -- пре-релиз, значит pip выбрал её не по
этому требованию, и на чистой машине выбирать будет нечего.
"""

import os
import re
import sys
import unittest
from importlib import metadata

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = os.path.join(ROOT, "requirements.txt")
DEV = os.path.join(ROOT, "requirements-dev.txt")

# Пакеты, которые нужны только тестам. В списке для пользователя их быть не
# должно: playwright с браузером -- это сотни мегабайт сверх программы, и
# каждый лишний пакет -- ещё один способ не запуститься.
TEST_ONLY = {"playwright", "esprima", "httpx", "httpx2", "pytest"}

PRE_RELEASE = re.compile(r"(a|b|rc|dev)\d*$", re.I)
LINE = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*([^;#]*)")


def read(path):
    """Строки требований: имя, дополнения, условие версии."""
    out = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith("#") or line.startswith("-r"):
                continue
            found = LINE.match(line)
            if found:
                out.append((found.group(1), (found.group(3) or "").strip(),
                            line))
    return out


def is_pre_release(version):
    """«1.0.0b10» -- пре-релиз, «1.0.0» -- нет."""
    return bool(PRE_RELEASE.search((version or "").split("+")[0]))


class TestRuntimeRequirements(unittest.TestCase):
    def setUp(self):
        self.reqs = read(RUNTIME)

    def test_the_file_is_not_empty(self):
        self.assertTrue(self.reqs)

    def test_every_requirement_is_installed_here(self):
        """Иначе проверять нечего: тесты идут в окружении, где всё стоит."""
        for name, _spec, line in self.reqs:
            if "sys_platform" in line and not sys.platform.startswith("win"):
                continue
            try:
                metadata.version(name)
            except metadata.PackageNotFoundError:
                self.fail("%s объявлен, но не установлен" % name)

    def test_a_prerelease_package_is_asked_for_as_a_prerelease(self):
        """Главная проверка: выполнимо ли требование на чистой машине.

        pip по умолчанию пре-релизы не ставит. Если единственная версия,
        которая у пакета есть, -- пре-релиз, а в требовании написано просто
        «>=1.0.0», то на машине, где пакета ещё нет, установка оборвётся.
        """
        for name, spec, line in self.reqs:
            if "sys_platform" in line and not sys.platform.startswith("win"):
                continue
            try:
                here = metadata.version(name)
            except metadata.PackageNotFoundError:
                continue
            if not is_pre_release(here):
                continue
            self.assertTrue(
                any(is_pre_release(part) for part in re.split(r"[<>=!~,]+", spec)),
                "%s стоит в версии %s -- это пре-релиз, а в требовании «%s» "
                "пре-релиза нет: pip на чистой машине эту версию не возьмёт, "
                "и установка оборвётся" % (name, here, line))

    def test_test_only_packages_are_not_forced_on_the_user(self):
        names = {name.lower() for name, _spec, _line in self.reqs}
        stowaways = sorted(names & TEST_ONLY)
        self.assertEqual(stowaways, [],
                         "это нужно только тестам: %s" % stowaways)

    def test_nothing_is_asked_for_twice(self):
        """Один пакет -- одна строка: две записи расходятся молча."""
        names = [name.lower() for name, _spec, _line in self.reqs]
        twice = sorted({n for n in names if names.count(n) > 1})
        self.assertEqual(twice, [], "повторы: %s" % twice)


class TestDevRequirements(unittest.TestCase):
    def test_the_dev_list_exists_and_pulls_in_the_runtime_one(self):
        self.assertTrue(os.path.exists(DEV))
        with open(DEV, encoding="utf-8") as fh:
            self.assertIn("-r requirements.txt", fh.read())

    def test_what_the_tests_need_is_listed_there(self):
        names = {name.lower() for name, _spec, _line in read(DEV)}
        for needed in ("esprima", "playwright"):
            self.assertIn(needed, names)
        # Клиент для TestClient -- какой-нибудь из двух: starlette сначала
        # просит httpx2, а на старых версиях обходится httpx.
        self.assertTrue(names & {"httpx", "httpx2"}, names)


if __name__ == "__main__":
    unittest.main()
