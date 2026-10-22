"""A sample of real decks built on one commander, from Archidekt.

Why this exists at all. EDHREC already aggregates thousands of decks and says
how usual each card is -- app/edhrec.py uses that, and nothing here replaces
it. What EDHREC cannot answer is a *conditional* question: not "how many decks
run this card" but "of the decks that look like mine, how many run it". That
needs the decklists themselves, so a sample of them is fetched and kept.

How it behaves towards someone else's server, in order of importance:

  * nothing is fetched unless the user presses the button. Opening a panel,
    opening a deck, starting the program -- none of that reaches Archidekt;
  * 1.5 seconds between requests, one connection, our own user agent;
  * a deck is fetched once and then lives in the cache on disk, so a bigger
    sample later only costs the decks that are new;
  * work comes in chunks. One call fetches a handful of decks and returns; the
    interface asks for the next chunk only while the user is still watching,
    so closing the panel stops the traffic;
  * the target is capped. A sample is a sample: past a few hundred decks the
    numbers stop moving and only the bill grows.

Honesty about what the sample is: Archidekt's search returns the decks it
chooses to return, most-viewed first, and a deck list on the internet is not a
random draw from all Commander decks. The numbers here describe the sample, and
the interface says so rather than calling them "the truth".
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from typing import Any, Callable

import requests

from .deckimport import ImportError_, fetch_archidekt
from .edhrec import slug
from .storage import data_dir

# Как просить колоды одного формата.
#
# Фильтр называется `deckFormat`, а НЕ `formats`. Здесь годами стоял
# `formats=3&size=100` -- и не делал ничего: проверка показала, что с
# `formats=1`, `=2`, ... `=9` приходит одна и та же выдача, те же колоды в
# том же порядке. Командирской она оказывалась только из-за
# `commanderName`. С `deckFormat=2` приходят ровно modern-колоды.
#
# `size` -- это число карт в колоде, а не размер страницы: size=2 просит
# двухкарточные колоды и отдаёт мусор. Для 60-карточных форматов он вреден
# и так: списки лежат и по 60, и по 75 с сайдбордом.
SEARCH_COMMANDER = (
    "https://archidekt.com/api/decks/v3/"
    "?deckFormat=3&orderBy=-viewCount&commanderName=%s&page=%d"
)
SEARCH_FORMAT = (
    "https://archidekt.com/api/decks/v3/"
    "?deckFormat=%d&orderBy=-viewCount&page=%d"
)

# Номера форматов у Archidekt. Выяснены запросами и проверены по самим
# колодам: формат колоды лежит в поле `deckFormat` (поле `format` всегда
# пустое), а что это за формат -- видно по легальностям карт и по названиям
# («SUP - Pauper - ...» при deckFormat=6, «Modern 20 Bolt» при 2).
# Перечислены только подтверждённые: legacy и vintage не проверялись, и
# гадать о них тут нечего.
DECK_FORMAT = {
    "standard": 1,
    "modern": 2,
    "commander": 3,
    "pauper": 6,
    "pioneer": 15,
}
USER_AGENT = "mtg-hunter/1.19.0 (local deckbuilding tool)"
TIMEOUT = 45
MIN_INTERVAL = 1.5

# One call fetches at most this many decks, so a request never hangs for
# minutes and the user can stop between chunks.
CHUNK = 12
DEFAULT_TARGET = 150
MAX_TARGET = 400

# Сколько РАЗНЫХ карт должно быть в колоде, чтобы она пошла в выборку.
# В командирской их около сотни -- там копий нет. В 60-карточной бывает и
# два десятка: по четыре копии каждой. Один порог на оба случая невозможен.
COMMANDER_MIN = 60
SIXTY_MIN = 18

# Basic lands are in every deck and say nothing about similarity.
BASICS = {
    "plains", "island", "swamp", "mountain", "forest", "wastes",
    "snow-covered plains", "snow-covered island", "snow-covered swamp",
    "snow-covered mountain", "snow-covered forest",
}


class ArchidektError(RuntimeError):
    """Something went wrong talking to Archidekt, said in Russian for the UI."""


def commander_key(name: str) -> str:
    """Выборка по командиру: «кто играет с этим командиром».

    В ключе лежит имя как есть, а не слаг: по нему идёт поиск на Archidekt
    (`commanderName=`), и «bartolome-del-presidio» там не найдётся. Слаг
    нужен только для имени файла и делается в `_cache_path`.
    """
    return "cmd:" + (name or "").strip()


def format_key(fmt: str) -> str:
    """Выборка по формату: «что вообще играют в модерне».

    Нужна потому, что командира у 60-карточной колоды нет, а вопрос «что
    играют в похожих колодах» у неё тот же самый. Раньше выборка умела
    только командира, и для модерна, пионера и паупера подсказок не было
    вовсе -- при том что сама статистика соседей формату безразлична.
    """
    return "fmt:" + (fmt or "").strip().lower()


def search_url(key: str, page: int) -> str:
    """Адрес поиска для этой выборки."""
    if key.startswith("fmt:"):
        fmt = key[4:]
        code = DECK_FORMAT.get(fmt)
        if not code:
            raise ArchidektError(
                "для формата «%s» выборка чужих колод не настроена" % fmt)
        return SEARCH_FORMAT % (code, page)
    name = key[4:] if key.startswith("cmd:") else key
    return SEARCH_COMMANDER % (urllib.parse.quote(name), page)


def min_cards_for(key: str) -> int:
    """Ниже скольких разных карт колода в выборку не годится."""
    return COMMANDER_MIN if not key.startswith("fmt:") else SIXTY_MIN


def _cache_path(key: str) -> str:
    folder = os.path.join(data_dir(), "archidekt")
    os.makedirs(folder, exist_ok=True)
    if key.startswith("fmt:"):
        return os.path.join(folder, "fmt-" + slug(key[4:]) + ".json")
    name = key[4:] if key.startswith("cmd:") else key
    return os.path.join(folder, slug(name) + ".json")


def load(key: str) -> dict[str, Any]:
    """The sample we already have. Never fetches anything.

    Командирские выборки лежат там же, где лежали: файл зовётся по слагу
    имени, и переход на ключи их не осиротил -- это десятки чужих запросов,
    терять их из-за переименования незачем.
    """
    try:
        with open(_cache_path(key), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"key": key, "ids": [], "decks": {}, "failed": [],
                "pages_done": 0, "updated": None}
    data.setdefault("key", key)
    data.setdefault("ids", [])
    data.setdefault("decks", {})
    data.setdefault("failed", [])
    data.setdefault("pages_done", 0)
    return data


def _save(key: str, data: dict[str, Any]) -> None:
    data["updated"] = time.time()
    path = _cache_path(key)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass  # a cache we cannot write is not a reason to lose the work


def state(key: str, target: int = DEFAULT_TARGET) -> dict[str, Any]:
    """What the interface needs to show without touching the network."""
    data = load(key)
    return {
        "key": key,
        # Старое имя поля: интерфейс и проверки читают его давно, и ломать
        # их ради вида ключа незачем. Для выборки по формату тут лежит
        # название формата.
        "commander": key.split(":", 1)[-1],
        "kind": "format" if key.startswith("fmt:") else "commander",
        "decks": len(data["decks"]),
        "ids_known": len(data["ids"]),
        "failed": len(data["failed"]),
        "target": max(0, min(int(target or 0), MAX_TARGET)),
        "updated": data.get("updated"),
        "done": len(data["decks"]) >= max(0, min(int(target or 0), MAX_TARGET)),
    }


class Sampler:
    """One session's worth of fetching, with the throttle it owes."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._last = 0.0

    def _throttle(self) -> None:
        wait = MIN_INTERVAL - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()

    def _get(self, url: str) -> Any:
        self._throttle()
        try:
            resp = self.session.get(url, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise ArchidektError("Archidekt не ответил: %s" % exc) from exc
        if resp.status_code == 429:
            raise ArchidektError(
                "Archidekt просит подождать (429). Выборку можно продолжить позже — "
                "то, что уже скачано, сохранено."
            )
        if resp.status_code >= 400:
            raise ArchidektError("Archidekt ответил ошибкой %s" % resp.status_code)
        try:
            return resp.json()
        except ValueError as exc:
            raise ArchidektError("Archidekt ответил не JSON") from exc

    def more_ids(self, key: str, data: dict[str, Any]) -> int:
        """One page of deck ids. Returns how many new ones were added."""
        page = int(data.get("pages_done") or 0) + 1
        payload = self._get(search_url(key, page))
        known = set(data["ids"]) | set(data["failed"])
        added = 0
        for row in payload.get("results") or []:
            deck_id = row.get("id")
            if deck_id is None:
                continue
            if str(deck_id) in {str(x) for x in known}:
                continue
            data["ids"].append(deck_id)
            added += 1
        data["pages_done"] = page
        # No results at all means the search is exhausted; remember that by
        # leaving pages_done where it is so the next call does not spin.
        if not (payload.get("results") or []):
            data["exhausted"] = True
        return added

    def one_deck(self, deck_id: Any,
                 min_cards: int = COMMANDER_MIN) -> list[str] | None:
        """A deck as the names it plays: the 99 plus the commander."""
        url = "https://archidekt.com/decks/%s" % deck_id
        self._throttle()
        try:
            parsed = fetch_archidekt(url, self.session)
        except ImportError_:
            return None          # private, deleted, or not a deck any more
        except requests.RequestException:
            return None
        names = [
            entry.name for entry in parsed.entries
            if entry.section in ("main", "commander") and entry.name
        ]
        # Огрызок -- не колода: список в работе или просто куча карт только
        # размоет статистику. Но порог у форматов разный. Сотня в
        # командирской колоде -- это сто РАЗНЫХ карт, а в модерне их бывает
        # и двадцать: четыре копии каждой. Прежний порог в 60 имён, общий
        # для всех, выбросил бы почти весь модерн целиком.
        if len(names) < max(1, min_cards):
            return None
        return names


def collect(
    key: str,
    target: int = DEFAULT_TARGET,
    chunk: int = CHUNK,
    sampler: Sampler | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Fetch up to `chunk` more decks towards `target`, then return the state.

    Deliberately partial: the caller asks again for the next chunk, so the
    traffic stops the moment the user stops watching. Whatever was fetched is
    saved even if the call ends in an error.
    """
    target = max(1, min(int(target or DEFAULT_TARGET), MAX_TARGET))
    chunk = max(1, min(int(chunk or CHUNK), CHUNK))
    data = load(key)
    if len(data["decks"]) >= target:
        return state(key, target)

    sampler = sampler or Sampler()
    fetched = 0
    id_pages = 0            # bounded: a search that returns nothing new must
    ID_PAGES_MAX = 3        # not turn one call into an endless crawl

    try:
        while fetched < chunk and len(data["decks"]) < target:
            pending = [
                deck_id for deck_id in data["ids"]
                if str(deck_id) not in data["decks"]
            ]
            if not pending:
                if data.get("exhausted") or id_pages >= ID_PAGES_MAX:
                    break
                id_pages += 1
                added = sampler.more_ids(key, data)
                if not added and data.get("exhausted"):
                    break
                continue

            deck_id = pending[0]
            names = sampler.one_deck(deck_id, min_cards_for(key))
            if names is None:
                # Private, deleted, or not a hundred cards: remember it as
                # failed so the next chunk does not try it again.
                data["failed"].append(deck_id)
                data["ids"] = [x for x in data["ids"] if x != deck_id]
            else:
                data["decks"][str(deck_id)] = names
            fetched += 1
            if progress:
                progress("колод в выборке: %d" % len(data["decks"]))
    finally:
        _save(key, data)

    result = state(key, target)
    result["exhausted"] = bool(data.get("exhausted"))
    return result


__all__ = [
    "ArchidektError", "BASICS", "CHUNK", "COMMANDER_MIN", "DECK_FORMAT",
    "DEFAULT_TARGET", "MAX_TARGET", "SIXTY_MIN", "Sampler", "collect",
    "commander_key", "format_key", "load", "min_cards_for", "search_url",
    "state",
]
