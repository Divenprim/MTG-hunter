"""FastAPI backend. Runs locally; the UI is plain HTML/JS served from web/."""

from __future__ import annotations

import base64
import json
import os
import socket
import threading
import uuid
from collections import OrderedDict
from dataclasses import replace
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import collection as collection_store
from . import combos as combo_store
from . import (
    archidekt, artscan, carddetect, cooccur, deckbuild, deckshape, favourites,
    family as family_store, formats, holdings, landsets, manabase,
    ocr, pile,
    goldfish,
    offermatch, orders, recommend, shops, undo as undo_store, whatsnew,
)
from .cards import DB_PATH, CardDB, database_is_complete, normalize_name
from .decks import DeckError, DeckStore
from .deckimport import DeckList, ImportError_, import_from_url, parse_text
from .hunt import (
    SELLER_FEE_DEFAULT, Filters, Hunter, Want, build_plan, compute_wants,
)
from .lineparse import SetIndex, parse_line
from .messages import drafts_for_plan
from .topdeck import TopdeckClient

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(ROOT, "web")
DATA_DIR = os.path.join(ROOT, "data")
COLLECTION_PATH = os.path.join(DATA_DIR, "collection.json")
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")

app = FastAPI(title="MTG Hunter", version="1.15.1")

_db: CardDB | None = None
_sets: SetIndex | None = None


def db() -> CardDB:
    global _db
    if _db is None:
        if not database_is_complete(DB_PATH):
            raise HTTPException(
                status_code=503,
                detail="Card database is missing or incomplete. Run: python build_db.py",
            )
        _db = CardDB(DB_PATH)
    return _db


def sets() -> SetIndex:
    global _sets
    if _sets is None:
        _sets = SetIndex.load()
    return _sets


def load_json(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #

class FiltersIn(BaseModel):
    languages: list[str] = Field(default_factory=list)
    min_condition: str | None = None
    max_price: int | None = None
    min_seller_refs: int | None = None
    include_shops: bool = True
    include_users: bool = True
    require_stated_language: bool = False
    require_stated_condition: bool = False
    exclude_proxy: bool = True
    cities: list[str] = Field(default_factory=list)

    def to_filters(self) -> Filters:
        return Filters(**self.model_dump())


class DeckImportIn(BaseModel):
    url: str | None = None
    text: str | None = None
    name: str | None = None


class WantIn(BaseModel):
    name: str
    quantity: int = 1
    set_code: str | None = None
    section: str = "main"


class HuntIn(BaseModel):
    wants: list[WantIn]
    filters: FiltersIn = Field(default_factory=FiltersIn)
    strategy: str = "sellers"
    # What one more seller is worth in postage and waiting. The plan spends up
    # to this much to avoid a seller, and never more.
    seller_fee: int = SELLER_FEE_DEFAULT
    use_collection: bool = True
    # Leave out the copies already ordered and on their way. Off by default:
    # a card in the post is not a card you have.
    skip_ordered: bool = False


class HuntLookupIn(BaseModel):
    """Where could this one card be bought, given the plan we already have?"""

    hunt_id: str
    name: str
    quantity: int = 1
    filters: FiltersIn = Field(default_factory=FiltersIn)


class HuntAddIn(BaseModel):
    """Confirmed: put this card in the order, from this listing."""

    hunt_id: str
    name: str
    quantity: int = 1
    offer_key: str = ""


class ReplanIn(BaseModel):
    """Rebuild a plan from a hunt already fetched, after the user changed
    their mind. No topdeck requests: the offers are the ones we already have."""

    hunt_id: str
    strategy: str = "sellers"
    seller_fee: int = SELLER_FEE_DEFAULT
    # Offer keys the user refused ("not this listing").
    skip_offers: list[str] = Field(default_factory=list)
    # Card names the user decided not to buy at all.
    skip_wants: list[str] = Field(default_factory=list)
    # Card name -> how many copies to take, when fewer than first planned.
    quantities: dict[str, int] = Field(default_factory=dict)
    # Card name -> the offer key the user chose by hand for it.
    pins: dict[str, str] = Field(default_factory=dict)
    # A seller the user would rather buy everything from.
    prefer_seller: str = ""


class OffersIn(BaseModel):
    names: list[str]


class MessagesIn(BaseModel):
    plan: dict[str, Any]
    template: str = "ru_polite"


class CollectionIn(BaseModel):
    text: str


class DeckIdsIn(BaseModel):
    """Несколько колод: сравнить между собой."""

    deck_ids: list[str] = Field(default_factory=list)


class CollectionAddIn(BaseModel):
    """Прибавить карты к коллекции, не трогая остальное."""

    cards: list[DeckCardIn] = Field(default_factory=list)


class PurchaseOrderItemIn(BaseModel):
    name: str
    quantity: int = 1
    unit_price: int = 0


class UndoIn(BaseModel):
    kind: str


class SampleIn(BaseModel):
    """Fetch one more chunk of real decks for this commander."""

    commander: str = ""
    deck_id: str = ""
    target: int = archidekt.DEFAULT_TARGET


class PurchaseOrderIn(BaseModel):
    seller_name: str
    seller_kind: str = "user"
    items: list[PurchaseOrderItemIn]


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

# --------------------------------------------------------------------------- #
# Доступ из локальной сети
# --------------------------------------------------------------------------- #

# run.bat кладёт сюда то, чем он запустил uvicorn. Само приложение адреса, на
# котором его слушают, не знает, а показать его надо: с планшета нужен не
# localhost, а адрес этого компьютера в сети.
BIND_HOST = os.environ.get("MTGH_HOST", "127.0.0.1")
BIND_PORT = os.environ.get("MTGH_PORT", "8765")
LAN_OPEN = BIND_HOST not in ("127.0.0.1", "localhost", "::1", "")


def lan_addresses() -> list[str]:
    """Адреса этого компьютера в локальной сети -- то, что набирают на планшете.

    Ничего наружу не отправляется: UDP-сокет только спрашивает у системы, с
    какого адреса ушёл бы пакет, и это спрашивается лишь тогда, когда имя
    машины не дало ни одного адреса.
    """
    found: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    if not found:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            found.append(probe.getsockname()[0])
        except OSError:
            pass
        finally:
            probe.close()
    return found


# По https сервер работает только в режиме для планшета, и адрес там другой.
# Подсказать планшету «http://...» значит подсказать неработающий адрес:
# соединения не будет, а выглядит это как «программа не работает».
SCHEME = os.environ.get("MTGH_SCHEME", "http")


def lan_urls() -> list[str]:
    return ["%s://%s:%s" % (SCHEME, ip, BIND_PORT) for ip in lan_addresses()]


# Корневой сертификат надо как-то донести до планшета, а по https он туда не
# попадёт: планшет ещё не знает этого сертификата и в соединение не пойдёт.
# Поэтому рядом с основным сервером поднимается крошечный обычный http, который
# умеет отдавать ровно один файл -- сам сертификат, и ничего больше.
CA_PORT = os.environ.get("MTGH_CA_PORT", "")
CA_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "data", "cert", "ca.pem")


def _serve_ca(port: int) -> None:
    import http.server

    data = open(CA_FILE, "rb").read()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:                        # noqa: N802
            if self.path.rstrip("/") not in ("/ca.pem", "/ca", ""):
                self.send_error(404)
                return
            self.send_response(200)
            # Тип для профиля: с ним iOS предлагает установить, а не показывает
            # текст сертификата на экране.
            self.send_header("Content-Type", "application/x-x509-ca-cert")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args: Any) -> None:       # noqa: D102
            pass

    http.server.HTTPServer(("0.0.0.0", port), Handler).serve_forever()


def _start_ca_server() -> None:
    if not CA_PORT or not os.path.exists(CA_FILE):
        return
    try:
        port = int(CA_PORT)
    except ValueError:
        return
    threading.Thread(target=_serve_ca, args=(port,), daemon=True).start()
    for ip in lan_addresses():
        print("[сеть] сертификат для планшета: http://%s:%d/ca.pem" % (ip, port))


def _say_where() -> None:
    """Напечатать адреса при запуске: с планшета нужен не localhost."""
    if not LAN_OPEN:
        return
    for url in lan_urls():
        print("[сеть] с планшета и телефона: %s" % url)
    print("[сеть] пароля нет: кто в этой сети, тот и видит вашу коллекцию")


_say_where()
_start_ca_server()


@app.get("/api/status")
def status() -> dict[str, Any]:
    built = database_is_complete(DB_PATH)
    stats = db().stats() if built else {"built": False}
    coll = collection_store.summary()
    return {
        "db": stats,
        "collection_cards": coll["copies"],
        "collection_distinct": coll["distinct"],
        "settings": load_json(SETTINGS_PATH, {}),
        "favourites": favourites.summary(),
        "backups": {
            "favourites": len(favourites.backups()),
            "collection": len(collection_store.backups()),
        },
        "lan": {"open": LAN_OPEN, "urls": lan_urls() if LAN_OPEN else []},
    }


@app.get("/api/search")
def search(
    q: str = "",
    limit: int = 60,
    offset: int = 0,
    sort: str = "relevance",
) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    database = db()
    rows = database.search(q, limit=limit, offset=offset, sort=sort)
    # `count` is a second full pass; only the first page needs it. Later pages
    # reuse the total the client already has.
    total = database.count(q) if offset == 0 else None
    return {
        "query": q,
        "count": len(rows),
        "total": total,
        "offset": offset,
        "sort": sort,
        "cards": rows,
    }


_SETS_CACHE: dict[str, Any] | None = None


@app.get("/api/sets")
def sets_list() -> dict[str, Any]:
    """Sets that actually have paper cards in our database, for the filter panel.

    Cached: it is a GROUP BY over 108k rows and cannot change until the
    database is rebuilt, but the page asks for it on every load.
    """
    global _SETS_CACHE
    if _SETS_CACHE is not None:
        return _SETS_CACHE
    rows = db().conn.execute(
        """
        SELECT set_code, set_name, set_type, MAX(released_at) AS released, COUNT(*) AS cards
        FROM cards
        WHERE set_code IS NOT NULL AND %s
        GROUP BY set_code
        ORDER BY released DESC
        """
        % "layout NOT IN ('art_series','token','double_faced_token','emblem')"
    ).fetchall()
    _SETS_CACHE = {"sets": [dict(r) for r in rows]}
    return _SETS_CACHE


_TYPE_CACHE: dict[str, Any] | None = None


@app.get("/api/types")
def types_list() -> dict[str, Any]:
    """Card type vocabulary, derived from the printings we actually have.

    Feeds the Archidekt-style type picker: you type, pick from suggestions and
    add each type as a removable token. Split on the em dash: the left side
    holds supertypes and card types, the right side holds subtypes.
    """
    global _TYPE_CACHE
    if _TYPE_CACHE is not None:
        return _TYPE_CACHE

    import re as _re

    primary: set[str] = set()
    sub: set[str] = set()
    rows = db().conn.execute(
        "SELECT DISTINCT type_line FROM cards WHERE type_line IS NOT NULL AND type_line <> ''"
    ).fetchall()
    for row in rows:
        line = (row["type_line"] or "").replace("//", "—")
        parts = _re.split(r"[—–]", line)
        for word in _re.findall(r"[A-Za-z'’-]{2,}", parts[0]):
            primary.add(word)
        for chunk in parts[1:]:
            for word in _re.findall(r"[A-Za-z'’-]{2,}", chunk):
                sub.add(word)

    # Types worth offering first; the rest are mostly oddities (Plane, Scheme…).
    common = [
        "Creature", "Instant", "Sorcery", "Artifact", "Enchantment", "Land",
        "Planeswalker", "Battle", "Legendary", "Snow", "Kindred", "Token", "Basic",
    ]
    ordered_primary = [t for t in common if t in primary] + sorted(primary - set(common))

    _TYPE_CACHE = {
        "types": ordered_primary,
        "subtypes": sorted(sub),
        "all": ordered_primary + sorted(sub),
    }
    return _TYPE_CACHE


