"""A sample of real decks from Archidekt, to answer a conditional question.

Why this exists at all. EDHREC already aggregates thousands of decks and says
how usual each card is -- app/edhrec.py uses that, and nothing here replaces
it. What EDHREC cannot answer is a *conditional* question: not "how many decks
run this card" but "of the decks that look like mine, how many run it". That
needs the decklists themselves, so a sample of them is fetched and kept.

Три вида выборки -- три разных вопроса:

  * `cmd:<командир>`  -- кто играет с этим командиром;
  * `fmt:<формат>`    -- что вообще играют в модерне;
  * `cards:<формат>|<карта>|<карта>` -- колоды формата, где стоят ЭТИ карты.

Третий появился последним, и для 60-карточных колод он главный. Выборка по
формату тащит все архетипы подряд: 8-Rack, бёрн, трон и эльфы в одной куче, и
на любой конкретный архетип приходится несколько колод из полутора сотен --
меньше, чем нужно, чтобы соседство вообще считалось соседством. Поиск
Archidekt умеет фильтр `cardName`, причём повторённый -- это И, а не ИЛИ:
`cardName=Thoughtseize&cardName=Liliana of the Veil` даёт 51 колоду из тысячи
модерновых. Это и есть архетип, заданный двумя картами из вашего же списка.

How it behaves towards someone else's server, in order of importance:

  * nothing is fetched unless the user presses the button. Opening a panel,
    opening a deck, starting the program -- none of that reaches Archidekt;
  * 1.5 seconds between requests, one connection, our own user agent;
  * a deck is fetched once and then lives in the cache on disk, so a bigger
    sample later only costs the decks that are new;
  * колода, которая заведомо не годится, не качается вовсе. В выдаче поиска
    уже лежат `size`, `private` и `updatedAt` -- по ним видно и огрызок, и
    закрытую колоду, и список, который не трогали с 2021 года. Раньше такая
    колода стоила полутора секунд запроса и выбрасывалась после;
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

import hashlib
import json
import os
import time
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Callable, Iterable

import requests

from .deckimport import ArchidektSource, ImportError_
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
# `size` в запросе -- это число карт в колоде, а не размер страницы: size=2
# просит двухкарточные колоды и отдаёт мусор. Для 60-карточных форматов он
# вреден и так: списки лежат и по 60, и по 75 с сайдбордом. Зато `size` в
# ОТВЕТЕ полезен -- см. `_worth_fetching`.
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

# Сколько карт должно быть заявлено в выдаче поиска, чтобы колоду вообще
# качать. Это копии, а не названия: 60-карточная колода с сайдбордом -- это
# 60..90 карт, командирская -- 100. Берём с запасом вниз: лучше скачать
# лишнюю и отбросить по настоящему списку, чем пропустить живую колоду.
MIN_SIZE = {"cmd": 80, "fmt": 55, "cards": 55}

# Старше скольких дней колода выборке не нужна. Для 60-карточных форматов
# это главный фильтр качества: поиск сортирует по просмотрам, а самые
# просматриваемые модерн-колоды -- это списки 2021 года, где ещё играли
# то, что давно забанено. У командира метагейм ползёт медленнее, и там
# порог стоит просто от трухи.
FRESH_DAYS = {"cmd": 1460, "fmt": 400, "cards": 400}

# Больше трёх карт в фильтре -- это уже не архетип, а ваш собственный
# список: Archidekt найдёт три колоды, и статистики из них не выйдет.
CARDS_MAX = 3

# Basic lands are in every deck and say nothing about similarity.
BASICS = {
    "plains", "island", "swamp", "mountain", "forest", "wastes",
    "snow-covered plains", "snow-covered island", "snow-covered swamp",
    "snow-covered mountain", "snow-covered forest",
}


class ArchidektError(RuntimeError):
    """Something went wrong talking to Archidekt, said in Russian for the UI."""


# --------------------------------------------------------------------------- #
# Ключи выборок
# --------------------------------------------------------------------------- #

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


def cards_key(fmt: str, names: Iterable[str]) -> str:
    """Выборка по архетипу: колоды формата, где есть все названные карты.

    Имена сортируются, чтобы «Thoughtseize + Liliana» и «Liliana +
    Thoughtseize» были одной выборкой, а не двумя файлами с одинаковым
    содержимым.
    """
    clean: list[str] = []
    seen: set[str] = set()
    for name in names or ():
        one = " ".join((name or "").split())
        if not one or one.lower() in seen:
            continue
        seen.add(one.lower())
        clean.append(one)
    if not clean:
        return format_key(fmt)
    clean.sort(key=str.lower)
    return "cards:" + (fmt or "").strip().lower() + "|" + "|".join(clean[:CARDS_MAX])


def kind_of(key: str) -> str:
    """cmd | fmt | cards -- какой это вопрос."""
    if key.startswith("fmt:"):
        return "fmt"
    if key.startswith("cards:"):
        return "cards"
    return "cmd"


def key_parts(key: str) -> tuple[str, str, list[str]]:
    """(вид, формат-или-имя, карты фильтра)."""
    kind = kind_of(key)
    if kind == "cards":
        rest = key[len("cards:"):]
        head, _sep, tail = rest.partition("|")
        return kind, head, [c for c in tail.split("|") if c]
    if kind == "fmt":
        return kind, key[4:], []
    return kind, key[4:] if key.startswith("cmd:") else key, []


def title_of(key: str) -> str:
    """Как назвать выборку человеку, без подробностей оформления."""
    kind, head, cards = key_parts(key)
    if kind == "cards":
        return " + ".join(cards)
    return head


def search_url(key: str, page: int) -> str:
    """Адрес поиска для этой выборки."""
    kind, head, cards = key_parts(key)
    if kind == "cmd":
        return SEARCH_COMMANDER % (urllib.parse.quote(head), page)

    code = DECK_FORMAT.get(head)
    if not code:
        raise ArchidektError(
            "для формата «%s» выборка чужих колод не настроена" % head)
    url = SEARCH_FORMAT % (code, page)
    # Повторённый cardName -- это И: проверено, одна карта даёт 554 колоды
    # из тысячи модерновых, две -- 51. Через запятую не работает вовсе:
    # приходит count = -1 и пустой список.
    for card in cards[:CARDS_MAX]:
        url += "&cardName=" + urllib.parse.quote(card)
    return url


def min_cards_for(key: str) -> int:
    """Ниже скольких разных карт колода в выборку не годится."""
    return COMMANDER_MIN if kind_of(key) == "cmd" else SIXTY_MIN


def _cache_path(key: str) -> str:
    folder = os.path.join(data_dir(), "archidekt")
    os.makedirs(folder, exist_ok=True)
    kind, head, cards = key_parts(key)
    if kind == "fmt":
        return os.path.join(folder, "fmt-" + slug(head) + ".json")
    if kind == "cards":
        # Длинное имя файла -- это отказ записи на Windows, а не косметика:
        # три карты вроде «Urza's Saga» дают под сотню символов. Хвост
        # заменяется коротким отпечатком ключа, и совпадений у него не
        # бывает, потому что ключ в отпечаток и уходит.
        tail = "-".join(slug(c) for c in cards)
        if len(tail) > 60:
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
            tail = slug(cards[0])[:40] + "-" + digest
        return os.path.join(folder, "cards-" + slug(head) + "-" + tail + ".json")
    return os.path.join(folder, slug(head) + ".json")


# --------------------------------------------------------------------------- #
# Чтение колоды из выборки
#
# В кеше лежат колоды двух видов. Старые -- простым списком имён: так их
# писали до того, как выборка научилась считать копии и сайдборд. Новые --
# разбором: что в мейне и по сколько, что в сайде, когда колоду обновляли.
# Читать нужно оба: у человека на диске лежат сотни скачанных колод, и
# выбрасывать их ради формы записи было бы глупо.
# --------------------------------------------------------------------------- #

def deck_main(entry: Any) -> dict[str, int]:
    """Мейн колоды: имя -> сколько копий."""
    if isinstance(entry, list):
        return {str(name): 1 for name in entry if name}
    if isinstance(entry, dict):
        return {str(k): int(v or 1) for k, v in (entry.get("main") or {}).items()}
    return {}


def deck_side(entry: Any) -> dict[str, int]:
    """Сайдборд колоды. У старых записей его нет -- там пусто, а не ноль."""
    if isinstance(entry, dict):
        return {str(k): int(v or 1) for k, v in (entry.get("side") or {}).items()}
    return {}


def deck_names(entry: Any) -> list[str]:
    """Имена мейна списком -- то, что раньше лежало в кеше целиком."""
    return list(deck_main(entry).keys())


def deck_meta(entry: Any) -> dict[str, Any]:
    """Что известно о колоде помимо карт: имя, дата, просмотры."""
    if isinstance(entry, dict):
        return {k: v for k, v in entry.items() if k not in ("main", "side")}
    return {}


def has_sides(data: dict[str, Any]) -> int:
    """В скольких колодах выборки известен сайдборд."""
    return sum(1 for entry in (data.get("decks") or {}).values()
               if deck_side(entry))


# --------------------------------------------------------------------------- #
# Кеш на диске
# --------------------------------------------------------------------------- #

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
                "skipped": {}, "meta": {}, "pages_done": 0, "updated": None}
    data.setdefault("key", key)
    data.setdefault("ids", [])
    data.setdefault("decks", {})
    data.setdefault("failed", [])
    data.setdefault("skipped", {})
    data.setdefault("meta", {})
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


def _age_days(stamp: str | None) -> float | None:
    """Сколько дней назад колоду трогали. None -- дата не разобралась."""
    if not stamp:
        return None
    text = str(stamp).replace("Z", "+00:00")
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).total_seconds() / 86400.0


def freshness(data: dict[str, Any]) -> dict[str, Any]:
    """Насколько свежи колоды выборки: сколько им дней и скольким известно.

    Нужно сказать вслух. Числа из выборки, собранной по просмотрам, звучат
    одинаково солидно и для списка, который обновляли вчера, и для списка,
    который лежит нетронутым с 2021 года, -- а стоят они разного.
    """
    ages = []
    for entry in (data.get("decks") or {}).values():
        age = _age_days(deck_meta(entry).get("updated"))
        if age is not None:
            ages.append(age)
    if not ages:
        return {"known": 0, "median_days": None, "oldest_days": None,
                "fresh_year": 0}
    ages.sort()
    return {
        "known": len(ages),
        "median_days": int(ages[len(ages) // 2]),
        "oldest_days": int(ages[-1]),
        "fresh_year": sum(1 for a in ages if a <= 365),
    }


def state(key: str, target: int = DEFAULT_TARGET) -> dict[str, Any]:
    """What the interface needs to show without touching the network."""
    data = load(key)
    kind, head, cards = key_parts(key)
    reasons: dict[str, int] = {}
    for reason in (data.get("skipped") or {}).values():
        reasons[reason] = reasons.get(reason, 0) + 1
    return {
        "key": key,
        # Старое имя поля: интерфейс и проверки читают его давно, и ломать
        # их ради вида ключа незачем. Для выборки по формату тут лежит
        # название формата, для выборки по картам -- сами карты.
        "commander": title_of(key),
        "kind": {"cmd": "commander", "fmt": "format", "cards": "cards"}[kind],
        "format": head if kind != "cmd" else None,
        "cards": cards,
        "decks": len(data["decks"]),
        "ids_known": len(data["ids"]),
        "failed": len(data["failed"]),
        "skipped": reasons,
        "with_side": has_sides(data),
        "fresh": freshness(data),
        "target": max(0, min(int(target or 0), MAX_TARGET)),
        # Поиск кончился -- колод по этому запросу у Archidekt больше нет.
        # Для выборки по двум картам это обычное дело: их и бывает полсотни.
        # Без этого слова интерфейс вечно показывал бы «24 из 150», а кнопка
        # «собрать ещё» тратила бы запросы на пустые страницы.
        "exhausted": bool(data.get("exhausted")),
        "updated": data.get("updated"),
        "done": len(data["decks"]) >= max(0, min(int(target or 0), MAX_TARGET)),
    }


# --------------------------------------------------------------------------- #
# Сбор
# --------------------------------------------------------------------------- #

class Sampler:
    """One session's worth of fetching, with the throttle it owes."""

    def __init__(self) -> None:
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._source = ArchidektSource()
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
        """One page of deck ids. Returns how many new ones were added.

        Здесь же отсев по тому, что видно прямо в выдаче: закрытая колода,
        огрызок на двадцать карт и список, который не трогали годами, стоят
        ровно одного запроса -- и этот запрос незачем делать.
        """
        page = int(data.get("pages_done") or 0) + 1
        payload = self._get(search_url(key, page))
        known = {str(x) for x in data["ids"]} | {str(x) for x in data["failed"]}
        known |= set(data.get("skipped") or {})
        added = 0
        for row in payload.get("results") or []:
            deck_id = row.get("id")
            if deck_id is None or str(deck_id) in known:
                continue
            reason = _worth_fetching(key, row)
            if reason:
                data.setdefault("skipped", {})[str(deck_id)] = reason
                continue
            data["ids"].append(deck_id)
            data.setdefault("meta", {})[str(deck_id)] = {
                "name": row.get("name") or "",
                "updated": row.get("updatedAt") or "",
                "views": int(row.get("viewCount") or 0),
                "size": int(row.get("size") or 0),
            }
            added += 1
        data["pages_done"] = page
        # No results at all means the search is exhausted; remember that by
        # leaving pages_done where it is so the next call does not spin.
        if not (payload.get("results") or []):
            data["exhausted"] = True
        return added

    def one_deck(self, deck_id: Any,
                 min_cards: int = COMMANDER_MIN) -> dict[str, Any] | None:
        """Колода как она играется: мейн с копиями и сайдборд отдельно.

        Копии и сайд раньше выбрасывались: в кеш уходил список имён. Для
        командирской колоды потеря невелика -- там всё по одной, -- а в
        модерне «играют по 4» и «держат в сайде» это половина ответа на
        вопрос, ради которого колоды и качались.
        """
        self._throttle()
        try:
            parsed = self._source.fetch(str(deck_id), self.session)
        except ImportError_:
            return None          # private, deleted, or not a deck any more
        except requests.RequestException:
            return None
        main: dict[str, int] = {}
        side: dict[str, int] = {}
        for entry in parsed.entries:
            if not entry.name:
                continue
            if entry.section in ("main", "commander"):
                main[entry.name] = main.get(entry.name, 0) + int(entry.quantity or 1)
            elif entry.section == "side":
                side[entry.name] = side.get(entry.name, 0) + int(entry.quantity or 1)
        # Огрызок -- не колода: список в работе или просто куча карт только
        # размоет статистику. Но порог у форматов разный. Сотня в
        # командирской колоде -- это сто РАЗНЫХ карт, а в модерне их бывает
        # и двадцать: четыре копии каждой. Прежний порог в 60 имён, общий
        # для всех, выбросил бы почти весь модерн целиком.
        if len(main) < max(1, min_cards):
            return None
        return {"main": main, "side": side}


