"""Обновление программы: проверить, скачать, распаковать поверх.

Программа живёт одной папкой и обновляется распаковкой архива поверх неё.
Делать это руками — скачать 275 МБ, найти папку, не задеть `data` — человек
будет раз в полгода, а в промежутке работать на версии, в которой уже
починены вещи, из-за которых он и писал.

Правила, из которых всё остальное следует:

1. **Молча наружу не ходим.** Проверка обновлений — отдельное разрешение,
   спрошенное один раз и записанное в настройки. Пока не разрешили, ни один
   запрос не уходит, и это проверяется тестом.
2. **Данные человека не трогаем никогда.** Обновляется код и базы карт,
   которые и так приходят из сборки; `user.sqlite`, сертификаты, кеш
   картинок, последняя охота остаются как были. Список того, что заменяется,
   — белый, а не чёрный: забыть дописать исключение легче, чем забыть
   разрешить нужное.
3. **Архив — чужие данные.** Пути внутри проверяются до распаковки: `..` и
   абсолютный путь в имени файла — это попытка записать мимо папки, и такой
   архив не применяется целиком, а не частично.
4. **Сначала рядом, потом на место.** Архив распаковывается во временную
   папку и только потом переносится: оборванная закачка не должна оставить
   половину программы.

Сюда вынесена вся логика без сети — чтобы её можно было проверить тестами, не
выходя наружу. Запросы делает `start.py`, у которого есть только стандартная
библиотека.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from typing import Any

# Откуда берутся обновления. Один репозиторий, вписанный в код: «куда ходить»
# не должно зависеть от файла настроек, который можно подменить.
REPO = "Divenprim/MTG-hunter"
RELEASES_URL = "https://api.github.com/repos/%s/releases/latest" % REPO
ASSET_NAME = "MTG-Hunter-Windows-portable.zip"

# Что в скачанной сборке заменяет то, что лежит на диске. Всё остальное --
# в том числе всё, что человек нажил, -- остаётся нетронутым.
REPLACE_DIRS = ("app", "web", "runtime")
REPLACE_FILES = (
    "start.py", "netutil.py", "build_db.py", "build_art.py", "fetch_sets.py",
    "make_cert.py", "open_browser.py", "requirements.txt", "README.md",
    "LICENSE", "MTG-Hunter.bat", "MTG-Hunter-LAN.bat", "MTG-Hunter-Tablet.bat",
    "MTG-Hunter-Phone.bat", "MTG-Hunter-Phone-Camera.bat",
)
# Базы из сборки: общие для всех, обновляются вместе с кодом.
REPLACE_DATA = ("sets.json", "cards.sqlite", "combos.sqlite", "art_hashes.sqlite")

# Чего в архиве быть не должно. Если это там есть -- архив не тот, и
# применять его нельзя: внутри чужая коллекция или чужие ключи.
NEVER = ("data/user.sqlite", "data/cert")


class UpdateError(Exception):
    """Обновление не применилось. Текст виден человеку, поэтому он по-русски."""


# --------------------------------------------------------------- версии

_NUM = re.compile(r"\d+")


def parse_version(text: str) -> tuple[int, ...]:
    """«v1.26.0» -> (1, 26, 0). Непонятное -> (0,), то есть «старее всего».

    Сравнивать версии строками нельзя: «1.9.0» больше «1.10.0» по алфавиту, и
    программа навсегда застревает на девятке.
    """
    nums = _NUM.findall(text or "")
    return tuple(int(n) for n in nums) if nums else (0,)


def is_newer(candidate: str, current: str) -> bool:
    """Строго новее. Равные версии -- не повод что-то скачивать."""
    return parse_version(candidate) > parse_version(current)


def pick_asset(release: dict[str, Any]) -> dict[str, Any] | None:
    """Файл сборки среди приложенных к релизу."""
    for asset in release.get("assets") or []:
        if asset.get("name") == ASSET_NAME:
            return asset
    return None


def read_release(payload: bytes | str) -> dict[str, Any]:
    """Ответ GitHub -> то немногое, что нам из него нужно.

    Ответ чужого сервера -- данные, а не указания: берём три поля и проверяем
    их тип, остальное не трогаем.
    """
    try:
        raw = json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise UpdateError("не разобрать ответ GitHub: %s" % exc) from exc
    if not isinstance(raw, dict):
        raise UpdateError("GitHub ответил не тем, чем обычно")
    tag = str(raw.get("tag_name") or "")
    asset = pick_asset(raw) or {}
    url = str(asset.get("browser_download_url") or "")
    if url and not url.startswith("https://github.com/" + REPO + "/"):
        # Ссылка не туда, куда мы собирались: качать по ней нельзя.
        raise UpdateError("ссылка на сборку ведёт не в репозиторий программы")
    return {
        "version": tag,
        "name": str(raw.get("name") or ""),
        "notes": str(raw.get("body") or ""),
        "url": url,
        "size": int(asset.get("size") or 0),
        "published": str(raw.get("published_at") or ""),
    }


# --------------------------------------------------------------- настройки

def update_setting(settings: dict[str, Any]) -> str | None:
    """Что человек решил насчёт проверки обновлений: "yes", "no" или ничего."""
    value = settings.get("update_check")
    if value in ("yes", "no"):
        return value
    # Старые настройки могли хранить булево -- понимаем и его.
    if isinstance(value, bool):
        return "yes" if value else "no"
    return None


def may_check(settings: dict[str, Any]) -> bool:
    """Можно ли спрашивать GitHub. Молчание -- это «нет», а не «да»."""
    return update_setting(settings) == "yes"


# --------------------------------------------------------------- архив

def archive_root(names: list[str]) -> str:
    """Общая папка внутри архива: сборка кладёт всё в «MTG-Hunter/»."""
    tops = {n.split("/", 1)[0] for n in names if n and not n.startswith("/")}
    tops.discard("")
    if len(tops) != 1:
        raise UpdateError("в архиве не одна папка верхнего уровня: %s"
                          % ", ".join(sorted(tops)[:4]))
    return tops.pop()


def check_names(names: list[str]) -> None:
    """Проверить пути до распаковки.

    Имя файла в архиве -- это строка, которую написал тот, кто архив собрал.
    `../../Windows/System32/x` в ней означает запись мимо нашей папки.
    """
    for name in names:
        clean = name.replace("\\", "/")
        if clean.startswith("/") or (len(clean) > 1 and clean[1] == ":"):
            raise UpdateError("в архиве абсолютный путь: %s" % name)
        if any(part == ".." for part in clean.split("/")):
            raise UpdateError("в архиве путь наружу: %s" % name)
    root = archive_root(names)
    for name in names:
        tail = name.replace("\\", "/")[len(root) + 1:]
        if tail in NEVER:
            raise UpdateError("в архиве чужие данные: %s" % tail)


def plan_from(root_dir: str) -> list[tuple[str, str]]:
    """Что откуда переносить: (путь в распакованном, путь относительно папки).

    Белый список: всё, чего здесь нет, остаётся на диске как было.
    """
    plan: list[tuple[str, str]] = []
    for name in REPLACE_DIRS:
        src = os.path.join(root_dir, name)
        if os.path.isdir(src):
            plan.append((src, name))
    for name in REPLACE_FILES:
        src = os.path.join(root_dir, name)
        if os.path.isfile(src):
            plan.append((src, name))
    for name in REPLACE_DATA:
        src = os.path.join(root_dir, "data", name)
        if os.path.isfile(src):
            plan.append((src, os.path.join("data", name)))
    return plan


def unpack(archive: str, into: str) -> str:
    """Распаковать во временную папку и вернуть путь к корню сборки."""
    with zipfile.ZipFile(archive) as zf:
        names = zf.namelist()
        check_names(names)
        root = archive_root(names)
        zf.extractall(into)
    out = os.path.join(into, root)
    if not os.path.isdir(out):
        raise UpdateError("в архиве нет папки %s" % root)
    return out


def apply_update(unpacked_root: str, target: str) -> list[str]:
    """Перенести новое поверх старого. Возвращает то, что заменилось.

    Переносим по одному, начиная с папок: если перенос оборвётся, часть
    файлов будет новой, часть старой -- неприятно, но программа запустится и
    скажет об этом. Полностью безопасной эта операция быть не может: мы
    переписываем работающую программу её же руками.
    """
    done: list[str] = []
    for src, rel in plan_from(unpacked_root):
        dst = os.path.join(target, rel)
        os.makedirs(os.path.dirname(dst) or target, exist_ok=True)
        if os.path.isdir(src):
            old = dst + ".old"
            if os.path.isdir(old):
                shutil.rmtree(old, ignore_errors=True)
            if os.path.isdir(dst):
                os.replace(dst, old)
            shutil.move(src, dst)
            shutil.rmtree(old, ignore_errors=True)
        else:
            shutil.copy2(src, dst)
        done.append(rel)
    return done


def human_size(size: int) -> str:
    """«275 МБ» вместо «288400848»."""
    mb = (size or 0) / 1048576.0
    if mb >= 1024:
        return "%.1f ГБ" % (mb / 1024)
    return "%.0f МБ" % mb if mb >= 10 else "%.1f МБ" % mb