_DROPS_CACHE: list[dict[str, Any]] | None = None

SECRET_LAIR_CODES = ("sld", "slc", "slp", "slu", "pssc", "sls", "slx")


def _compute_drops() -> list[dict[str, Any]]:
    """Split Secret Lair into individual drops.

    Scryfall has no drop field -- `sld` is one set holding 2754 cards from
    hundreds of products. What identifies a drop is a CONTIGUOUS RUN of
    collector numbers within one set and release date. Release date alone is
    not enough: 2025-07-14 holds the Sonic drop (#2081-2087), an unrelated
    Commander reprint drop (#2088-2101) and a Lotus Petal drop (#7030-7037).

    This is a heuristic, and it is labelled as one in the UI.
    """
    rows = db().conn.execute(
        """
        SELECT set_code, set_name, released_at, collector_number, name
        FROM cards
        WHERE set_code IN (%s) AND collector_number GLOB '[0-9]*'
        ORDER BY set_code, released_at, CAST(collector_number AS INTEGER)
        """
        % ",".join("'%s'" % c for c in SECRET_LAIR_CODES)
    ).fetchall()

    drops: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for row in rows:
        try:
            number = int("".join(ch for ch in row["collector_number"] if ch.isdigit()))
        except ValueError:
            continue
        same_product = (
            current is not None
            and current["set_code"] == row["set_code"]
            and current["released"] == row["released_at"]
            and number - current["last"] <= 1
        )
        if same_product:
            current["last"] = number
            current["names"].append(row["name"])
        else:
            if current:
                drops.append(current)
            current = {
                "set_code": row["set_code"],
                "set_name": row["set_name"],
                "released": row["released_at"],
                "first": number,
                "last": number,
                "names": [row["name"]],
            }
    if current:
        drops.append(current)

    for drop in drops:
        drop["count"] = len(drop["names"])
        drop["query"] = "s:%s cn>=%d cn<=%d" % (
            drop["set_code"], drop["first"], drop["last"]
        )
    drops.sort(key=lambda d: (d["released"] or ""), reverse=True)
    return drops


@app.get("/api/drops")
def drops_list(q: str = "", limit: int = 40) -> dict[str, Any]:
    """Secret Lair drops, searchable by ANY card inside them.

    This is what makes "find the Sonic cards" work: searching card names alone
    misses "Amy Rose" and "Knuckles the Echidna" (no "sonic" in the name) and
    wrongly returns "Sonic Screwdriver" from Doctor Who.
    """
    global _DROPS_CACHE
    if _DROPS_CACHE is None:
        _DROPS_CACHE = _compute_drops()

    needle = (q or "").strip().lower()
    if needle:
        hits = []
        for drop in _DROPS_CACHE:
            matched = [n for n in drop["names"] if needle in n.lower()]
            if matched:
                copy = dict(drop)
                copy["matched"] = matched
                hits.append(copy)
    else:
        hits = [dict(d, matched=[]) for d in _DROPS_CACHE]

    limit = max(1, min(limit, 200))
    return {
        "query": q,
        "total": len(hits),
        "drops": hits[:limit],
    }


# Russian labels for the themes people actually search by. Only slugs that
# exist in Tagger and expand to a useful number of cards are listed; the free
# text search below reaches all 4524 tags.
THEME_PRESETS: list[tuple[str, str]] = [
    ("рампа", "ramp"),
    ("мана-рок", "mana-rock"),
    ("мана-дорк", "mana-dork"),
    ("туторы", "tutor"),
    ("точечное удаление", "spot-removal"),
    ("масс-удаление", "sweeper"),
    ("возврат в руку", "removal-bounce"),
    ("контрмагия", "counterspell"),
    ("блинк", "flicker"),
    ("жертва", "repeatable-sacrifice-outlet"),
    ("смерть-триггеры", "death-trigger"),
    ("реанимация", "reanimate"),
    ("из кладбища", "castable-from-graveyard"),
    ("мельница", "mill-any"),
    ("самомельница", "mill-self"),
    ("сброс у соперника", "discard"),
    ("сброс себе", "discard-outlet"),
    ("добор карт", "draw"),
    ("колесо", "wheel-symmetrical"),
    ("кража существ", "theft-creature"),
    ("смена контроля", "control-changing-effects"),
    ("жетоны существ", "repeatable-creature-tokens"),
    ("счётчики +1/+1", "repeatable-pp-counters"),
    ("сокровища", "repeatable-treasures"),
    ("экипировка", "synergy-equipment"),
    ("чары на существо", "synergy-aura"),
    ("помехи атакующим", "hate-attacker"),
    ("помехи блокерам", "hate-blocker"),
    ("ненависть к кладбищу", "hate-graveyard"),
    ("защита", "protection"),
    ("эвейжн", "evasion"),
    ("лендфолл", "landfall"),
    ("доп. ходы", "extra-turn"),
    ("лайфгейн", "lifegain"),
    ("групповое добро", "group-hug"),
]

# Printed keyword abilities. Tagger has no tags for these, yet "a wall of
# Defenders" or "everything at flash speed" is exactly a deck direction.
KEYWORD_PRESETS: list[tuple[str, str]] = [
    ("дефендеры", "defender"),
    ("мгновенная скорость", "flash"),
    ("полёт", "flying"),
    ("пробивной", "trample"),
    ("смертельное касание", "deathtouch"),
    ("бдительность", "vigilance"),
    ("ускорение", "haste"),
    ("связь с жизнью", "lifelink"),
    ("первый удар", "first strike"),
    ("угроза", "menace"),
    ("защитник от порчи", "hexproof"),
    ("неразрушимый", "indestructible"),
    ("циклирование", "cycling"),
    ("каскад", "cascade"),
    ("прорицание", "scry"),
]


@app.get("/api/tags")
def tags_list(q: str = "", limit: int = 60) -> dict[str, Any]:
    """Functional tags, searchable. Feeds the theme picker.

    Purpose-based search ("ramp", "theft-creature") comes from Scryfall Tagger,
    which is community-curated -- far better than trying to infer intent from
    oracle text with regexes.
    """
    database = db()
    needle = (q or "").strip().lower()
    limit = max(1, min(limit, 300))

    if needle:
        rows = database.conn.execute(
            """
            SELECT slug, label, description, card_count, children
            FROM tags
            WHERE LOWER(slug) LIKE ? OR LOWER(label) LIKE ?
               OR LOWER(COALESCE(description,'')) LIKE ?
               OR LOWER(COALESCE(aliases,'')) LIKE ?
            ORDER BY card_count DESC
            LIMIT ?
            """,
            tuple(["%%%s%%" % needle] * 4) + (limit,),
        ).fetchall()
    else:
        rows = database.conn.execute(
            "SELECT slug, label, description, card_count, children FROM tags "
            "WHERE card_count > 20 ORDER BY card_count DESC LIMIT ?",
            (limit,),
        ).fetchall()

    # Tribal directions: 238 `typal-*` tags exist; only the substantial ones
    # are worth offering as a list.
    typal = database.conn.execute(
        "SELECT slug, label, description, card_count, children FROM tags "
        "WHERE slug LIKE 'typal-%' AND card_count >= 20 "
        "ORDER BY card_count DESC LIMIT 60"
    ).fetchall()

    return {
        "query": q,
        "presets": [{"label": ru, "slug": slug} for ru, slug in THEME_PRESETS],
        "keywords": [{"label": ru, "keyword": kw} for ru, kw in KEYWORD_PRESETS],
        "typal": [dict(r) for r in typal],
        "tags": [dict(r) for r in rows],
    }


# --------------------------------------------------------------------------- #
# Сканер: узнать карту по кадру с камеры
# --------------------------------------------------------------------------- #

class ScanIn(BaseModel):
    """Кадр из камеры. Картинка идёт как data:URL -- это то, что отдаёт
    canvas.toDataURL(), и одно поле проще, чем составная форма."""

    image: str
    limit: int = 5
    # Кадр уже обрезан по рамке до самой карты. Если нет -- значит прислали
    # карту целиком, и арт вырежем сами.
    cropped: bool = False
    # Искать карту в кадре самим: тогда угол и положение неважны. Выключается
    # только для отладки -- и тогда кадр считается уже обрезанным по карте.
    detect: bool = True


# Дальше какого расстояния ответ считается догадкой, а не ответом, и насколько
# он должен опережать следующего. 128 -- полное расхождение обоих хешей.
#
# Числа не на глаз: на полной базе (36 495 отпечатков) шестьдесят карт сняты
# тремя способами -- при хорошем свете, тускло и размыто, с пересветом и
# наклоном в 4 градуса. Верно узнались все 180 снимков; порог решает лишь,
# сколько из них засчитывается само, а сколько показывается как «похоже на».
# При 24 это 165 из 180, при 28 -- 174, дальше кривая выполаживается (175 и
# при 30, и при 34). Ошибок и принятых не-карт нет ни при одном пороге.
#
# Не-карту (стол, однотонный фон, кадр мимо карты) отсеивает не столько
# расстояние -- она попадает в 28-36, -- сколько зазор: у неё до следующей
# карты один-три бита, а у настоящей карты десятки.
SCAN_SURE = 28
SCAN_MARGIN = 6


def _scan_verdict(matches: list[dict[str, Any]]) -> tuple[Any, Any, bool]:
    """Ближайшая карта, ближайшая ДРУГАЯ карта и уверены ли мы.

    Отрыв считается до другой карты, а не до другой записи в базе. Когда
    отпечатаны все печати, у карты, переизданной десять раз, ближайшие соседи
    -- она же сама: арт у перепечаток общий, расстояние ноль. Правило «второй
    должен отстать на шесть битов» при этом не выполняется никогда, и уверенных
    ответов не остаётся вовсе -- при том, что карта узнана правильно.

    У базовых земель печатей за две сотни, так что без этого сканер на полной
    базе просто перестал бы засчитывать хоть что-нибудь.
    """
    if not matches:
        return None, None, False
    best = matches[0]
    rival = next((m for m in matches[1:]
                  if m.get("oracle_id") != best.get("oracle_id")), None)
    sure = bool(
        best["distance"] <= SCAN_SURE
        and (rival is None or rival["distance"] - best["distance"] >= SCAN_MARGIN)
    )
    return best, rival, sure


def _scan_many(data: bytes, limit: int = 40) -> list[dict[str, Any]]:
    """Все карты, которые видно на снимке, -- по арту.

    Кандидатов от детектора приходит больше, чем карт: вложенные контуры,
    пары соседних карт, случайные прямоугольники. Какой из них карта, решает
    отпечаток: у настоящей карты расстояние до своей записи в разы меньше, чем
    у чего угодно другого. Пересекающиеся кандидаты соревнуются между собой, и
    остаётся тот, кто ближе.
    """
    out: list[dict[str, Any]] = []
    for found in carddetect.find_cards(data, limit=limit):
        matches = artscan.identify(found["image"], limit=8, both_ways=True)
        best, _rival, sure = _scan_verdict(matches)
        if not sure:
            continue
        out.append({"match": best, "quad": found["corners"], "area": found["area"],
                    "centre": [sum(p[0] for p in found["corners"]) / 4.0,
                               sum(p[1] for p in found["corners"]) / 4.0]})

    # Две принятые карты не могут занимать одно место: если центр одной лежит
    # внутри другой, это один и тот же кусок снимка, и остаётся ближайший.
    out.sort(key=lambda r: r["match"]["distance"])
    kept: list[dict[str, Any]] = []
    for row in out:
        cx, cy = row["centre"]
        clash = False
        for k in kept:
            kx, ky = k["centre"]
            span = max(k["area"], row["area"]) ** 0.5
            if abs(cx - kx) < span * 0.5 and abs(cy - ky) < span * 0.5:
                clash = True
                break
        if not clash:
            kept.append(row)
    return kept