def _worth_fetching(key: str, row: dict[str, Any]) -> str | None:
    """Почему эту колоду качать не стоит -- или None, если стоит."""
    kind = kind_of(key)
    if row.get("private"):
        return "private"
    size = row.get("size")
    try:
        size = int(size)
    except (TypeError, ValueError):
        size = None
    if size is not None and size < MIN_SIZE.get(kind, 55):
        return "small"
    age = _age_days(row.get("updatedAt"))
    limit = FRESH_DAYS.get(kind, 0)
    if age is not None and limit and age > limit:
        return "old"
    return None


def _as_record(fetched: Any, meta: dict[str, Any] | None) -> Any:
    """Что положить в кеш: разбор колоды плюс то, что знал поиск.

    Заглушки в проверках отдают просто список имён -- и это рабочий случай,
    а не ошибка: так же выглядят колоды в старых кешах.
    """
    if isinstance(fetched, list):
        record: dict[str, Any] = {"main": {str(n): 1 for n in fetched if n},
                                  "side": {}}
    elif isinstance(fetched, dict):
        record = {"main": dict(fetched.get("main") or {}),
                  "side": dict(fetched.get("side") or {})}
    else:
        return None
    for field, value in (meta or {}).items():
        record.setdefault(field, value)
    return record


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
            got = sampler.one_deck(deck_id, min_cards_for(key))
            record = _as_record(got, (data.get("meta") or {}).get(str(deck_id)))
            if record is None:
                # Private, deleted, or not a hundred cards: remember it as
                # failed so the next chunk does not try it again.
                data["failed"].append(deck_id)
                data["ids"] = [x for x in data["ids"] if x != deck_id]
            else:
                data["decks"][str(deck_id)] = record
            fetched += 1
            if progress:
                progress("колод в выборке: %d" % len(data["decks"]))
    finally:
        _save(key, data)

    result = state(key, target)
    result["exhausted"] = bool(data.get("exhausted"))
    return result


__all__ = [
    "ArchidektError", "BASICS", "CARDS_MAX", "CHUNK", "COMMANDER_MIN",
    "DECK_FORMAT", "DEFAULT_TARGET", "FRESH_DAYS", "MAX_TARGET", "MIN_SIZE",
    "SIXTY_MIN", "Sampler", "cards_key", "collect", "commander_key",
    "deck_main", "deck_meta", "deck_names", "deck_side", "format_key",
    "freshness", "has_sides", "key_parts", "kind_of", "load", "min_cards_for",
    "search_url", "state", "title_of",
]