def _scan_card(card_id: str) -> dict[str, Any]:
    """Карта из базы по id печати -- чтобы показать её и знать цену."""
    row = db().conn.execute("SELECT * FROM cards WHERE id = ?", (card_id,)).fetchone()
    return CardDB.card_dict(row) if row else {}


class PileIn(BaseModel):
    """Снимок пачки: карты внахлёст, у каждой видно только имя."""

    image: str


@app.get("/api/card")
def card_by_name(name: str) -> Any:
    """Карта целиком по имени.

    Предложение -- замена, добавка, кусок комбо -- приходит одним именем и
    картинкой в 72 пикселя, по которой ничего не прочесть. Чтобы открыть такую
    карту в общем окне, нужна она целиком: текст, обе стороны, легальность,
    печати. Это и есть тот запрос.
    """
    card = db().by_name(name)
    if not card:
        raise HTTPException(status_code=404, detail="такой карты нет в базе")
    return {"card": card}


@app.get("/api/card/{card_id}")
def card_by_id(card_id: str) -> Any:
    """Карта целиком по id печати.

    Сканеру этого не нужно -- он показывает имя и картинку, -- но нужно окну
    карты, которое по ней открывается: там и печати, и цены, и обе стороны.
    """
    card = _scan_card(card_id)
    if not card:
        raise HTTPException(status_code=404, detail="такой печати нет в базе")
    return {"card": card}


@app.get("/api/scan/status")
def scan_status() -> dict[str, Any]:
    state = artscan.status()
    state["ready"] = artscan.index().ready
    # Разбор пачки -- другая задача и другой инструмент: там читается имя, а
    # не сравнивается арт. Поэтому и готовность у него своя.
    state["ocr"] = ocr.available()
    # Поиск карты в кадре -- отдельная возможность: без него сканер требует
    # класть карту в рамку, с ним -- нет.
    state["detect"] = carddetect.DEPS_OK
    return state


# Указатель на имена карт строится один раз: 59 тысяч имён и их трёхбуквенные
# куски -- это заметная работа, и делать её на каждый снимок незачем.
_PILE_FINDER: Any = None
_PILE_LOCK = threading.Lock()


def _pile_finder() -> Any:
    global _PILE_FINDER
    with _PILE_LOCK:
        if _PILE_FINDER is None:
            _PILE_FINDER = pile.NameFinder(db())
        return _PILE_FINDER


@app.post("/api/scan/pile")
def scan_pile(payload: PileIn) -> Any:
    """Какие карты видно на снимке пачки.

    Снимок нигде не сохраняется; наружу, как и везде в сканере, ничего не идёт.
    """
    raw = payload.image or ""
    if "," in raw[:64]:
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw, validate=False)
    except Exception:                                    # noqa: BLE001
        raise HTTPException(status_code=400, detail="снимок не разобрать")
    if not data:
        raise HTTPException(status_code=400, detail="пустой снимок")
    try:
        out = pile.read_pile(data, db(), ocr, _pile_finder())
    except Exception as exc:                             # noqa: BLE001
        raise HTTPException(status_code=400, detail="снимок не разобрать: %s" % exc)

    # Второй путь по тому же снимку: если карты разложены отдельно, а не
    # внахлёст, у них виден арт -- и тогда отпечаток надёжнее чтения имени.
    # Пути дополняют друг друга: у пачки виден только текст, у раскладки --
    # только арт, и каждый снимок бывает и тем и другим наполовину.
    by_name = {c["name"]: c for c in out.get("cards", [])}
    for row in _scan_many(data):
        match = row["match"]
        card = _scan_card(match["card_id"])
        name = card.get("name") or match.get("name")
        known = by_name.get(name)
        if known is not None:
            known["sure"] = True
            known["how"] = "оба"
            continue
        row_out = {
            "text": "", "name": name, "ru_name": card.get("ru_name"),
            "card_id": match["card_id"], "oracle_id": card.get("oracle_id"),
            "image_small": card.get("image_small"),
            "set_code": card.get("set_code"),
            "collector_number": card.get("collector_number"),
            "score": 1.0, "y": 0, "sure": True, "in_step": True,
            "how": "арт", "distance": match["distance"], "quad": row["quad"],
        }
        by_name[name] = row_out
        out.setdefault("cards", []).append(row_out)

    for card in out.get("cards", []):
        card.setdefault("how", "текст")
    return out


@app.post("/api/scan")
def scan(payload: ScanIn) -> Any:
    """Что за карта на кадре.

    Наружу ничего не уходит: сравнение идёт с отпечатками, собранными заранее
    (build_art.py). Снимок нигде не сохраняется -- он живёт до конца ответа.
    """
    raw = payload.image or ""
    if "," in raw[:64]:
        raw = raw.split(",", 1)[1]
    try:
        data = base64.b64decode(raw, validate=False)
    except Exception:                                    # noqa: BLE001
        raise HTTPException(status_code=400, detail="кадр не разобрать")
    if not data:
        raise HTTPException(status_code=400, detail="пустой кадр")

    if not artscan.index().ready:
        return {
            "ready": False,
            "matches": [],
            "detail": "база отпечатков не собрана — запустите build_art.py",
        }

    limit = max(1, min(payload.limit, 10))
    quad = None
    detected = False
    try:
        # Сначала пробуем найти карту в кадре и выпрямить её: тогда неважно,
        # под каким углом и где она лежит. Не нашлась (пёстрый фон, карта
        # выходит за кадр) -- смотрим кадр как есть, по рамке.
        found = carddetect.find_cards(data, limit=1) if payload.detect else []
        if found:
            detected = True
            quad = found[0]["corners"]
            # Просим с запасом: среди ближайших почти всегда есть перепечатки
            # той же карты, а для отрыва нужна ближайшая ДРУГАЯ.
            matches = artscan.identify(found[0]["image"], limit=limit + 6,
                                       both_ways=True)
        else:
            matches = artscan.identify(data, limit=limit + 6,
                                       already_cropped=payload.cropped)
    except Exception as exc:                             # noqa: BLE001
        raise HTTPException(status_code=400, detail="кадр не разобрать: %s" % exc)

    out = []
    for m in matches:
        card = _scan_card(m["card_id"])
        out.append({
            "card_id": m["card_id"],
            "oracle_id": card.get("oracle_id") or m.get("oracle_id"),
            "distance": m["distance"],
            "name": card.get("name") or m.get("name"),
            "ru_name": card.get("ru_name"),
            "set_code": card.get("set_code") or m.get("set_code"),
            "set_name": card.get("set_name"),
            "collector_number": card.get("collector_number"),
            "image_small": card.get("image_small"),
            "image_normal": card.get("image_normal"),
            "type_line": card.get("type_line"),
            "mana_cost": card.get("mana_cost"),
            "prices": card.get("prices"),
        })

    _best, _rival, sure = _scan_verdict(matches)
    # Сколько печатей с тем же артом попало в ответ: по картинке они
    # неразличимы, и выбирать печать -- дело человека, а не программы.
    same_art = sum(1 for m in matches
                   if matches and m.get("oracle_id") == matches[0].get("oracle_id"))
    return {"ready": True, "sure": sure, "detected": detected, "quad": quad,
            "printings": same_art, "matches": out}


@app.get("/api/formats")
def formats_list() -> dict[str, Any]:
    """Format keys present in the legalities blob."""
    row = db().conn.execute(
        "SELECT legalities FROM cards WHERE legalities IS NOT NULL AND legalities <> '{}' LIMIT 1"
    ).fetchone()
    try:
        keys = sorted(json.loads(row["legalities"]).keys()) if row else []
    except (TypeError, ValueError):
        keys = []
    return {"formats": keys}


@app.get("/api/printings/{oracle_id}")
def printings(oracle_id: str) -> dict[str, Any]:
    rows = db().printings(oracle_id)
    if not rows:
        raise HTTPException(status_code=404, detail="no printings for that oracle id")
    return {"count": len(rows), "printings": rows}


@app.post("/api/deck/import")
def deck_import(payload: DeckImportIn) -> dict[str, Any]:
    try:
        if payload.url:
            deck = import_from_url(payload.url)
        elif payload.text:
            deck = parse_text(payload.text, name=payload.name or "Pasted deck")
        else:
            raise HTTPException(status_code=400, detail="give either a url or text")
    except ImportError_ as exc:
        # These messages are written for the user to read directly.
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=502, content={"detail": "import failed: %s" % exc}
        )

    return {"deck": _enrich_deck(deck)}


def _enrich_deck(deck: DeckList) -> dict[str, Any]:
    """Attach the local card record to each entry, plus what you already own.

    The deck view is where you decide what to buy, so it needs the two facts
    that drive that decision: how many copies you are short, and what a copy
    costs. Without them the list is just names.
    """
    d = deck.as_dict()
    database = db()
    owned_by_name = {k.lower(): v for k, v in collection_store.load().items()}

    unknown: list[str] = []
    total_usd = 0.0
    missing_usd = 0.0

    for entry in d["entries"]:
        card = database.by_name(entry["name"])
        if card:
            entry["card"] = {
                "oracle_id": card.get("oracle_id"),
                "name": card.get("name"),
                "ru_name": card.get("ru_name"),
                "flavor_name": card.get("flavor_name"),
                "image_small": card.get("image_small"),
                "image_normal": card.get("image_normal"),
                "set_code": card.get("set_code"),
                "type_line": card.get("type_line"),
                "mana_cost": card.get("mana_cost"),
                "cmc": card.get("cmc"),
                "colors": card.get("colors"),
                "rarity": card.get("rarity"),
                "keywords": card.get("keywords"),
                "prices": card.get("prices"),
                "legalities": card.get("legalities"),
            }
        else:
            entry["card"] = None
            unknown.append(entry["name"])

        # Match the collection on the canonical name as well as the written one,
        # so "Удар Молнии" in the collection covers "Lightning Bolt" in the deck.
        owned = owned_by_name.get(entry["name"].lower(), 0)
        if not owned and card:
            for alias in (card.get("name"), card.get("ru_name")):
                if alias and alias.lower() in owned_by_name:
                    owned = owned_by_name[alias.lower()]
                    break
        entry["owned"] = owned
        entry["missing"] = max(0, int(entry["quantity"]) - owned)

        unit = 0.0
        try:
            unit = float(((card or {}).get("prices") or {}).get("usd") or 0)
        except (TypeError, ValueError):
            unit = 0.0
        entry["unit_usd"] = unit or None
        total_usd += unit * int(entry["quantity"])
        missing_usd += unit * entry["missing"]

    d["unknown_names"] = unknown
    d["total_usd"] = round(total_usd, 2)
    d["missing_usd"] = round(missing_usd, 2)
    d["missing_names"] = sum(1 for e in d["entries"] if e["missing"] > 0)
    d["missing_copies"] = sum(e["missing"] for e in d["entries"])
    return d


# --------------------------------------------------------------------------- #
# Deck builder
# --------------------------------------------------------------------------- #

_store: DeckStore | None = None


def store() -> DeckStore:
    global _store
    if _store is None:
        _store = DeckStore()
    return _store


class DeckNewIn(BaseModel):
    name: str
    format: str = "commander"


class DeckPatchIn(BaseModel):
    name: str | None = None
    format: str | None = None
    # Собрана ли колода физически: её карты заняты и другим колодам не
    # достанутся.
    assembled: bool | None = None
    # К какому замыслу относится эта колода: два turbofog -- одно семейство.
    family: str | None = None


class DeckCardIn(BaseModel):
    name: str
    quantity: int = 1
    section: str = "main"
    category: str = ""
    set_code: str | None = None
    collector_number: str | None = None


class DeckCardsIn(BaseModel):
    cards: list[DeckCardIn]


class DeckCardPatchIn(BaseModel):
    quantity: int | None = None
    section: str | None = None
    category: str | None = None
    note: str | None = None


class VersionIn(BaseModel):
    label: str = ""


class PriceRefreshIn(BaseModel):
    names: list[str] | None = None
    only_missing: bool = False


def _deck_payload(deck_id: str) -> dict[str, Any]:
    deck = store().get_deck(deck_id)
    deck = deckbuild.enrich(deck, db(), store(), collection_store.load())
    deck["versions"] = store().list_versions(deck_id)
    return deck


def _deck_error(exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/api/decks")
def decks_list() -> dict[str, Any]:
    return {"decks": store().list_decks(), "prices": store().price_stats()}


@app.post("/api/decks")
def decks_create(payload: DeckNewIn) -> Any:
    try:
        deck_id = store().create_deck(payload.name, payload.format)
    except DeckError as exc:
        return _deck_error(exc)
    return {"deck": _deck_payload(deck_id)}


@app.get("/api/decks/{deck_id}")
def decks_get(deck_id: str) -> Any:
    try:
        return {"deck": _deck_payload(deck_id)}
    except DeckError as exc:
        return _deck_error(exc)


@app.patch("/api/decks/{deck_id}")
def decks_patch(deck_id: str, payload: DeckPatchIn) -> Any:
    try:
        store().rename_deck(deck_id, payload.name, payload.format,
                            payload.assembled, payload.family)
        return {"deck": _deck_payload(deck_id)}
    except DeckError as exc:
        return _deck_error(exc)


@app.delete("/api/decks/{deck_id}")
def decks_delete(deck_id: str) -> Any:
    try:
        store().delete_deck(deck_id)
    except DeckError as exc:
        return _deck_error(exc)
    return {"decks": store().list_decks()}


@app.post("/api/decks/{deck_id}/cards")
def decks_add_cards(deck_id: str, payload: DeckCardsIn) -> Any:
    try:
        store().add_many(deck_id, [c.model_dump() for c in payload.cards])
        return {"deck": _deck_payload(deck_id)}
    except DeckError as exc:
        return _deck_error(exc)


@app.patch("/api/decks/{deck_id}/cards/{card_id}")
def decks_patch_card(deck_id: str, card_id: str, payload: DeckCardPatchIn) -> Any:
    try:
        store().update_card(deck_id, card_id, **payload.model_dump())
        return {"deck": _deck_payload(deck_id)}
    except DeckError as exc:
        return _deck_error(exc)


@app.delete("/api/decks/{deck_id}/cards/{card_id}")
def decks_remove_card(deck_id: str, card_id: str) -> Any:
    try:
        store().remove_card(deck_id, card_id)
        return {"deck": _deck_payload(deck_id)}
    except DeckError as exc:
        return _deck_error(exc)


@app.get("/api/decks/{deck_id}/formats")
def decks_formats(deck_id: str) -> Any:
    """Под какие форматы колода подходит, а под какие почти.

    Ничего не спрашивает наружу: легальность лежит в базе Scryfall.
    """
    try:
        deck = _deck_payload(deck_id)
    except DeckError as exc:
        return _deck_error(exc)
    out = formats.survey(deck)
    # Чем колода выигрывает -- вопрос к самой колоде, а не к формату, но
    # спрашивают его именно здесь: «пойдёт ли это в паупер» без ответа «чем
    # оно там будет выигрывать» ничего не значит.
    # Базу комбо спрашиваем, если она собрана: колода с дюжиной собранных
    # связок выигрывает ими, а не «боем», как показал бы подсчёт существ.
    out["win"] = formats.win_plan(db(), deck, _combo_db)
    return out


@app.get("/api/decks/{deck_id}/formats/{fmt}/replacements")
def decks_format_replacements(deck_id: str, fmt: str, name: str,
                              limit: int = 6, require: str = "") -> Any:
    """Чем заменить в этом формате карту, которая в него не проходит.

    require -- назначения через запятую: «покажи только те, что умеют imprint».
    limit -- сколько показать; шесть это начало разговора, а не его конец.
    """
    try:
        deck = _deck_payload(deck_id)
    except DeckError as exc:
        return _deck_error(exc)
    wanted = [x.strip() for x in (require or "").split(",") if x.strip()]
    return formats.replacements(db(), name, fmt, deck,
                                limit=max(1, min(120, limit)), require=wanted)


@app.get("/api/decks/{deck_id}/manabase")
def decks_manabase(deck_id: str, budget: float = 5.0, only_open: bool = False,
                   colors: str = "", fmt: str = "", limit: int = 24) -> Any:
    """Манабаза колоды: чего хватает, чего нет и чем добить.

    Считается по локальной базе: что земля производит, как входит и сколько
    стоит дешёвая её печать. Наружу не уходит ни одного запроса -- цена
    берётся долларовая, из тех же данных Scryfall.
    """
    try:
        deck = _deck_payload(deck_id)
    except DeckError as exc:
        return _deck_error(exc)
    fmt = (fmt or deck.get("format") or "modern").lower()
    return manabase.candidates(db(), deck, fmt, colors=colors,
                               budget=budget, only_open=only_open,
                               limit=max(1, min(60, limit)))


@app.get("/api/landsets")
def land_sets(fmt: str = "", budget: float | None = None, colors: str = "",
              order: str = "value", only_open: bool = False,
              limit: int = 40) -> Any:
    """Наборы земель: циклы, известные связки и комбо, где все куски -- земли.

    Вопрос «что купить по четыре штуки, чтобы потом собрать что угодно» -- про
    наборы, а не про карты, поэтому цена считается и за комплект, и за плейсет.
    """
    return landsets.catalogue(db(), (fmt or "").lower(), combo_db=_combo_db,
                              budget=budget, colors=colors, order=order,
                              only_open=only_open,
                              limit=max(1, min(80, limit)))


@app.get("/api/decks/{deck_id}/formats/{fmt}/adapt")
def decks_format_adapt(deck_id: str, fmt: str) -> Any:
    """План: что заменить, что срезать, что отложить ради этого формата.

    Только план. Колода не трогается -- ни эта, ни какая-либо ещё.
    """
    try:
        deck = _deck_payload(deck_id)
    except DeckError as exc:
        return _deck_error(exc)
    return formats.adapt(db(), deck, fmt, combo_db=_combo_db)


def _apply_adapt(deck_id: str, plan: dict[str, Any]) -> dict[str, Any]:
    """Применить план к уже заведённой колоде.

    Порядок внутри замены важен: сначала кладём новую карту, потом убираем
    старую. Сорвётся посередине -- колода останется с лишней картой, а не без
    нужной.
    """
    rows = store().get_deck(deck_id)["cards"]
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_name.setdefault((row.get("name") or "").lower(), []).append(row)

    swapped: list[dict[str, Any]] = []
    shelved: list[str] = []
    trimmed: list[str] = []

    for swap in plan.get("swaps") or []:
        targets = by_name.get((swap.get("name") or "").lower()) or []
        if not targets:
            continue
        quantity = sum(int(t.get("quantity") or 0) for t in targets)
        new_name = ((swap.get("to") or {}).get("name") or "").strip()
        if not new_name:
            continue
        store().add_many(deck_id, [{
            "name": new_name,
            "quantity": quantity,
            "section": targets[0].get("section") or "main",
            "category": targets[0].get("category") or "",
        }])
        for t in targets:
            store().remove_card(deck_id, t["id"])
        swapped.append({"from": swap.get("name"), "to": new_name,
                        "quantity": quantity})

    for row in plan.get("shelve") or []:
        for t in by_name.get((row.get("name") or "").lower()) or []:
            if t.get("section") == "maybe":
                continue
            store().update_card(deck_id, t["id"], section="maybe")
        shelved.append(row.get("name"))

    for row in plan.get("trims") or []:
        targets = [t for t in by_name.get((row.get("name") or "").lower()) or []
                   if t.get("section") in ("main", "commander")]
        if not targets:
            continue
        keep = max(1, int(row.get("keep") or 1))
        store().update_card(deck_id, targets[0]["id"], quantity=keep)
        for t in targets[1:]:
            store().remove_card(deck_id, t["id"])
        trimmed.append("%s -> %d" % (row.get("name"), keep))

    return {"swapped": swapped, "shelved": shelved, "trimmed": trimmed}


class VariantIn(BaseModel):
    """Имя для варианта. Пустое -- назову сам, по колоде и формату."""

    name: str = ""


@app.post("/api/decks/{deck_id}/formats/{fmt}/variant")
def decks_format_variant(deck_id: str, fmt: str, payload: VariantIn) -> Any:
    """Ответвить исполнение этой же колоды под другой формат.

    Одна колода -- один замысел, и её турбофог под модерн и под пионер это не
    две разные колоды, а два исполнения одного. Поэтому вариант заводится
    ответвлением: оба остаются в семействе и сравниваются в «Версиях», а
    исходная колода не меняется ни на карту.
    """
    try:
        deck = _deck_payload(deck_id)
        plan = formats.adapt(db(), deck, fmt, combo_db=_combo_db)
        title = (payload.name or "").strip() or "%s — %s" % (
            deck.get("name"), formats.FORMAT_TITLES.get(fmt, fmt))
        new_id = store().branch_deck(deck_id, title)
        store().rename_deck(new_id, None, fmt)
        applied = _apply_adapt(new_id, plan)
    except DeckError as exc:
        return _deck_error(exc)
    return {
        "deck": _deck_payload(new_id),
        "decks": store().list_decks(),
        "plan": plan,
        "applied": applied,
        "check": formats.check(_deck_payload(new_id), fmt),
    }


@app.get("/api/decks/{deck_id}/formats/{fmt}/theme")
def decks_format_theme(deck_id: str, fmt: str) -> Any:
    """О чём колода и что к ней добавить, не выходя из пула формата."""
    try:
        deck = _deck_payload(deck_id)
    except DeckError as exc:
        return _deck_error(exc)
    return formats.theme(db(), deck, fmt)


@app.post("/api/decks/{deck_id}/versions")
def decks_save_version(deck_id: str, payload: VersionIn) -> Any:
    try:
        store().save_version(deck_id, payload.label)
        return {"deck": _deck_payload(deck_id)}
    except DeckError as exc:
        return _deck_error(exc)


@app.post("/api/decks/{deck_id}/versions/{version_id}/restore")
def decks_restore_version(deck_id: str, version_id: str) -> Any:
    try:
        store().restore_version(deck_id, version_id)
        return {"deck": _deck_payload(deck_id)}
    except DeckError as exc:
        return _deck_error(exc)


@app.delete("/api/decks/{deck_id}/versions/{version_id}")
def decks_delete_version(deck_id: str, version_id: str) -> Any:
    try:
        store().delete_version(deck_id, version_id)
        return {"deck": _deck_payload(deck_id)}
    except DeckError as exc:
        return _deck_error(exc)


@app.post("/api/decks/{deck_id}/prices")
def decks_refresh_prices(deck_id: str, payload: PriceRefreshIn) -> Any:
    """Pull topdeck prices for this deck. On demand only -- 1.5s per request."""
    try:
        deck = store().get_deck(deck_id)
    except DeckError as exc:
        return _deck_error(exc)

    if payload.names:
        names = payload.names
    else:
        names = [c["name"] for c in deck["cards"]]
        if payload.only_missing:
            cached = store().get_prices(names)
            names = [n for n in names if normalize_name(n) not in cached]

    report = deckbuild.refresh_prices(names, store(), db(), TopdeckClient())
    result = {"report": report}
    try:
        result["deck"] = _deck_payload(deck_id)
    except DeckError:
        pass
    return result


class PriceNamesIn(BaseModel):
    """Price arbitrary cards, not a whole deck."""

    names: list[str]
    only_missing: bool = True


# A hard ceiling, because each name costs topdeck a request. Suggestions are
# 250 cards; pricing all of them would be minutes of traffic and rude.
PRICE_NAMES_LIMIT = 40


@app.post("/api/prices")
def prices_for_names(payload: PriceNamesIn) -> dict[str, Any]:
    """Ask topdeck for these specific cards. On demand only, 1.5s per request."""
    names = [n.strip() for n in payload.names if n and n.strip()]
    if not names:
        raise HTTPException(status_code=400, detail="не указано ни одной карты")

    if payload.only_missing:
        cached = store().get_prices(names)
        names = [n for n in names if normalize_name(n) not in cached]
    if not names:
        return {"report": {"updated": 0, "total": 0, "not_found": [],
                           "skipped_cached": True},
                "prices": store().get_prices([n.strip() for n in payload.names])}

    if len(names) > PRICE_NAMES_LIMIT:
        raise HTTPException(
            status_code=400,
            detail="за раз можно узнать цены не более чем для %d карт — "
                   "отметьте меньше" % PRICE_NAMES_LIMIT,
        )

    report = deckbuild.refresh_prices(names, store(), db(), TopdeckClient())
    return {"report": report, "prices": store().get_prices(names)}


# ------------------------------------------------------------------ combos

_combo_db = combo_store.ComboDB()
_combo_lock = threading.Lock()


def _combo_card_info(names: list[str], fmt: str = "") -> dict[str, Any]:
    """Local knowledge about the cards a combo names: art, USD, owned, roubles.

    И легальность в формате колоды, если он известен: комбо на четыре карты, из
    которых одна забанена, -- это не подсказка, а ловушка, и узнавать об этом
    надо до похода в магазин, а не после.
    """
    cards = db()
    prices = store().get_prices(names)
    collection = collection_store.load()
    have = (
        {normalize_name(k): int(v or 0) for k, v in collection.items()}
        if isinstance(collection, dict) else {}
    )
    out: dict[str, Any] = {}
    for name in names:
        key = normalize_name(name)
        card = cards.by_name(name)
        cached = prices.get(key)
        out[name] = {
            "image_small": (card or {}).get("image_small"),
            "image_normal": (card or {}).get("image_normal"),
            "ru_name": (card or {}).get("ru_name"),
            "type_line": (card or {}).get("type_line"),
            "mana_cost": (card or {}).get("mana_cost"),
            "known": bool(card),
            "legal": formats.legality(card, fmt) if fmt else "",
            "owned": have.get(key, 0),
            "rub": (
                {"min": cached.get("rub_min"), "median": cached.get("rub_median")}
                if cached else None
            ),
        }
    return out


@app.get("/api/combos/status")
def combos_status() -> dict[str, Any]:
    return _combo_db.status()


@app.post("/api/combos/build")
def combos_build() -> dict[str, Any]:
    """Download Commander Spellbook's bulk file and rebuild the local database.

    27 MB and about a minute. Deliberate: nothing downloads on its own.
    """
    if not _combo_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="сборка базы комбо уже идёт")
    try:
        report = combo_store.build()
    except combo_store.ComboError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        _combo_lock.release()
    return {"report": report, "status": _combo_db.status()}


@app.get("/api/combos/card")
def combos_for_card(name: str, commander_only: bool = True,
                    limit: int = 40, include_unplayed: bool = False,
                    fmt: str = "") -> dict[str, Any]:
    """Combos this card takes part in."""
    if not name.strip():
        raise HTTPException(status_code=400, detail="не указана карта")
    card = db().by_name(name)
    asked = (card or {}).get("name") or name
    try:
        found = _combo_db.for_card(
            asked, limit=limit, commander_only=commander_only,
            min_popularity=0 if include_unplayed else None,
        )
    except combo_store.ComboError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    every = sorted({
        n for c in found
        for n in list(c.get("cards", [])) + list(c.get("one_of", []))
    })
    fmt = (fmt or "").lower()
    return {
        "card": asked,
        "combos": found,
        "cards": _combo_card_info(every, fmt),
        "format": fmt,
        "format_title": formats.FORMAT_TITLES.get(fmt, fmt),
    }


@app.get("/api/combos/deck")
def combos_for_deck(deck_id: str, missing: int = 1,
                    commander_only: bool = True,
                    include_unplayed: bool = False,
                    fmt: str = "") -> dict[str, Any]:
    """Combos the deck already has, and those it is a card or two short of."""
    try:
        deck = store().get_deck(deck_id)
    except DeckError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    names = [c["name"] for c in deck.get("cards", [])]
    try:
        found = _combo_db.for_deck(
            names, max_missing=max(0, min(2, missing)),
            commander_only=commander_only,
            min_popularity=0 if include_unplayed else None,
        )
    except combo_store.ComboError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    # The interchangeable cards need prices too: the point of listing them is
    # that you buy whichever is cheapest.
    every = sorted({
        n for group in ("complete", "near", "needs_template")
        for c in found.get(group, [])
        for n in list(c.get("cards", [])) + list(c.get("one_of", []))
    })
    # Формат берётся из самой колоды, если не спросили про другой: комбо
    # смотрят, сидя в колоде, и «легально ли это» значит «легально ли у меня».
    fmt = (fmt or deck.get("format") or "").lower()
    found["cards"] = _combo_card_info(every, fmt)
    found["deck_id"] = deck_id
    found["deck_name"] = deck.get("name")
    found["format"] = fmt
    found["format_title"] = formats.FORMAT_TITLES.get(fmt, fmt)
    return found


class GoldfishIn(BaseModel):
    games: int = 1000
    hand_size: int = 7
    turns: int = 5


@app.post("/api/decks/{deck_id}/goldfish")
def decks_goldfish(deck_id: str, payload: GoldfishIn) -> Any:
    """Simulate opening hands and the first few turns."""
    try:
        deck = _deck_payload(deck_id)
    except DeckError as exc:
        return _deck_error(exc)
    result = goldfish.simulate(
        deck, games=payload.games, hand_size=payload.hand_size, turns=payload.turns
    )
    if "error" in result:
        return JSONResponse(status_code=422, content={"detail": result["error"]})
    return {"goldfish": result}


@app.post("/api/decks/{deck_id}/deal")
def decks_deal(deck_id: str, payload: GoldfishIn) -> Any:
    """One shuffled hand, plus the rest of the library in order."""
    try:
        deck = _deck_payload(deck_id)
    except DeckError as exc:
        return _deck_error(exc)
    result = goldfish.deal(deck, hand_size=payload.hand_size)
    if "error" in result:
        return JSONResponse(status_code=422, content={"detail": result["error"]})
    return result


@app.post("/api/decks/{deck_id}/autocategory")
def decks_autocategory(deck_id: str) -> Any:
    """Fill empty categories from the functional tags."""
    try:
        deck = _deck_payload(deck_id)
        assigned = deckbuild.auto_categorise(deck, db(), store())
        return {"deck": _deck_payload(deck_id), "assigned": assigned}
    except DeckError as exc:
        return _deck_error(exc)


@app.post("/api/decks/{deck_id}/import")
def decks_import(deck_id: str, payload: DeckImportIn) -> Any:
    """Pour an imported decklist into an existing deck."""
    try:
        if payload.url:
            imported = import_from_url(payload.url)
        elif payload.text:
            imported = parse_text(payload.text)
        else:
            raise HTTPException(status_code=400, detail="give either a url or text")
    except ImportError_ as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    try:
        store().add_many(
            deck_id,
            [
                {"name": e.name, "quantity": e.quantity, "section": e.section,
                 "set_code": e.set_code, "collector_number": e.collector_number}
                for e in imported.entries
            ],
        )
        return {"deck": _deck_payload(deck_id), "added": len(imported.entries)}
    except DeckError as exc:
        return _deck_error(exc)


# --------------------------------------------------------------------------- #
# Favourites
# --------------------------------------------------------------------------- #

class FolderIn(BaseModel):
    name: str


class FavCardIn(BaseModel):
    name: str
    quantity: int = 1
    set_code: str | None = None
    collector_number: str | None = None
    note: str = ""
    image: str | None = None


class FavCardPatch(BaseModel):
    quantity: int | None = None
    note: str | None = None


class MoveCardIn(BaseModel):
    target_folder_id: str


def _decorate(doc: dict[str, Any]) -> dict[str, Any]:
    """Attach artwork and a reference price to every saved card.

    A shopping list of bare names is not much use -- you want to see what you
    put aside and roughly what it costs.
    """
    database = db()
    out = json.loads(json.dumps(doc))  # cheap deep copy; the doc is tiny
    for folder in out["folders"]:
        total_usd = 0.0
        for card in folder["cards"]:
            printing = None
            if card.get("set_code") and card.get("collector_number"):
                printing = database.by_set_number(card["set_code"], card["collector_number"])
            if printing is None:
                printing = database.by_name(card["name"])
            if printing:
                card["resolved"] = {
                    "oracle_id": printing.get("oracle_id"),
                    "set_code": printing.get("set_code"),
                    "set_name": printing.get("set_name"),
                    "collector_number": printing.get("collector_number"),
                    "image_small": card.get("image") or printing.get("image_small"),
                    "image_normal": printing.get("image_normal"),
                    "ru_name": printing.get("ru_name"),
                    "type_line": printing.get("type_line"),
                    "rarity": printing.get("rarity"),
                    "prices": printing.get("prices"),
                }
                usd = (printing.get("prices") or {}).get("usd")
                try:
                    total_usd += float(usd) * int(card.get("quantity", 1))
                except (TypeError, ValueError):
                    pass
            else:
                card["resolved"] = None
        folder["total_usd"] = round(total_usd, 2)
        folder["copies"] = sum(int(c.get("quantity", 1)) for c in folder["cards"])
    return out


def _fav_response(doc: dict[str, Any]) -> dict[str, Any]:
    return {"favourites": _decorate(doc), "summary": favourites.summary(doc)}


@app.get("/api/favourites")
def favourites_get() -> dict[str, Any]:
    return _fav_response(favourites.load())


@app.post("/api/favourites/folders")
def favourites_create_folder(payload: FolderIn) -> Any:
    try:
        return _fav_response(favourites.create_folder(payload.name))
    except favourites.FavouritesError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.patch("/api/favourites/folders/{folder_id}")
def favourites_rename_folder(folder_id: str, payload: FolderIn) -> Any:
    try:
        return _fav_response(favourites.rename_folder(folder_id, payload.name))
    except favourites.FavouritesError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.delete("/api/favourites/folders/{folder_id}")
def favourites_delete_folder(folder_id: str) -> Any:
    try:
        return _fav_response(favourites.delete_folder(folder_id))
    except favourites.FavouritesError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.post("/api/favourites/folders/{folder_id}/cards")
def favourites_add_card(folder_id: str, payload: FavCardIn) -> Any:
    try:
        return _fav_response(
            favourites.add_card(
                folder_id,
                name=payload.name,
                quantity=payload.quantity,
                set_code=payload.set_code,
                collector_number=payload.collector_number,
                note=payload.note,
                image=payload.image,
            )
        )
    except favourites.FavouritesError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


class BulkAddIn(BaseModel):
    """Either folder_id (existing) or folder_name (created if new)."""

    cards: list[FavCardIn]
    folder_id: str | None = None
    folder_name: str | None = None


@app.post("/api/favourites/cards/bulk")
def favourites_add_many(payload: BulkAddIn) -> Any:
    try:
        doc, report = favourites.add_many(
            [c.model_dump() for c in payload.cards],
            folder_id=payload.folder_id,
            folder_name=payload.folder_name,
        )
    except favourites.FavouritesError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    result = _fav_response(doc)
    result["report"] = report
    return result


@app.patch("/api/favourites/folders/{folder_id}/cards/{card_id}")
def favourites_update_card(folder_id: str, card_id: str, payload: FavCardPatch) -> Any:
    try:
        return _fav_response(
            favourites.update_card(
                folder_id, card_id, quantity=payload.quantity, note=payload.note
            )
        )
    except favourites.FavouritesError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.delete("/api/favourites/folders/{folder_id}/cards/{card_id}")
def favourites_remove_card(folder_id: str, card_id: str) -> Any:
    try:
        return _fav_response(favourites.remove_card(folder_id, card_id))
    except favourites.FavouritesError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.post("/api/favourites/folders/{folder_id}/cards/{card_id}/move")
def favourites_move_card(folder_id: str, card_id: str, payload: MoveCardIn) -> Any:
    try:
        return _fav_response(
            favourites.move_card(folder_id, card_id, payload.target_folder_id)
        )
    except favourites.FavouritesError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.get("/api/favourites/folders/{folder_id}/wants")
def favourites_folder_wants(folder_id: str) -> Any:
    try:
        return {"wants": favourites.folder_as_wants(folder_id)}
    except favourites.FavouritesError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})


class RestoreIn(BaseModel):
    snapshot_id: int


@app.get("/api/backups")
def backups_list() -> dict[str, Any]:
    """Every snapshot we hold, newest first.

    Snapshots are written before each change, so an accidental deletion is
    always one click from being undone.
    """
    return {
        "favourites": favourites.backups(),
        "collection": collection_store.backups(),
    }


@app.post("/api/backups/favourites/restore")
def backups_restore_favourites(payload: RestoreIn) -> Any:
    try:
        doc = favourites.restore(payload.snapshot_id)
    except favourites.FavouritesError as exc:
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    result = _fav_response(doc)
    result["backups"] = favourites.backups()
    return result


@app.post("/api/backups/collection/restore")
def backups_restore_collection(payload: RestoreIn) -> Any:
    try:
        restored = collection_store.restore(payload.snapshot_id)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(status_code=422, content={"detail": str(exc)})
    return {
        "collection": restored,
        "backups": collection_store.backups(),
    }


@app.get("/api/collection")
def get_collection() -> dict[str, Any]:
    return {
        "collection": collection_store.load(),
        "backups": collection_store.backups(),
    }


@app.post("/api/collection")
def set_collection(payload: CollectionIn) -> dict[str, Any]:
    """Collection is a pasted decklist-style text: "4 Lightning Bolt" per line."""
    deck = parse_text(payload.text, name="Collection")
    entries: dict[str, int] = {}
    for e in deck.entries:
        entries[e.name] = entries.get(e.name, 0) + e.quantity
    stored = collection_store.replace(entries)
    return {
        "stored": len(stored),
        "copies": sum(stored.values()),
        "warnings": deck.warnings,
        "backups": collection_store.backups(),
    }


@app.post("/api/collection/add")
def add_to_collection(payload: CollectionAddIn) -> dict[str, Any]:
    """Прибавить копии к коллекции. Так в неё попадает всё, что насканировали."""
    entries: dict[str, int] = {}
    for card in payload.cards:
        name = (card.name or "").strip()
        if name:
            entries[name] = entries.get(name, 0) + max(0, int(card.quantity or 0))
    result = collection_store.add(entries)
    return {
        "added": result["added"],
        "stored": len(result["collection"]),
        "copies": sum(result["collection"].values()),
        "backups": collection_store.backups(),
    }


class BranchIn(BaseModel):
    """Ответвить новое исполнение -- из колоды или из её сохранённой версии."""

    name: str = ""
    version_id: str | None = None


class ModuleIn(BaseModel):
    """Готовый кусок колоды: карты, которые имеют смысл только вместе."""

    name: str
    note: str = ""
    cards: list[DeckCardIn] = Field(default_factory=list)


def _family_prices(deck_ids: list[str]) -> dict[str, Any]:
    names: set[str] = set()
    for deck_id in deck_ids:
        for card in store().get_deck(deck_id).get("cards", []):
            if card.get("name"):
                names.add(card["name"])
    return store().get_prices(sorted(names))


@app.get("/api/families")
def families_list() -> dict[str, Any]:
    """Семейства колод: какие замыслы есть и сколько у каждого исполнений."""
    return {"families": family_store.families(store())}


@app.get("/api/family")
def family_report(name: str) -> Any:
    """Разбор одного семейства: матрица, ядро, сменные части, сайдборд."""
    found = next((f for f in family_store.families(store()) if f["name"] == name), None)
    if found is None:
        raise HTTPException(status_code=404, detail="такого семейства нет")
    prices = _family_prices([d["id"] for d in found["decks"]])
    return family_store.report(store(), name, db(), prices)


@app.post("/api/family/compare")
def family_compare(payload: DeckIdsIn) -> Any:
    """Сравнить произвольные колоды между собой, не заводя семейства."""
    ids = [i for i in payload.deck_ids if i]
    if len(ids) < 2:
        raise HTTPException(status_code=400, detail="нужно хотя бы две колоды")
    return family_store.compare(store(), ids, db(), _family_prices(ids))


class GroupIn(BaseModel):
    """Группа исполнений: либо семейство по имени, либо список колод.

    Семейство -- обычный случай («мой турбофог»), список -- когда сравнивают
    то, что в семейство ещё не сведено.
    """

    deck_ids: list[str] = Field(default_factory=list)
    family: str = ""
    mode: str = "together"
    basics: bool = False
    hand_size: int = 7
    games: int = 1000
    turns: int = 5
    seed: int | None = None


def _group_ids(payload: GroupIn) -> list[str]:
    ids = [i for i in payload.deck_ids if i]
    if payload.family:
        found = next((f for f in family_store.families(store())
                      if f["name"] == payload.family), None)
        if found is None:
            raise HTTPException(status_code=404, detail="такого семейства нет")
        ids = [d["id"] for d in found["decks"]]
    if not ids:
        raise HTTPException(status_code=400, detail="не выбрано ни одной колоды")
    return ids


def _group_decks(ids: list[str]) -> list[dict[str, Any]]:
    try:
        return [_deck_payload(deck_id) for deck_id in ids]
    except DeckError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/family/specs")
def family_specs(payload: GroupIn) -> Any:
    """Спеки исполнений рядом: земли, кривая, средняя мана, цена, чего не хватает."""
    ids = _group_ids(payload)
    return family_store.specs(_group_decks(ids))


@app.post("/api/family/hands")
def family_hands(payload: GroupIn) -> Any:
    """По стартовой руке каждому исполнению -- одной раздачей.

    Сравнивать руки по очереди бессмысленно: разница между двадцатью четырьмя
    землями и двадцатью шестью видна только тогда, когда обе руки лежат рядом.
    """
    ids = _group_ids(payload)
    size = max(1, min(10, payload.hand_size))
    hands: list[dict[str, Any]] = []
    for deck in _group_decks(ids):
        dealt = goldfish.deal(deck, hand_size=size)
        if "error" in dealt:
            hands.append({"deck_id": deck.get("id"), "name": deck.get("name"),
                          "format": deck.get("format"), "error": dealt["error"]})
            continue
        hand = dealt["hand"]
        hands.append({
            "deck_id": deck.get("id"),
            "name": deck.get("name"),
            "format": deck.get("format"),
            "hand": hand,
            "lands": sum(1 for c in hand if c.get("is_land")),
            "avg_mv": round(
                sum(float(c.get("cmc") or 0) for c in hand if not c.get("is_land"))
                / max(1, sum(1 for c in hand if not c.get("is_land"))), 2),
            "library_size": dealt["library_size"],
        })
    return {"hand_size": size, "hands": hands}


@app.post("/api/family/simulate")
def family_simulate(payload: GroupIn) -> Any:
    """Одна и та же прогонка для каждого исполнения -- цифры рядом."""
    ids = _group_ids(payload)
    runs: list[dict[str, Any]] = []
    for deck in _group_decks(ids):
        result = goldfish.simulate(
            deck, games=max(50, min(5000, payload.games)),
            hand_size=max(1, min(10, payload.hand_size)),
            turns=max(1, min(10, payload.turns)))
        runs.append({
            "deck_id": deck.get("id"),
            "name": deck.get("name"),
            "format": deck.get("format"),
            "error": result.get("error", ""),
            "goldfish": None if "error" in result else result,
        })
    return {"runs": runs}


@app.post("/api/family/shopping")
def family_shopping(payload: GroupIn) -> Any:
    """Что докупить на всю группу -- разом и без двойного счёта."""
    ids = _group_ids(payload)
    decks = _group_decks(ids)
    mode = payload.mode if payload.mode in ("together", "byturn") else "together"
    return family_store.shopping(
        decks, collection_store.load(), _family_prices(ids), mode,
        basics=bool(payload.basics))


@app.post("/api/decks/{deck_id}/branch")
def deck_branch(deck_id: str, payload: BranchIn) -> Any:
    """Новое исполнение того же замысла -- поперёк истории, а не вдоль."""
    try:
        new_id = store().branch_deck(deck_id, payload.name, payload.version_id)
    except DeckError as exc:
        return _deck_error(exc)
    return {"deck": _deck_payload(new_id), "decks": store().list_decks()}


@app.get("/api/modules")
def modules_list() -> dict[str, Any]:
    return {"modules": store().list_modules()}


@app.post("/api/modules")
def modules_create(payload: ModuleIn) -> Any:
    try:
        module_id = store().create_module(
            payload.name, [c.model_dump() for c in payload.cards], payload.note)
    except DeckError as exc:
        return _deck_error(exc)
    return {"module_id": module_id, "modules": store().list_modules()}


@app.delete("/api/modules/{module_id}")
def modules_delete(module_id: str) -> dict[str, Any]:
    store().delete_module(module_id)
    return {"modules": store().list_modules()}


@app.post("/api/decks/{deck_id}/modules/{module_id}")
def modules_apply(deck_id: str, module_id: str) -> Any:
    """Положить модуль в колоду целиком."""
    try:
        added = store().apply_module(deck_id, module_id)
    except DeckError as exc:
        return _deck_error(exc)
    return {"added": added, "deck": _deck_payload(deck_id)}


@app.get("/api/holdings")
def holdings_report() -> dict[str, Any]:
    """Что есть, что занято собранными колодами и что свободно.

    Считается на лету из коллекции и колод: отдельного склада в базе нет, и
    заводить его значило бы держать две правды об одном и том же.
    """
    collection = collection_store.load()
    names = set(collection)
    for deck in store().list_decks():
        for card in store().get_deck(deck["id"]).get("cards", []):
            names.add(card.get("name") or "")
    prices = store().get_prices([n for n in names if n])
    out = holdings.report(store(), collection, db(), prices)
    # Заодно запоминаем сегодняшнюю оценку: строка в день, за сегодня
    # переписывается. Так у коллекции появляется история, а не одно «сейчас».
    total = out["totals"]
    collection_store.record_value(total["cards"], total["copies"],
                                  total["usd"], total["rub"],
                                  total["rub_known"])
    out["history"] = collection_store.value_history()
    return out


@app.get("/api/collection/value")
def collection_value() -> dict[str, Any]:
    """Как менялась оценка коллекции -- по дням."""
    return {"history": collection_store.value_history()}


@app.get("/api/collection/export")
def collection_export(kind: str = "text") -> Any:
    """Коллекция целиком -- одним куском, чтобы унести куда угодно.

    `text` -- тот же формат, которым коллекция вводится, то есть список можно
    вернуть обратно без правки. `csv` -- для таблицы: туда идут и цены, и то,
    что занято колодами.
    """
    collection = collection_store.load()
    names = list(collection)
    prices = store().get_prices(names)
    out = holdings.report(store(), collection, db(), prices)
    mine = [c for c in out["cards"] if c["owned"] > 0]
    mine.sort(key=lambda c: c["name"].lower())

    if kind == "csv":
        rows = ["имя,русское имя,есть,занято,свободно,сет,номер,"
                "цена ₽,цена $,стоимость ₽,стоимость $"]
        for c in mine:
            rows.append(",".join(_csv_cell(v) for v in (
                c["name"], c.get("ru_name") or "", c["owned"], c["committed"],
                c["free"], (c.get("set_code") or "").upper(),
                c.get("collector_number") or "", c.get("price") or "",
                c.get("usd") or "", c.get("rub_total") or "",
                c.get("usd_total") or "")))
        body = "\n".join(rows)
    else:
        body = "\n".join("%d %s" % (c["owned"], c["name"]) for c in mine)

    return {"kind": kind, "cards": len(mine),
            "copies": sum(c["owned"] for c in mine),
            "totals": out["totals"], "text": body}


def _csv_cell(value: Any) -> str:
    """Ячейка CSV: запятая и кавычки внутри имени не должны рвать столбцы."""
    text = "" if value is None else str(value)
    if any(ch in text for ch in (",", '"', "\n")):
        return '"%s"' % text.replace('"', '""')
    return text


@app.get("/api/orders")
def purchase_orders() -> dict[str, Any]:
    """Cards paid/ordered but not yet received into the collection."""
    return orders.state()


@app.post("/api/orders")
def create_purchase_order(payload: PurchaseOrderIn) -> dict[str, Any]:
    try:
        order_id = orders.create(
            payload.seller_name,
            payload.seller_kind,
            [item.model_dump() for item in payload.items],
        )
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return dict(orders.state(), created_id=order_id)


@app.get("/api/orders/purchases")
def order_purchases(name: str) -> dict[str, Any]:
    """Every time this card was actually bought, and for how much.

    Not the same question as the price cache: that says what topdeck is asking
    now, this says what was paid and to whom.
    """
    if not name.strip():
        raise HTTPException(status_code=400, detail="не указана карта")
    card = db().by_name(name)
    asked = (card or {}).get("name") or name
    rows = orders.purchases_of(asked)
    return {
        "name": asked,
        "purchases": rows,
        "copies": sum(int(r["quantity"] or 0) for r in rows),
        "spent": sum(int(r["subtotal"] or 0) for r in rows),
    }


@app.post("/api/orders/{order_id}/remove")
def remove_purchase_order(order_id: str) -> dict[str, Any]:
    if not orders.remove(order_id):
        raise HTTPException(status_code=404, detail="такого активного заказа нет")
    return orders.state()


@app.post("/api/orders/{order_id}/receive")
def receive_purchase_order(order_id: str) -> dict[str, Any]:
    if not orders.receive(order_id):
        raise HTTPException(status_code=404, detail="такого активного заказа нет")
    return dict(orders.state(), collection=collection_store.summary())


@app.get("/api/undo/status")
def undo_status() -> dict[str, Any]:
    """What can be taken back right now."""
    return {"available": undo_store.available()}


@app.post("/api/undo")
def undo_last(payload: UndoIn) -> dict[str, Any]:
    """Put back the state from before the last change of this kind."""
    try:
        result = undo_store.undo(payload.kind)
    except undo_store.UndoError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Whatever was undone, the interface needs the fresh state of it, so it
    # can redraw without a second round of requests.
    result["favourites"] = _fav_response(favourites.load())
    result["collection"] = collection_store.summary()
    result["orders"] = orders.state()
    return result


@app.get("/api/whatsnew")
def what_is_new(seen: str = "") -> dict[str, Any]:
    """Notes for versions newer than the one already shown to this browser."""
    version = app.version
    return {
        "version": version,
        "seen": seen or None,
        "fresh": whatsnew.is_newer(version, seen or None),
        "entries": whatsnew.since(seen or None),
    }


@app.post("/api/offers")
def offers(payload: OffersIn) -> dict[str, Any]:
    """Raw topdeck offers for specific cards, with our parse alongside the
    seller's original line."""
    names = [n for n in payload.names if n.strip()]
    if not names:
        raise HTTPException(status_code=400, detail="no card names given")
    client = TopdeckClient()
    try:
        found = client.search(names)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=502, content={"detail": "topdeck request failed: %s" % exc}
        )

    index = sets()
    matcher = offermatch.OfferMatcher(db())

    out = []
    rejected: dict[str, int] = {}
    for o in found:
        parsed = parse_line(o.line, index, o.eng_name, o.rus_name, [o.name])
        row = o.as_dict()
        row["parsed"] = parsed.as_dict()

        # topdeck labels every hit with the name we searched for, so the only
        # evidence of WHICH card a listing sells is the seller's own line.
        # Asking for "Burgeoning" returns "Urban Burgeoning" at a tenth of the
        # price, labelled "Burgeoning".
        want = next(
            (n for n in names if offermatch.normalize_name(n) ==
             offermatch.normalize_name(o.eng_name or o.name)),
            names[0],
        )
        verdict = matcher.classify(want, o.line)
        row["verdict"] = verdict.get("verdict")
        row["verdict_reason"] = verdict.get("reason")
        row["actual_card"] = verdict.get("actual")
        row["want"] = want

        # topdeck also misreads prices: it took "#235/281" for 235 roubles on a
        # card priced at 1300. We cannot know which number is right, so such an
        # offer is flagged and never presented as the cheapest.
        price = offermatch.price_check(o.cost, o.line)
        row["price_disputed"] = price["disputed"]
        row["price_in_line"] = price.get("written")
        row["price_reason"] = price.get("reason")
        if verdict["verdict"] == offermatch.OTHER:
            label = verdict.get("actual") or "другая карта"
            rejected[label] = rejected.get(label, 0) + 1
        out.append(row)

    return {
        "count": len(out),
        "matched": sum(1 for r in out if r["verdict"] == offermatch.MATCH),
        "price_disputed": sum(1 for r in out if r["price_disputed"]),
        "other_cards": rejected,
        "offers": out,
    }


# A hunt costs a 1.5s request per batch, so the offers it fetched are kept in
# memory. Changing your mind about a card then rebuilds the plan instantly and
# without touching topdeck again. Only the few most recent hunts are held.
_HUNT_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_HUNT_CACHE_LOCK = threading.Lock()
HUNT_CACHE_KEEP = 4


def _seller_fee(value: Any) -> int:
    """A fee out of range is a typo, not an instruction."""
    try:
        return max(0, min(int(value), 5000))
    except (TypeError, ValueError):
        return SELLER_FEE_DEFAULT


def _remember_hunt(wants: list[Want], candidates: list[Any], strategy: str,
                   seller_fee: int = SELLER_FEE_DEFAULT) -> str:
    hunt_id = uuid.uuid4().hex[:12]
    with _HUNT_CACHE_LOCK:
        _HUNT_CACHE[hunt_id] = {
            "wants": wants,
            "candidates": candidates,
            "strategy": strategy,
            "seller_fee": seller_fee,
        }
        while len(_HUNT_CACHE) > HUNT_CACHE_KEEP:
            _HUNT_CACHE.popitem(last=False)
    return hunt_id


def _plan_sellers(held: dict[str, Any]) -> set[str]:
    """Sellers the current plan already involves, by the planner's own key."""
    plan = build_plan(
        held["wants"], held["candidates"], prefer=held.get("strategy") or "sellers",
        pins=held.get("pins") or {}, prefer_seller=held.get("prefer_seller") or None,
        seller_fee=_seller_fee(held.get("seller_fee", SELLER_FEE_DEFAULT)),
    )
    keys = set()
    for lot in plan.get("lots", []):
        for item in lot.get("items", []):
            offer = item.get("offer") or {}
            seller = offer.get("seller") or {}
            keys.add(
                "shop:%s" % seller.get("name")
                if seller.get("kind") == "shop"
                else "user:%s" % (seller.get("id") or seller.get("name"))
            )
    return keys


@app.post("/api/hunt/lookup")
def hunt_lookup(payload: HuntLookupIn) -> dict[str, Any]:
    """Fetch one card's offers and sort them by whether we are already buying
    from that seller.

    Nothing is added to the order here. The point of the step is to see the
    answer first: a card at 300 from someone already in the plan costs no extra
    postage, and that usually beats 250 from a stranger. One polite topdeck
    request, on demand.
    """
    with _HUNT_CACHE_LOCK:
        held = _HUNT_CACHE.get(payload.hunt_id)
    if not held:
        raise HTTPException(
            status_code=404,
            detail="этот поиск больше не в памяти — запустите охоту заново",
        )

    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="не указана карта")
    card = db().by_name(name)
    if card:
        name = card.get("name") or name

    want = Want(name=name, quantity=max(1, payload.quantity))
    hunter = Hunter(db(), TopdeckClient(), sets())
    try:
        candidates = hunter.gather([want])
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=502, content={"detail": "topdeck request failed: %s" % exc}
        )
    hunter.apply_filters(candidates, payload.filters.to_filters())
    hunter.resolve(candidates)

    # Held aside, not merged: the plan must not move until the user says so.
    with _HUNT_CACHE_LOCK:
        held.setdefault("pending", {})[normalize_name(name)] = {
            "want": want,
            "candidates": candidates,
        }

    in_plan = _plan_sellers(held)
    usable = [c for c in candidates if not c.rejected and c.stock > 0]

    def row(cand: Any) -> dict[str, Any]:
        seller = cand.offer.seller
        key = (
            "shop:%s" % seller.name if seller.is_shop
            else "user:%s" % (seller.id or seller.name)
        )
        return {
            "key": cand.offer.key,
            "seller_name": seller.name,
            "seller_kind": seller.kind,
            "seller_city": seller.city,
            "seller_refs": seller.refs,
            "price": cand.unit_price,
            "qty": cand.stock,
            "qty_dispute": cand.qty_dispute,
            "certainty": cand.certainty,
            "line": cand.offer.line,
            "set_code": cand.parsed.set_code,
            "language": cand.parsed.language,
            "condition": cand.parsed.condition,
            "url": cand.offer.url,
            "in_plan": key in in_plan,
        }

    rows = sorted((row(c) for c in usable), key=lambda r: r["price"])
    return {
        "name": name,
        "quantity": want.quantity,
        "with_sellers_in_plan": [r for r in rows if r["in_plan"]],
        "elsewhere": [r for r in rows if not r["in_plan"]],
        "rejected": sum(1 for c in candidates if c.rejected),
        "offers": len(candidates),
    }


@app.post("/api/hunt/add")
def hunt_add(payload: HuntAddIn) -> dict[str, Any]:
    """Confirmed: the card joins the order, from the listing that was chosen."""
    with _HUNT_CACHE_LOCK:
        held = _HUNT_CACHE.get(payload.hunt_id)
    if not held:
        raise HTTPException(
            status_code=404,
            detail="этот поиск больше не в памяти — запустите охоту заново",
        )

    key = normalize_name(payload.name)
    pending = (held.get("pending") or {}).get(key)
    if not pending:
        raise HTTPException(
            status_code=409,
            detail="сначала посмотрите, где эта карта есть",
        )

    with _HUNT_CACHE_LOCK:
        want = pending["want"]
        want.quantity = max(1, payload.quantity)
        # Replace rather than duplicate if the card is asked for twice.
        held["wants"] = [w for w in held["wants"]
                         if normalize_name(w.name) != key] + [want]
        held["candidates"] = [
            c for c in held["candidates"] if normalize_name(c.want) != key
        ] + pending["candidates"]
        held.pop("pending", None)
        if payload.offer_key:
            held.setdefault("pins", {})[want.name] = payload.offer_key

    return {
        "added": want.name,
        "quantity": want.quantity,
        "pinned": payload.offer_key or None,
        "wants": [w.as_dict() for w in held["wants"]],
    }


@app.post("/api/hunt/replan")
def hunt_replan(payload: ReplanIn) -> dict[str, Any]:
    """Rebuild the plan after the user refused an offer, a card, or some copies."""
    with _HUNT_CACHE_LOCK:
        held = _HUNT_CACHE.get(payload.hunt_id)
    if not held:
        raise HTTPException(
            status_code=404,
            detail="этот поиск больше не в памяти — запустите охоту заново",
        )

    skip_offers = set(payload.skip_offers)
    skip_wants = {n.strip().lower() for n in payload.skip_wants if n.strip()}
    quantities = {k.strip().lower(): int(v) for k, v in payload.quantities.items()}

    # Refusals are re-applied from scratch every time, never accumulated, so
    # taking one back is just leaving it out of the next call.
    candidates = held["candidates"]
    for cand in candidates:
        if cand.offer.key in skip_offers:
            cand.refused = "вы отказались от этого предложения"
        elif cand.want.strip().lower() in skip_wants:
            cand.refused = "вы решили не брать эту карту"
        else:
            cand.refused = None

    wants = []
    for want in held["wants"]:
        key = want.name.strip().lower()
        if key in skip_wants:
            continue
        qty = quantities.get(key, want.quantity)
        qty = max(0, min(int(qty), want.quantity))
        if qty <= 0:
            continue
        wants.append(replace(want, quantity=qty))

    # Pins set when a card was added by hand live in the cache; the ones the
    # interface sends win over them.
    pins = dict(held.get("pins") or {})
    pins.update(payload.pins or {})
    with _HUNT_CACHE_LOCK:
        held["pins"] = pins
        held["prefer_seller"] = payload.prefer_seller or None
        held["strategy"] = payload.strategy
        held["seller_fee"] = _seller_fee(payload.seller_fee)

    plan = build_plan(
        wants, candidates, prefer=payload.strategy,
        pins=pins, prefer_seller=payload.prefer_seller or None,
        seller_fee=_seller_fee(payload.seller_fee),
    )
    return {
        "hunt_id": payload.hunt_id,
        "wants": [w.as_dict() for w in wants],
        "plan": plan,
        "candidates": [c.as_dict() for c in candidates],
        "rejected_count": sum(1 for c in candidates if c.rejected),
        "refused_count": sum(1 for c in candidates if c.refused),
    }


@app.post("/api/hunt")
def hunt(payload: HuntIn) -> dict[str, Any]:
    if not payload.wants:
        raise HTTPException(status_code=400, detail="nothing to hunt for")

    collection = collection_store.load() if payload.use_collection else {}
    entries = [
        Want(name=w.name, quantity=w.quantity, set_code=w.set_code, section=w.section)
        for w in payload.wants
    ]
    wants = compute_wants(
        entries,
        collection if isinstance(collection, dict) else {},
        ordered=orders.ordered_counts() if payload.skip_ordered else None,
    )
    if not wants:
        return {
            "wants": [],
            "plan": {"lots": [], "unfilled": [], "total": 0, "sellers": 0},
            "candidates": [],
            "note": "your collection already covers every card in this list",
        }

    hunter = Hunter(db(), TopdeckClient(), sets())
    try:
        candidates = hunter.gather(wants)
    except Exception as exc:  # noqa: BLE001
        return JSONResponse(
            status_code=502, content={"detail": "topdeck request failed: %s" % exc}
        )

    hunter.apply_filters(candidates, payload.filters.to_filters())
    hunter.resolve(candidates)
    plan = build_plan(wants, candidates, prefer=payload.strategy,
                      seller_fee=_seller_fee(payload.seller_fee))

    return {
        "hunt_id": _remember_hunt(wants, candidates, payload.strategy,
                                  _seller_fee(payload.seller_fee)),
        "wants": [w.as_dict() for w in wants],
        "plan": plan,
        "candidates": [c.as_dict() for c in candidates],
        "rejected_count": sum(1 for c in candidates if c.rejected),
        "refused_count": 0,
    }


# One EDHREC request per commander, cached on disk for two weeks, so the client
# is long-lived and its throttle actually means something.
_rec_client = recommend.RecClient()


def _commander_and_deck(
    commander: str, deck_id: str
) -> tuple[str, dict[str, Any] | None]:
    """Resolve which commander is meant, and which deck is being asked about."""
    name = (commander or "").strip()
    deck = None

    if deck_id:
        try:
            deck = store().get_deck(deck_id)
        except DeckError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not name:
            # The deck knows its own commander; asking twice is pointless.
            for row in deck.get("cards", []):
                if row.get("section") == "commander":
                    name = row.get("name") or ""
                    break

    if not name:
        raise HTTPException(
            status_code=400,
            detail="не указан командир — выберите карту командира в колоде или впишите имя",
        )

    # Suggestions are only as good as the name: resolve it locally first so a
    # Russian name or a face name works too.
    card = db().by_name(name)
    if card:
        name = card.get("name") or name
    return name, deck


@app.get("/api/deckshape")
def deck_shape(
    commander: str = "",
    deck_id: str = "",
    refresh: bool = False,
) -> dict[str, Any]:
    """Your deck's shape beside the average deck on the same commander."""
    name, deck = _commander_and_deck(commander, deck_id)
    try:
        data = deckshape.compare(
            deck or {"cards": []}, name, db(), refresh=refresh, client=_rec_client
        )
    except deckshape.EdhrecError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    data["deck_id"] = deck_id or None
    data["has_deck"] = deck is not None
    data["deck_name"] = (deck or {}).get("name")
    return data


@app.get("/api/recommend")
def recommend_for_commander(
    commander: str = "",
    deck_id: str = "",
    refresh: bool = False,
    use_collection: bool = True,
) -> dict[str, Any]:
    """What people play with this commander, joined with your own data."""
    name, deck = _commander_and_deck(commander, deck_id)

    collection = collection_store.load() if use_collection else {}
    try:
        data = recommend.for_commander(
            name,
            db(),
            store(),
            collection=collection if isinstance(collection, dict) else {},
            deck=deck,
            refresh=refresh,
            client=_rec_client,
        )
    except recommend.EdhrecError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    data["asked"] = name
    data["deck_id"] = deck_id or None
    return data


# Sampling talks to someone else's server, so two of them at once is both rude
# and a race over the same cache file.
_sample_lock = threading.Lock()


@app.get("/api/cooccur/status")
def cooccur_status(commander: str = "", deck_id: str = "",
                   target: int = archidekt.DEFAULT_TARGET) -> dict[str, Any]:
    """How big the sample is. Reads the disk; fetches nothing."""
    name, _deck = _commander_and_deck(commander, deck_id)
    return dict(archidekt.state(name, target),
                chunk=archidekt.CHUNK, max_target=archidekt.MAX_TARGET)


@app.post("/api/cooccur/collect")
def cooccur_collect(payload: SampleIn) -> dict[str, Any]:
    """Fetch one chunk of decks towards the target.

    One chunk per call on purpose: the traffic stops as soon as the interface
    stops asking, which is what closing the panel does.
    """
    name, _deck = _commander_and_deck(payload.commander, payload.deck_id)
    if not _sample_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="выборка уже собирается")
    try:
        return dict(
            archidekt.collect(name, target=payload.target),
            chunk=archidekt.CHUNK, max_target=archidekt.MAX_TARGET,
        )
    except archidekt.ArchidektError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        _sample_lock.release()


@app.get("/api/cooccur")
def cooccur_suggestions(
    commander: str = "",
    deck_id: str = "",
    near: int = cooccur.NEAR_DECKS,
    limit: int = 60,
    min_share: float = 0.2,
    use_collection: bool = True,
) -> dict[str, Any]:
    """What the decks closest to yours play and yours does not."""
    name, deck = _commander_and_deck(commander, deck_id)
    sample = archidekt.load(name)

    names = [row.get("name", "") for row in (deck or {}).get("cards", [])
             if row.get("section") in ("main", "commander")]
    result = cooccur.suggest(names, sample, near=near, limit=limit,
                             min_share=min_share, exclude=[name])

    card = db().by_name(name)
    rec = {
        "commander": {
            "name": name,
            "decks": result["decks"],
            "color_identity": list((card or {}).get("color_identity") or ""),
        },
        "sections": cooccur.as_sections(result, db()),
    }
    collection = collection_store.load() if use_collection else {}
    data = recommend.enrich(
        rec, db(), store(),
        collection=collection if isinstance(collection, dict) else {},
        deck=deck,
    )
    data["sample"] = dict(archidekt.state(name, result["decks"] or 1),
                          chunk=archidekt.CHUNK)
    data["near"] = result["near"]
    data["overlap"] = result["overlap"]
    data["fallback"] = result["fallback"]
    data["asked"] = name
    data["deck_id"] = deck_id or None
    data["has_deck"] = deck is not None
    return data


@app.get("/api/cooccur/pairs")
def cooccur_pairs(card: str, commander: str = "", deck_id: str = "",
                  limit: int = 20) -> dict[str, Any]:
    """What travels with this card in the sample."""
    if not card.strip():
        raise HTTPException(status_code=400, detail="не указана карта")
    name, _deck = _commander_and_deck(commander, deck_id)
    found = db().by_name(card)
    return cooccur.pairs_for((found or {}).get("name") or card,
                             archidekt.load(name), limit=limit)


@app.post("/api/messages")
def messages(payload: MessagesIn) -> dict[str, Any]:
    return {
        "drafts": drafts_for_plan(payload.plan, payload.template),
        # A shop is not sent a private message: its lot becomes an order on its
        # own site, prepared up to the point where the user presses "buy".
        "orders": shops.orders_for_plan(payload.plan),
    }


class ShopOrderIn(BaseModel):
    names: list[str]
    domain: str


@app.post("/api/shops/order")
def shop_order(payload: ShopOrderIn) -> dict[str, Any]:
    """A paste-ready order for one shop from a bare list of names."""
    names = [n for n in payload.names if n and n.strip()]
    if not names:
        raise HTTPException(status_code=400, detail="список пуст")
    return shops.order_for_names(names, payload.domain)


@app.get("/api/shops")
def shops_known() -> dict[str, Any]:
    """Which shops we have verified links for."""
    return {
        "shops": [
            dict(cfg, domain=domain, known=True)
            for domain, cfg in sorted(shops.SHOPS.items())
        ]
    }


@app.middleware("http")
async def no_stale_frontend(request, call_next):
    """Make the browser revalidate the app's own HTML/JS/CSS every time.

    Without a Cache-Control header, browsers apply heuristic freshness: they
    happily serve a cached app.js for a while without asking. That silently
    resurrects bugs that were already fixed -- a fix looked like it had not
    worked when in truth the old script was still running. `no-cache` does not
    mean "do not store": with the ETag already present, revalidation is a cheap
    304, and a reload always runs the current code.
    """
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    return response


@app.get("/")
def index() -> FileResponse:
    path = os.path.join(WEB_DIR, "index.html")
    if not os.path.exists(path):
        raise HTTPException(status_code=500, detail="web/index.html is missing")
    return FileResponse(path)


if os.path.isdir(WEB_DIR):
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
