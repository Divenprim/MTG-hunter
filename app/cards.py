"""Local Scryfall card database: build, then query offline.

Why local: the hunt flow resolves thousands of listing lines against printings,
and doing that over the network would be both slow and rude to Scryfall.

Two data pulls:
  1. the `default_cards` bulk file (gzipped JSONL) -- every paper printing,
     English or the only printed language;
  2. a paginated `lang:ru` sweep (~21.8k printings) -- Russian printed names,
     needed both to search by Russian name and to match Russian listings.
     The 392MB `all_cards` bulk would give the same thing far more expensively.
"""

from __future__ import annotations

import gzip
import io
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, Iterator

import requests

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
DB_PATH = os.path.join(DATA_DIR, "cards.sqlite")
BULK_INDEX = "https://api.scryfall.com/bulk-data"
SCRYFALL_SEARCH = "https://api.scryfall.com/cards/search"
USER_AGENT = "mtg-hunter/1.1.0 (local personal tool)"

Progress = Callable[[str], None]


def _noop(msg: str) -> None:
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS cards (
    id                TEXT PRIMARY KEY,
    oracle_id         TEXT,
    name              TEXT NOT NULL,
    ru_name           TEXT,
    flavor_name       TEXT,
    set_code          TEXT NOT NULL,
    set_name          TEXT,
    collector_number  TEXT,
    rarity            TEXT,
    lang              TEXT,
    layout            TEXT,
    type_line         TEXT,
    oracle_text       TEXT,
    mana_cost         TEXT,
    cmc               REAL,
    colors            TEXT,
    color_identity    TEXT,
    power             TEXT,
    toughness         TEXT,
    loyalty           TEXT,
    legalities        TEXT,
    prices            TEXT,
    image_small       TEXT,
    image_normal      TEXT,
    released_at       TEXT,
    digital           INTEGER DEFAULT 0,
    finishes          TEXT,
    set_type          TEXT,
    representative    INTEGER DEFAULT 0,
    promo_types       TEXT,
    frame_effects     TEXT,
    border_color      TEXT,
    full_art          INTEGER DEFAULT 0,
    textless          INTEGER DEFAULT 0,
    keywords          TEXT
);
CREATE INDEX IF NOT EXISTS idx_cards_name      ON cards(name);
CREATE INDEX IF NOT EXISTS idx_cards_runame    ON cards(ru_name);
CREATE INDEX IF NOT EXISTS idx_cards_flavor    ON cards(flavor_name);
CREATE INDEX IF NOT EXISTS idx_cards_oracle    ON cards(oracle_id);
CREATE INDEX IF NOT EXISTS idx_cards_setnum    ON cards(set_code, collector_number);

CREATE TABLE IF NOT EXISTS ru_printings (
    oracle_id         TEXT,
    set_code          TEXT,
    collector_number  TEXT,
    printed_name      TEXT,
    PRIMARY KEY (set_code, collector_number)
);
CREATE INDEX IF NOT EXISTS idx_ru_oracle ON ru_printings(oracle_id);
CREATE INDEX IF NOT EXISTS idx_ru_name   ON ru_printings(printed_name);

-- One row per printed face. Needed because 4941 cards are stored under a
-- combined "A // B" name: without faces we cannot label what the user searched
-- for, and we can only ever show the front image.
CREATE TABLE IF NOT EXISTS card_faces (
    card_id           TEXT NOT NULL,
    oracle_id         TEXT,
    face_index        INTEGER NOT NULL,
    name              TEXT,
    printed_name      TEXT,
    type_line         TEXT,
    oracle_text       TEXT,
    mana_cost         TEXT,
    power             TEXT,
    toughness         TEXT,
    loyalty           TEXT,
    image_small       TEXT,
    image_normal      TEXT,
    PRIMARY KEY (card_id, face_index)
);
CREATE INDEX IF NOT EXISTS idx_faces_oracle ON card_faces(oracle_id);
CREATE INDEX IF NOT EXISTS idx_faces_name   ON card_faces(name);

-- Every name a card may legitimately be called: the full name, each face name,
-- and the Russian printed forms. This is the ONLY thing offer matching and deck
-- import are allowed to match against -- exactly, never by substring.
CREATE TABLE IF NOT EXISTS card_names (
    name_norm         TEXT NOT NULL,
    name_display      TEXT,
    oracle_id         TEXT NOT NULL,
    lang              TEXT,
    kind              TEXT,
    face_index        INTEGER DEFAULT -1
);
CREATE INDEX IF NOT EXISTS idx_cardnames_norm   ON card_names(name_norm);
CREATE INDEX IF NOT EXISTS idx_cardnames_oracle ON card_names(oracle_id);

CREATE VIRTUAL TABLE IF NOT EXISTS cards_fts USING fts5(
    name, ru_name, type_line, oracle_text, card_id UNINDEXED, tokenize='unicode61'
);

-- Functional tags from Scryfall Tagger: "ramp", "theft-creature", "threaten",
-- "spot removal". 4524 tags, 231k taggings, with a parent/child hierarchy.
-- This is what makes searching by PURPOSE possible instead of guessing at
-- oracle text with regexes.
CREATE TABLE IF NOT EXISTS tags (
    slug          TEXT PRIMARY KEY,
    label         TEXT,
    description   TEXT,
    parents       TEXT,          -- comma-separated slugs
    children      TEXT,          -- comma-separated slugs
    aliases       TEXT,
    card_count    INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS card_tags (
    oracle_id     TEXT NOT NULL,
    slug          TEXT NOT NULL,
    weight        TEXT,
    PRIMARY KEY (oracle_id, slug)
);
CREATE INDEX IF NOT EXISTS idx_cardtags_slug   ON card_tags(slug);
CREATE INDEX IF NOT EXISTS idx_cardtags_oracle ON card_tags(oracle_id);

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    # We hand each thread its own connection, and sqlite's page cache is
    # PER CONNECTION -- so without mmap every new thread re-reads pages and
    # each search cost over a second. mmap is shared through the OS page cache,
    # which makes the connections effectively share warm data.
    conn.execute("PRAGMA mmap_size=%d" % (512 * 1024 * 1024))
    conn.execute("PRAGMA cache_size=-32000")  # 32 MB per connection
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def database_is_complete(path: str = DB_PATH, require_russian: bool = True) -> bool:
    """Return whether *path* contains every index produced by a full build.

    Merely checking that cards.sqlite exists is unsafe: SQLite creates the file
    before the network downloads finish, so an interrupted first run leaves a
    valid-looking but functionally incomplete database behind.
    """
    if not os.path.isfile(path):
        return False
    conn: sqlite3.Connection | None = None
    try:
        conn = sqlite3.connect(Path(path).resolve().as_uri() + "?mode=ro", uri=True)
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
            )
        }
        required = {
            "cards", "ru_printings", "card_faces", "card_names",
            "tags", "card_tags", "cards_fts", "meta",
        }
        if not required.issubset(tables):
            return False
        meta = dict(conn.execute("SELECT key, value FROM meta"))
        expected_cards = int(meta.get("cards") or 0)
        if not meta.get("built_at") or expected_cards <= 0:
            return False
        if conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0] != expected_cards:
            return False
        for table in ("card_faces", "card_names", "tags", "card_tags", "cards_fts"):
            if conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] <= 0:
                return False
        if require_russian and conn.execute(
            "SELECT COUNT(*) FROM ru_printings"
        ).fetchone()[0] <= 0:
            return False
        if conn.execute(
            "SELECT COUNT(*) FROM cards WHERE representative = 1"
        ).fetchone()[0] <= 0:
            return False
        return True
    except (OSError, ValueError, sqlite3.Error):
        return False
    finally:
        if conn is not None:
            conn.close()


def checkpoint(conn: sqlite3.Connection, progress: Progress = _noop) -> None:
    """Fold the WAL back into the database file and truncate it.

    Builds and migrations leave a huge WAL behind (147 MB was measured), and
    every fresh connection then has to build a snapshot of it -- which added
    about a second to every single search. Always call this after writing.
    """
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.execute("ANALYZE")
    conn.execute("PRAGMA optimize")
    progress("checkpointed WAL and refreshed statistics")


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    return s


def _stream_bulk(bulk_type: str, progress: Progress) -> Iterator[dict[str, Any]]:
    s = _session()
    index = s.get(BULK_INDEX, timeout=60).json()["data"]
    entry = next((b for b in index if b["type"] == bulk_type), None)
    if entry is None:
        raise RuntimeError("bulk type %r not offered by Scryfall" % bulk_type)
    url = entry.get("jsonl_download_uri")
    if not url:
        raise RuntimeError("Scryfall no longer offers a JSONL download for %s" % bulk_type)
    size_mb = (entry.get("compressed_size") or 0) / 1048576
    progress("downloading %s (%.0f MB compressed)" % (entry["name"], size_mb))

    resp = s.get(url, stream=True, timeout=600)
    resp.raise_for_status()
    raw = gzip.GzipFile(fileobj=resp.raw)
    for i, line in enumerate(io.TextIOWrapper(raw, encoding="utf-8")):
        line = line.strip()
        if line:
            yield json.loads(line)
        if i and i % 20000 == 0:
            progress("  parsed %d printings" % i)


APOSTROPHES = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'"})


def normalize_name(name: str) -> str:
    """Canonical form for matching card names.

    Sellers and deck sites differ on apostrophes ("Tiamat's" vs "Tiamat’s"),
    spacing around "//", case, and stray punctuation. Matching must be exact
    after normalization -- substring matching is what causes a listing for
    "Tiamat's Fanatics" to be mistaken for "Tiamat".
    """
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", name).translate(APOSTROPHES)
    text = text.replace("\xa0", " ").strip().lower()
    text = re.sub(r"\s*//\s*", " // ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,;:!")


def _face_rows(card: dict[str, Any]) -> list[tuple]:
    faces = card.get("card_faces") or []
    if not isinstance(faces, list) or not faces:
        return []
    out: list[tuple] = []
    for i, f in enumerate(faces):
        if not isinstance(f, dict):
            continue
        uris = f.get("image_uris") or {}
        out.append(
            (
                card["id"],
                card.get("oracle_id"),
                i,
                f.get("name"),
                f.get("printed_name"),
                f.get("type_line"),
                f.get("oracle_text"),
                f.get("mana_cost"),
                f.get("power"),
                f.get("toughness"),
                f.get("loyalty"),
                uris.get("small"),
                uris.get("normal"),
            )
        )
    return out


FACE_INSERT_SQL = """
INSERT OR REPLACE INTO card_faces (
    card_id, oracle_id, face_index, name, printed_name, type_line, oracle_text,
    mana_cost, power, toughness, loyalty, image_small, image_normal
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
"""


def build_tag_index(conn: sqlite3.Connection, progress: Progress = _noop) -> int:
    """Load Scryfall Tagger's functional tags.

    These answer "what is this card FOR" -- ramp, spot removal, theft-creature,
    threaten -- which no amount of regex over oracle text gets right. The tags
    form a hierarchy, so asking for a parent must also return its children
    (`control changing effects` itself has no cards; they hang off its
    children).
    """
    raw: list[dict[str, Any]] = []
    tagging_rows: list[tuple] = []
    by_id: dict[str, str] = {}

    # One pass: the file is small, but parent_ids/child_ids reference tags by
    # UUID, so the id->slug map has to be complete before the hierarchy can be
    # written out.
    for tag in _stream_bulk("oracle_tags", progress):
        slug = tag.get("slug") or tag.get("label")
        if not slug:
            continue
        if tag.get("id"):
            by_id[tag["id"]] = slug
        raw.append(tag)
        for tagging in tag.get("taggings") or []:
            oracle_id = tagging.get("oracle_id")
            if oracle_id:
                tagging_rows.append((oracle_id, slug, tagging.get("weight") or ""))

    tag_rows = []
    for tag in raw:
        slug = tag.get("slug") or tag.get("label")
        tag_rows.append(
            (
                slug,
                tag.get("label") or slug,
                tag.get("description") or "",
                ",".join(by_id[i] for i in (tag.get("parent_ids") or []) if i in by_id),
                ",".join(by_id[i] for i in (tag.get("child_ids") or []) if i in by_id),
                ",".join(tag.get("aliases") or []),
                len(tag.get("taggings") or []),
            )
        )

    with conn:
        conn.execute("DELETE FROM tags")
        conn.execute("DELETE FROM card_tags")
        conn.executemany(
            "INSERT OR REPLACE INTO tags "
            "(slug, label, description, parents, children, aliases, card_count) "
            "VALUES (?,?,?,?,?,?,?)",
            tag_rows,
        )
        conn.executemany(
            "INSERT OR REPLACE INTO card_tags (oracle_id, slug, weight) VALUES (?,?,?)",
            tagging_rows,
        )
    progress("tags: %d tags, %d taggings" % (len(tag_rows), len(tagging_rows)))
    return len(tag_rows)


def build_name_index(conn: sqlite3.Connection, progress: Progress = _noop) -> int:
    """Rebuild card_names from cards, card_faces and ru_printings."""
    rows: list[tuple] = []

    for r in conn.execute(
        "SELECT DISTINCT oracle_id, name FROM cards WHERE oracle_id IS NOT NULL"
    ):
        if r["name"]:
            rows.append((normalize_name(r["name"]), r["name"], r["oracle_id"], "en", "full", -1))

    for r in conn.execute(
        "SELECT DISTINCT oracle_id, ru_name FROM cards "
        "WHERE oracle_id IS NOT NULL AND ru_name IS NOT NULL AND ru_name <> ''"
    ):
        rows.append((normalize_name(r["ru_name"]), r["ru_name"], r["oracle_id"], "ru", "full", -1))

    # Flavour names ("Piko Piko Hammer" for Hammer of Nazahn). 661 printings
    # carry one, and both search boxes and topdeck sellers use them.
    for r in conn.execute(
        "SELECT DISTINCT oracle_id, flavor_name FROM cards "
        "WHERE oracle_id IS NOT NULL AND flavor_name IS NOT NULL AND flavor_name <> ''"
    ):
        rows.append(
            (normalize_name(r["flavor_name"]), r["flavor_name"], r["oracle_id"],
             "en", "flavor", -1)
        )

    for r in conn.execute(
        "SELECT DISTINCT oracle_id, face_index, name, printed_name FROM card_faces "
        "WHERE oracle_id IS NOT NULL"
    ):
        if r["name"]:
            rows.append(
                (normalize_name(r["name"]), r["name"], r["oracle_id"], "en", "face", r["face_index"])
            )
        if r["printed_name"]:
            rows.append(
                (
                    normalize_name(r["printed_name"]),
                    r["printed_name"],
                    r["oracle_id"],
                    "ru",
                    "face",
                    r["face_index"],
                )
            )

    seen: set[tuple] = set()
    unique = []
    for row in rows:
        if row[0] and row not in seen:
            seen.add(row)
            unique.append(row)

    with conn:
        conn.execute("DELETE FROM card_names")
        conn.executemany(
            "INSERT INTO card_names "
            "(name_norm, name_display, oracle_id, lang, kind, face_index) "
            "VALUES (?,?,?,?,?,?)",
            unique,
        )
    progress("name index: %d entries" % len(unique))
    return len(unique)


def _image_uris(card: dict[str, Any]) -> tuple[str | None, str | None]:
    uris = card.get("image_uris") or {}
    if not uris:
        faces = card.get("card_faces") or []
        if faces and isinstance(faces[0], dict):
            uris = faces[0].get("image_uris") or {}
    return uris.get("small"), uris.get("normal")


def _oracle_text(card: dict[str, Any]) -> str:
    if card.get("oracle_text"):
        return card["oracle_text"]
    faces = card.get("card_faces") or []
    return "\n--\n".join(f.get("oracle_text", "") for f in faces if isinstance(f, dict))


def _row_from_card(card: dict[str, Any]) -> tuple | None:
    if card.get("object") != "card":
        return None
    # Paper only: Arena/MTGO printings are not for sale on topdeck.
    if "paper" not in (card.get("games") or []):
        return None
    small, normal = _image_uris(card)
    return (
        card["id"],
        card.get("oracle_id"),
        card.get("name") or "",
        None,  # ru_name filled later
        card.get("flavor_name"),
        (card.get("set") or "").lower(),
        card.get("set_name"),
        card.get("collector_number"),
        card.get("rarity"),
        card.get("lang"),
        card.get("layout"),
        card.get("type_line"),
        _oracle_text(card),
        card.get("mana_cost"),
        card.get("cmc"),
        "".join(card.get("colors") or []),
        "".join(card.get("color_identity") or []),
        card.get("power"),
        card.get("toughness"),
        card.get("loyalty"),
        json.dumps(card.get("legalities") or {}),
        json.dumps(card.get("prices") or {}),
        small,
        normal,
        card.get("released_at"),
        1 if card.get("digital") else 0,
        ",".join(card.get("finishes") or []),
        card.get("set_type"),
        ",".join(card.get("promo_types") or []),
        ",".join(card.get("frame_effects") or []),
        card.get("border_color"),
        1 if card.get("full_art") else 0,
        1 if card.get("textless") else 0,
        ",".join(card.get("keywords") or []),
    )


INSERT_SQL = """
INSERT OR REPLACE INTO cards (
    id, oracle_id, name, ru_name, flavor_name, set_code, set_name, collector_number, rarity,
    lang, layout, type_line, oracle_text, mana_cost, cmc, colors, color_identity,
    power, toughness, loyalty, legalities, prices, image_small, image_normal,
    released_at, digital, finishes, set_type,
    promo_types, frame_effects, border_color, full_art, textless, keywords
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
"""

# Which printing represents a card in a list. Without this, ordering by release
# date alone surfaces reprint-vehicle sets like The List and Mystery Booster
# for almost every card, which is not what anyone means by "Lightning Bolt".
PREF_RANK_SQL = """
CASE set_type
    WHEN 'core'             THEN 0
    WHEN 'expansion'        THEN 1
    WHEN 'draft_innovation' THEN 2
    WHEN 'masters'          THEN 3
    WHEN 'commander'        THEN 4
    WHEN 'starter'          THEN 5
    WHEN 'duel_deck'        THEN 6
    WHEN 'box'              THEN 7
    WHEN 'from_the_vault'   THEN 8
    WHEN 'spellbook'        THEN 9
    WHEN 'premium_deck'     THEN 10
    WHEN 'archenemy'        THEN 11
    WHEN 'planechase'       THEN 12
    WHEN 'promo'            THEN 20
    WHEN 'memorabilia'      THEN 21
    WHEN 'token'            THEN 22
    WHEN 'funny'            THEN 23
    ELSE 15
END
"""


def fetch_russian_printings(progress: Progress = _noop) -> list[tuple[str, str, str, str]]:
    """Paginate `lang:ru unique=prints`. ~125 requests, ~20s at Scryfall's
    requested rate limit."""
    s = _session()
    out: list[tuple[str, str, str, str]] = []
    url: str | None = SCRYFALL_SEARCH
    params: dict[str, str] | None = {
        "q": "lang:ru",
        "unique": "prints",
        "include_multilingual": "true",
    }
    page = 0
    while url:
        resp = s.get(url, params=params, timeout=60)
        if resp.status_code == 404:
            break
        resp.raise_for_status()
        payload = resp.json()
        for c in payload.get("data", []):
            name = c.get("printed_name") or c.get("name")
            if not name:
                continue
            out.append(
                (
                    c.get("oracle_id") or "",
                    (c.get("set") or "").lower(),
                    c.get("collector_number") or "",
                    name,
                )
            )
        page += 1
        progress("  russian names: page %d, %d printings" % (page, len(out)))
        url = payload.get("next_page")
        params = None
        if url:
            time.sleep(0.12)  # Scryfall asks for 50-100ms between requests
    return out


NOISE_LAYOUTS = (
    "art_series", "token", "double_faced_token", "emblem",
    "scheme", "planar", "vanguard", "sticker",
)
NOISE_LAYOUT_SQL = "layout NOT IN (%s)" % ",".join("'%s'" % l for l in NOISE_LAYOUTS)


def mark_representative_printings(conn: sqlite3.Connection, progress: Progress = _noop) -> int:
    """Flag the printing Scryfall considers the most recognizable version of
    each card, using the `oracle_cards` bulk file (one entry per oracle id).

    This beats any local heuristic: ranking by release date surfaces reprint
    vehicles like The List, and ranking by set type surfaces oddities like
    Summer Magic.
    """
    ids: list[tuple[str]] = []
    for card in _stream_bulk("oracle_cards", progress):
        if card.get("id"):
            ids.append((card["id"],))
    with conn:
        conn.execute("UPDATE cards SET representative = 0")
        conn.executemany("UPDATE cards SET representative = 1 WHERE id = ?", ids)
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM cards WHERE representative = 1"
    ).fetchone()["n"]
    progress("flagged %d representative printings" % n)
    return n


def build_database(
    db_path: str = DB_PATH,
    include_russian: bool = True,
    progress: Progress = _noop,
) -> dict[str, int]:
    """Full rebuild. Always close SQLite cleanly, including after a failure."""
    conn = connect(db_path)
    try:
        return _build_database(conn, include_russian, progress)
    finally:
        conn.close()


def _build_database(
    conn: sqlite3.Connection,
    include_russian: bool,
    progress: Progress,
) -> dict[str, int]:
    """Populate an open database connection from the upstream data sources."""
    conn.executescript(SCHEMA)

    # Invalidate an earlier successful build before touching any data.  This
    # transaction is deliberately committed on its own, so an interruption in
    # a later download cannot leave the old completion marker behind.
    with conn:
        conn.execute("DELETE FROM meta WHERE key IN ('built_at', 'cards', 'russian')")

    progress("building card table from Scryfall bulk data")
    n = 0
    faces_n = 0
    batch: list[tuple] = []
    face_batch: list[tuple] = []
    with conn:
        conn.execute("DELETE FROM cards_fts")
        conn.execute("DELETE FROM card_faces")
        for card in _stream_bulk("default_cards", progress):
            row = _row_from_card(card)
            if row is None:
                continue
            batch.append(row)
            n += 1
            faces = _face_rows(card)
            face_batch.extend(faces)
            faces_n += len(faces)
            if len(batch) >= 5000:
                conn.executemany(INSERT_SQL, batch)
                batch.clear()
            if len(face_batch) >= 5000:
                conn.executemany(FACE_INSERT_SQL, face_batch)
                face_batch.clear()
        if batch:
            conn.executemany(INSERT_SQL, batch)
        if face_batch:
            conn.executemany(FACE_INSERT_SQL, face_batch)
    progress("stored %d paper printings, %d faces" % (n, faces_n))

    ru_count = 0
    if include_russian:
        progress("fetching Russian printed names")
        ru = fetch_russian_printings(progress)
        with conn:
            conn.executemany(
                "INSERT OR REPLACE INTO ru_printings "
                "(oracle_id, set_code, collector_number, printed_name) VALUES (?,?,?,?)",
                ru,
            )
            # Attach a Russian name to every printing of the same oracle card,
            # so searching by Russian name finds all printings, not just RU ones.
            conn.execute(
                """
                UPDATE cards SET ru_name = (
                    SELECT printed_name FROM ru_printings r
                    WHERE r.oracle_id = cards.oracle_id LIMIT 1
                )
                WHERE oracle_id IS NOT NULL
                """
            )
        ru_count = len(ru)
        progress("stored %d Russian printings" % ru_count)

    progress("flagging representative printings")
    mark_representative_printings(conn, progress)

    progress("building name index")
    build_name_index(conn, progress)

    progress("loading functional tags (Scryfall Tagger)")
    build_tag_index(conn, progress)

    progress("building full-text index")
    with conn:
        conn.execute(
            """
            INSERT INTO cards_fts (name, ru_name, type_line, oracle_text, card_id)
            SELECT name, COALESCE(ru_name,''), COALESCE(type_line,''),
                   COALESCE(oracle_text,''), id FROM cards
            """
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('built_at', datetime('now'))"
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('cards', ?)", (str(n),)
        )
        conn.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('russian', ?)",
            (str(ru_count),),
        )
    checkpoint(conn, progress)
    progress("done")
    return {"printings": n, "russian": ru_count}


# --------------------------------------------------------------------------- #
# Query language -- a practical subset of Scryfall syntax, evaluated in SQL.
# --------------------------------------------------------------------------- #

WUBRG = "WUBRG"
COLOR_LETTERS = {"w": "W", "u": "U", "b": "B", "r": "R", "g": "G", "c": ""}

# Guild / shard / wedge names, so the filter panel and power users can both
# write `id:abzan` instead of `id:wbg`.
COLOR_ALIASES = {
    "white": "w", "blue": "u", "black": "b", "red": "r", "green": "g",
    "colorless": "c",
    "azorius": "wu", "dimir": "ub", "rakdos": "br", "gruul": "rg", "selesnya": "gw",
    "orzhov": "wb", "izzet": "ur", "golgari": "bg", "boros": "rw", "simic": "gu",
    "bant": "gwu", "esper": "wub", "grixis": "ubr", "jund": "brg", "naya": "rgw",
    "abzan": "wbg", "jeskai": "urw", "sultai": "bgu", "mardu": "rwb", "temur": "gur",
    "yore": "wubr", "glint": "ubrg", "dune": "brgw", "ink": "rgwu", "witch": "gwub",
    "wubrg": "wubrg", "five": "wubrg", "rainbow": "wubrg",
}
SORTS = {
    "relevance": None,  # handled by the ORDER BY built in search()
    "name": "name ASC",
    "cmc": "cmc ASC, name ASC",
    "cmc_desc": "cmc DESC, name ASC",
    "released": "released_at DESC, name ASC",
    "released_asc": "released_at ASC, name ASC",
    # Sorting by rarity means "mythics first". 'special'/'bonus' must rank
    # BELOW the normal ladder, not above it -- mapping them to a high number
    # and sorting DESC put oddities at the top.
    "rarity": (
        "CASE rarity WHEN 'mythic' THEN 4 WHEN 'rare' THEN 3 WHEN 'uncommon' THEN 2 "
        "WHEN 'common' THEN 1 ELSE 0 END DESC, name ASC"
    ),
    "price": (
        "CAST(COALESCE(json_extract(prices,'$.usd'),'0') AS REAL) DESC, name ASC"
    ),
    "price_asc": (
        "CASE WHEN COALESCE(json_extract(prices,'$.usd'),'') = '' THEN 1 ELSE 0 END ASC, "
        "CAST(COALESCE(json_extract(prices,'$.usd'),'0') AS REAL) ASC, name ASC"
    ),
}


# Named groups of set codes. Secret Lair is the reason this exists: it is not
# one set but five (`sld` alone holds 2754 cards), and the individual drops are
# not sets at all -- they are only distinguishable by promo_types/frame_effects.
SET_GROUPS: dict[str, list[str]] = {
    "secretlair": ["sld", "slc", "slp", "slu", "pssc", "sls", "slx"],
    "secret-lair": ["sld", "slc", "slp", "slu", "pssc", "sls", "slx"],
}


def expand_set_values(values: list[str]) -> list[str]:
    """Turn `s:secretlair,clb` into the underlying set codes."""
    out: list[str] = []
    for raw in values:
        key = raw.strip().lower().replace(" ", "")
        if key in SET_GROUPS:
            out.extend(SET_GROUPS[key])
        elif key:
            out.append(key)
    # de-duplicate, keep order
    seen: set[str] = set()
    unique = []
    for code in out:
        if code not in seen:
            seen.add(code)
            unique.append(code)
    return unique


def _list_contains(column: str, value: str, clauses: list[str], params: list[Any]) -> None:
    """Match one entry of a comma-separated column.

    Delimiting matters: `finishes LIKE '%foil%'` also matches "nonfoil", and
    `frame_effects LIKE '%art%'` would match "extendedart".
    """
    clauses.append("(',' || COALESCE(%s,'') || ',') LIKE ?" % column)
    params.append("%%,%s,%%" % value.strip().lower())


# Tag hierarchy, cached in-process: parse_query is called per keystroke and the
# table is tiny (4524 rows).
_TAG_TREE: dict[str, list[str]] | None = None
_TAG_ALIASES: dict[str, str] | None = None


def load_tag_tree(conn: sqlite3.Connection) -> None:
    """Read the tag hierarchy and aliases once, for query expansion."""
    global _TAG_TREE, _TAG_ALIASES
    tree: dict[str, list[str]] = {}
    aliases: dict[str, str] = {}
    try:
        rows = conn.execute("SELECT slug, children, aliases, label FROM tags").fetchall()
    except sqlite3.OperationalError:
        _TAG_TREE, _TAG_ALIASES = {}, {}
        return
    for row in rows:
        slug = row["slug"]
        tree[slug] = [c for c in (row["children"] or "").split(",") if c]
        aliases[slug.lower()] = slug
        if row["label"]:
            aliases[row["label"].lower()] = slug
        for alias in (row["aliases"] or "").split(","):
            if alias:
                aliases[alias.strip().lower()] = slug
    _TAG_TREE, _TAG_ALIASES = tree, aliases


def _expand_tag_slugs(value: str) -> list[str]:
    """A tag plus everything beneath it. Comma-separated values mean OR."""
    if _TAG_TREE is None or _TAG_ALIASES is None:
        return []
    wanted: list[str] = []
    seen: set[str] = set()

    for raw in value.split(","):
        key = raw.strip().lower().replace("_", "-")
        slug = _TAG_ALIASES.get(key) or _TAG_ALIASES.get(key.replace("-", " "))
        if not slug:
            continue
        stack = [slug]
        while stack:
            current = stack.pop()
            if current in seen:
                continue
            seen.add(current)
            wanted.append(current)
            stack.extend(_TAG_TREE.get(current, []))
    return wanted


def _expand_colors(value: str) -> str:
    """'abzan' -> 'wbg'; 'wu' -> 'wu'."""
    low = value.strip().lower()
    return COLOR_ALIASES.get(low, low)


def _wanted_colors(letters: str) -> set[str]:
    """The set of colour letters a query asked for.

    Note: cards.colors is stored in whatever order Scryfall emits (in practice
    alphabetical: 'UW', 'GU'), NOT WUBRG. So never compare the string directly
    -- match on length plus presence of each letter instead.
    """
    return {COLOR_LETTERS[ch] for ch in letters if ch in COLOR_LETTERS and COLOR_LETTERS[ch]}


def _color_clauses(
    column: str, value: str, op: str, clauses: list[str], params: list[Any]
) -> None:
    """Colour matching with the three modes people actually want.

      c:wu   / c>=wu  -- includes at least these
      c=wu   / c!wu   -- exactly these
      c<=wu           -- only these or fewer (subset)

    `id:` defaults to subset, matching Scryfall and what Commander players mean.
    """
    letters = _expand_colors(value)
    if "c" in letters and len(letters.replace("c", "")) == 0:
        clauses.append("%s = ''" % column)
        return

    wanted = _wanted_colors(letters)
    if op in ("=", "!"):
        # Exactly these colours: same count, and each one present.
        clauses.append("LENGTH(%s) = ?" % column)
        params.append(len(wanted))
        for ch in sorted(wanted):
            clauses.append("%s LIKE ?" % column)
            params.append("%%%s%%" % ch)
    elif op == "<=":
        for ch in WUBRG:
            if ch not in wanted:
                clauses.append("%s NOT LIKE ?" % column)
                params.append("%%%s%%" % ch)
    else:  # ":" or ">=" -- includes at least these
        for ch in sorted(wanted):
            clauses.append("%s LIKE ?" % column)
            params.append("%%%s%%" % ch)


def _or_like(column: str, values: list[str], clauses: list[str], params: list[Any]) -> None:
    """Comma lists mean OR: `t:creature,land`, `r:rare,mythic`, `s:clb,m10`."""
    parts = []
    for v in values:
        parts.append("LOWER(%s) LIKE ?" % column)
        params.append("%%%s%%" % v.strip().lower())
    if parts:
        clauses.append("(%s)" % " OR ".join(parts))


def _or_equals(column: str, values: list[str], clauses: list[str], params: list[Any]) -> None:
    vals = [v.strip().lower() for v in values if v.strip()]
    if not vals:
        return
    clauses.append("LOWER(%s) IN (%s)" % (column, ",".join("?" * len(vals))))
    params.extend(vals)
RARITY_ALIASES = {
    "c": "common", "u": "uncommon", "r": "rare", "m": "mythic", "s": "special",
    "common": "common", "uncommon": "uncommon", "rare": "rare",
    "mythic": "mythic", "special": "special", "bonus": "bonus",
}
TOKEN_RE = re.compile(
    r"""(?P<key>[a-z_]+)(?P<op>[:=><!]=?|>|<)(?P<val>"[^"]*"|'[^']*'|\S+)|(?P<bare>"[^"]*"|'[^']*'|\S+)""",
    re.I,
)


@dataclass
class Query:
    where: str
    params: list[Any]
    fts: str | None = None


def _unquote(v: str) -> str:
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    return v


def parse_query(text: str) -> Query:
    """Translate a query string into a SQL WHERE clause.

    Supported:
      t:creature  type:goblin      o:"draw a card"  oracle:flying
      c:rw  color:wu              id:esper / ci:abzan
      cmc>=3  mv<5  cmc:2
      r:mythic  rarity:rare
      s:clb  set:m10  e:2x2
      f:modern  format:commander  legal:pauper  banned:legacy
      pow>=4  tou<2  loy:3
      is:foil / is:nonfoil
      lang:ru
      bare words -> name or Russian name or oracle text
    """
    clauses: list[str] = []
    params: list[Any] = []
    fts_terms: list[str] = []

    for m in TOKEN_RE.finditer(text or ""):
        bare = m.group("bare")
        if bare:
            term = _unquote(bare)
            if term:
                fts_terms.append(term)
            continue

        key = (m.group("key") or "").lower()
        op = m.group("op") or ":"
        val = _unquote(m.group("val") or "")
        low = val.lower()

        if key in ("t", "type"):
            _or_like("type_line", val.split(","), clauses, params)
        elif key in ("o", "oracle", "text"):
            clauses.append("LOWER(oracle_text) LIKE ?")
            params.append("%%%s%%" % low)
        elif key in ("c", "color", "colors"):
            _color_clauses("colors", val, op, clauses, params)
        elif key in ("id", "ci", "identity"):
            # Scryfall semantics: identity is a SUBSET of what you asked for.
            _color_clauses("color_identity", val, op if op != ":" else "<=", clauses, params)
        elif key in ("cmc", "mv"):
            sql_op = {":": "=", "=": "=", ">": ">", "<": "<", ">=": ">=", "<=": "<="}.get(op, "=")
            try:
                params.append(float(val))
                clauses.append("cmc %s ?" % sql_op)
            except ValueError:
                pass
        elif key in ("r", "rarity"):
            _or_equals(
                "rarity",
                [RARITY_ALIASES.get(v.strip().lower(), v.strip().lower()) for v in val.split(",")],
                clauses,
                params,
            )
        elif key in ("s", "set", "e", "edition"):
            # `s:secretlair` expands to the five Secret Lair set codes.
            _or_equals("set_code", expand_set_values(val.split(",")), clauses, params)
        elif key in ("cn", "num", "number"):
            # Collector number. Numeric comparisons where possible, because a
            # Secret Lair drop is a contiguous run of numbers -- "cn>=2081
            # cn<=2087" is the only way to express "the Sonic drop", Scryfall
            # having no drop field at all. Non-numeric numbers ("IFIYW-2") fall
            # back to an exact string match.
            sql_op = {":": "=", "=": "=", ">": ">", "<": "<", ">=": ">=", "<=": "<="}.get(op, "=")
            try:
                numeric = int(val)
                clauses.append(
                    "(CAST(collector_number AS INTEGER) %s ? "
                    " AND collector_number GLOB '[0-9]*')" % sql_op
                )
                params.append(numeric)
            except ValueError:
                clauses.append("LOWER(collector_number) = ?")
                params.append(low)
        elif key == "released" or key == "date":
            sql_op = {":": "=", "=": "=", ">": ">", "<": "<", ">=": ">=", "<=": "<="}.get(op, "=")
            clauses.append("released_at %s ?" % sql_op)
            params.append(val)
        elif key in ("otag", "tag", "function", "func"):
            # Purpose, not wording: `otag:ramp`, `otag:theft-creature`.
            # Children are included, because a parent tag such as
            # "control changing effects" holds no cards itself -- they hang off
            # its children. Resolved against the tags table at query time by
            # the caller (see _expand_tag_slugs).
            wanted = _expand_tag_slugs(low)
            if wanted:
                clauses.append(
                    "oracle_id IN (SELECT oracle_id FROM card_tags WHERE slug IN (%s))"
                    % ",".join("?" * len(wanted))
                )
                params.extend(wanted)
            else:
                # Unknown tag: match nothing rather than silently everything.
                clauses.append("0=1")
        elif key in ("kw", "keyword"):
            # Printed keyword abilities (Defender, Flash, Flying…). Tagger has
            # no tags for these -- the only defender-related tag is
            # `turns-off-defender-self`, which means the opposite -- so the
            # keyword list is the only way to ask for them.
            parts = []
            for raw in val.split(","):
                word = raw.strip().lower()
                if not word:
                    continue
                parts.append("(',' || LOWER(COALESCE(keywords,'')) || ',') LIKE ?")
                params.append("%%,%s,%%" % word)
            if parts:
                clauses.append("(%s)" % " OR ".join(parts))
        elif key == "promo":
            _list_contains("promo_types", low, clauses, params)
        elif key == "frame":
            _list_contains("frame_effects", low, clauses, params)
        elif key == "border":
            clauses.append("LOWER(COALESCE(border_color,'')) = ?")
            params.append(low)
        elif key in ("f", "format", "legal"):
            fmts = [v.strip().lower() for v in val.split(",") if v.strip()]
            if fmts:
                parts = []
                for f in fmts:
                    parts.append("json_extract(legalities, '$.' || ?) = 'legal'")
                    params.append(f)
                clauses.append("(%s)" % " OR ".join(parts))
        elif key == "banned":
            clauses.append("json_extract(legalities, '$.' || ?) = 'banned'")
            params.append(low)
        elif key == "restricted":
            clauses.append("json_extract(legalities, '$.' || ?) = 'restricted'")
            params.append(low)
        elif key in ("pow", "power"):
            sql_op = {":": "=", "=": "=", ">": ">", "<": "<", ">=": ">=", "<=": "<="}.get(op, "=")
            clauses.append("CAST(power AS REAL) %s ?" % sql_op)
            params.append(val)
        elif key in ("tou", "toughness"):
            sql_op = {":": "=", "=": "=", ">": ">", "<": "<", ">=": ">=", "<=": "<="}.get(op, "=")
            clauses.append("CAST(toughness AS REAL) %s ?" % sql_op)
            params.append(val)
        elif key in ("loy", "loyalty"):
            clauses.append("loyalty = ?")
            params.append(val)
        elif key == "lang":
            clauses.append("lang = ?")
            params.append(low)
        elif key == "is":
            # Values below come from what is actually in the database, not from
            # guesswork: `borderless` lives in border_color, `showcase` and
            # `extendedart` in frame_effects, `serialized` in promo_types.
            if low in ("foil", "nonfoil", "glossy"):
                # `finishes` is a list ("nonfoil,foil"); LIKE '%foil%' would
                # also match "nonfoil", so the list must be delimited.
                _list_contains("finishes", low, clauses, params)
            elif low == "secretlair" or low == "secret-lair":
                _or_equals("set_code", SET_GROUPS["secretlair"], clauses, params)
            elif low == "borderless":
                clauses.append("LOWER(COALESCE(border_color,'')) = 'borderless'")
            elif low in ("showcase", "extendedart", "inverted", "enchantment",
                         "colorshifted", "shatteredglass", "etched"):
                # 'etched' is both a finish and a frame effect; accept either.
                if low == "etched":
                    clauses.append(
                        "((',' || COALESCE(finishes,'') || ',') LIKE '%,etched,%'"
                        " OR (',' || COALESCE(frame_effects,'') || ',') LIKE '%,etched,%')"
                    )
                else:
                    _list_contains("frame_effects", low, clauses, params)
            elif low in ("serialized", "boosterfun", "galaxyfoil", "surgefoil",
                         "ripplefoil", "silverfoil", "rainbowfoil", "universesbeyond",
                         "prerelease", "promopack", "setpromo", "mediainsert",
                         "playtest", "boxtopper", "poster", "sldbonus"):
                _list_contains("promo_types", low, clauses, params)
            elif low == "promo":
                clauses.append("COALESCE(promo_types,'') <> ''")
            elif low == "fullart":
                clauses.append("(full_art = 1 OR (',' || COALESCE(frame_effects,'') || ',')"
                               " LIKE '%,fullart,%')")
            elif low == "textless":
                clauses.append("textless = 1")
            elif low == "digital":
                clauses.append("digital = 1")
            elif low == "paper":
                clauses.append("digital = 0")
            elif low == "reprint":
                clauses.append(
                    "oracle_id IN (SELECT oracle_id FROM cards GROUP BY oracle_id "
                    "HAVING COUNT(*) > 1)"
                )
            else:
                # Unknown flag: try it against both list columns rather than
                # silently ignoring what the user asked for.
                clauses.append(
                    "((',' || COALESCE(promo_types,'') || ',') LIKE ?"
                    " OR (',' || COALESCE(frame_effects,'') || ',') LIKE ?)"
                )
                params.extend(["%%,%s,%%" % low, "%%,%s,%%" % low])
        elif key in ("n", "name"):
            clauses.append("(LOWER(name) LIKE ? OR LOWER(COALESCE(ru_name,'')) LIKE ?)")
            params.extend(["%%%s%%" % low, "%%%s%%" % low])
        else:
            # Unknown key: treat the whole token as free text rather than
            # silently dropping the user's intent.
            fts_terms.append("%s%s%s" % (key, op, val))

    where = " AND ".join(clauses) if clauses else "1=1"
    return Query(where=where, params=params, fts=" ".join(fts_terms) or None)


class CardDB:
    """Read-only access to the card database.

    The connection is thread-LOCAL, not shared. FastAPI runs sync handlers in a
    thread pool, and sqlite3 connections are bound to the thread that made them
    (`check_same_thread`), so a single shared connection raises
    "SQLite objects created in a thread can only be used in that same thread"
    as soon as two requests are served concurrently -- which is exactly what a
    browser does when it loads the page. Sequential curl calls tend to reuse one
    pool thread and hide it.

    Separate read connections are cheap and, with WAL enabled, read in parallel.
    """

    def __init__(self, path: str = DB_PATH) -> None:
        self.path = path
        self._local = threading.local()
        # Fail fast on a missing/corrupt database rather than at first query.
        self._local.conn = connect(path)
        # The tag hierarchy drives query expansion; read it once.
        load_tag_tree(self._local.conn)

    @property
    def conn(self) -> sqlite3.Connection:
        existing = getattr(self._local, "conn", None)
        if existing is None:
            existing = connect(self.path)
            self._local.conn = existing
        return existing

    @property
    def is_built(self) -> bool:
        row = self.conn.execute(
            "SELECT value FROM meta WHERE key='cards'"
        ).fetchone() if self._has_meta() else None
        return bool(row and int(row["value"] or 0) > 0)

    def _has_meta(self) -> bool:
        return bool(
            self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='meta'"
            ).fetchone()
        )

    def stats(self) -> dict[str, Any]:
        if not self._has_meta():
            return {"built": False, "printings": 0}
        n = self.conn.execute("SELECT COUNT(*) AS n FROM cards").fetchone()["n"]
        ru = self.conn.execute("SELECT COUNT(*) AS n FROM ru_printings").fetchone()["n"]
        built = self.conn.execute("SELECT value FROM meta WHERE key='built_at'").fetchone()
        return {
            "built": n > 0,
            "printings": n,
            "russian": ru,
            "built_at": built["value"] if built else None,
        }

    def count(self, query: str) -> int:
        """How many oracle cards match, for pagination and result counts."""
        q = parse_query(query)
        where = q.where
        params = list(q.params)
        if q.fts:
            like = "%%%s%%" % q.fts.lower()
            where += (
                " AND (LOWER(name) LIKE ? OR LOWER(COALESCE(ru_name,'')) LIKE ?"
                " OR oracle_id IN (SELECT oracle_id FROM card_names"
                "                  WHERE name_norm LIKE ?)"
                " OR id IN (SELECT card_id FROM cards_fts WHERE cards_fts MATCH ?))"
            )
            params.extend([like, like, "%%%s%%" % normalize_name(q.fts), _fts_escape(q.fts)])
        sql = (
            "SELECT COUNT(DISTINCT COALESCE(oracle_id, id)) AS n FROM cards "
            "WHERE (%s) AND %s" % (where, NOISE_LAYOUT_SQL)
        )
        return int(self.conn.execute(sql, params).fetchone()["n"])

    def search(
        self,
        query: str,
        limit: int = 200,
        offset: int = 0,
        sort: str = "relevance",
    ) -> list[dict[str, Any]]:
        """One row per oracle card, represented by a sensible printing.

        A window function picks that printing deterministically. An earlier
        version used GROUP BY with SELECT *, which lets SQLite return column
        values from an arbitrary row of the group -- so the set name and the
        image could describe different printings.
        """
        q = parse_query(query)
        where = q.where
        params = list(q.params)
        exact = ""

        if q.fts:
            # Substring on names is what people expect from a card search box;
            # the name index adds face names ("Petty Theft"), and FTS covers
            # multi-word oracle-text queries.
            like = "%%%s%%" % q.fts.lower()
            where += (
                " AND (LOWER(name) LIKE ? OR LOWER(COALESCE(ru_name,'')) LIKE ?"
                " OR oracle_id IN (SELECT oracle_id FROM card_names"
                "                  WHERE name_norm LIKE ?)"
                " OR id IN (SELECT card_id FROM cards_fts WHERE cards_fts MATCH ?))"
            )
            params.extend([like, like, "%%%s%%" % normalize_name(q.fts), _fts_escape(q.fts)])
            exact = normalize_name(q.fts)

        sql = """
            WITH filtered AS (
                SELECT *, {pref} AS pref_rank FROM cards
                WHERE ({where}) AND {no_noise}
            ),
            ranked AS (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY COALESCE(oracle_id, id)
                    -- If the query matched a FLAVOUR name, show the printing
                    -- that actually bears it: someone searching "Piko Piko
                    -- Hammer" wants the Sonic Secret Lair art, not whichever
                    -- printing of Hammer of Nazahn is otherwise canonical.
                    ORDER BY CASE WHEN ? <> ''
                                   AND LOWER(COALESCE(flavor_name,'')) = ?
                                  THEN 0 ELSE 1 END,
                             representative DESC, pref_rank ASC,
                             released_at DESC, collector_number ASC
                ) AS rn
                FROM filtered
            )
            SELECT * FROM ranked WHERE rn = 1
            ORDER BY {order}
            LIMIT ? OFFSET ?
        """.format(
            pref=PREF_RANK_SQL,
            where=where,
            no_noise=NOISE_LAYOUT_SQL,
            order=self._order_by(sort),
        )

        # Parameter order must follow the SQL: WHERE first, then the
        # ROW_NUMBER ordering inside the CTE, then the outer ORDER BY.
        params.extend([exact, exact])  # flavour-printing preference

        # Two exact-match tiers are always in the outer ORDER BY (two
        # parameters each); relevance adds the prefix tier on top.
        params.extend([exact, exact, exact, exact])
        if sort not in SORTS or sort == "relevance":
            # Two prefix tiers: own name first, then any name.
            prefix = (exact + "%") if exact else ""
            params.extend([exact, prefix, exact, prefix])
        params.extend([limit, offset])
        rows = self.conn.execute(sql, params).fetchall()
        cards = [self._card_dict(r) for r in rows]
        self._attach_faces(cards, matched_query=exact)
        return cards

    # An exact name hit is pinned to the top of EVERY sort order.
    #
    # Sorting used to replace this ranking entirely, so "tiamat" sorted by
    # ascending price listed "Livaan, Cultist of Tiamat" and "Tiamat's
    # Fanatics" before Tiamat itself -- the expensive exact match ended up
    # last. Searching for a card must always show that card first; the chosen
    # sort orders everything else.
    #
    # The full-name tier also outranks the face-name tier: "Lightning Bolt" is
    # a card and also the back face of "Emeritus of Conflict // Lightning Bolt".
    EXACT_TIERS_SQL = """
                CASE WHEN ? <> '' AND EXISTS (
                        SELECT 1 FROM card_names cn
                        WHERE cn.oracle_id = ranked.oracle_id
                          AND cn.name_norm = ? AND cn.kind = 'full'
                     ) THEN 0 ELSE 1 END,
                CASE WHEN ? <> '' AND EXISTS (
                        SELECT 1 FROM card_names cn
                        WHERE cn.oracle_id = ranked.oracle_id AND cn.name_norm = ?
                     ) THEN 0 ELSE 1 END,
    """
    # Prefix tiers mirror the exact ones: a card whose OWN name starts with what
    # you typed beats a card that merely has a FACE starting with it. Without
    # the split, typing "burg" put "Bilbo, Luckwearer // Burgle" above
    # "Burgeoning", because both matched the prefix and the tie-break was
    # alphabetical.
    PREFIX_TIER_SQL = """
                CASE WHEN ? <> '' AND EXISTS (
                        SELECT 1 FROM card_names cn
                        WHERE cn.oracle_id = ranked.oracle_id
                          AND cn.name_norm LIKE ? AND cn.kind = 'full'
                     ) THEN 0 ELSE 1 END,
                CASE WHEN ? <> '' AND EXISTS (
                        SELECT 1 FROM card_names cn
                        WHERE cn.oracle_id = ranked.oracle_id AND cn.name_norm LIKE ?
                     ) THEN 0 ELSE 1 END,
    """

    @classmethod
    def _order_by(cls, sort: str) -> str:
        explicit = SORTS.get(sort)
        if explicit:
            return cls.EXACT_TIERS_SQL + explicit
        return cls.EXACT_TIERS_SQL + cls.PREFIX_TIER_SQL + " name ASC"

    def _attach_faces(self, cards: list[dict[str, Any]], matched_query: str = "") -> None:
        """Add each card's faces, and say which face the query actually hit.

        Without this a search for "Petty Theft" returns a row labelled
        "Brazen Borrower // Petty Theft" showing the front image -- the user
        cannot tell that what they searched for is the back of that card.
        """
        if not cards:
            return
        ids = [c["id"] for c in cards]
        placeholders = ",".join("?" * len(ids))
        by_card: dict[str, list[dict[str, Any]]] = {}
        for row in self.conn.execute(
            "SELECT * FROM card_faces WHERE card_id IN (%s) ORDER BY card_id, face_index"
            % placeholders,
            ids,
        ):
            by_card.setdefault(row["card_id"], []).append(dict(row))

        for card in cards:
            faces = by_card.get(card["id"], [])
            card["faces"] = faces
            card["matched_face"] = None
            card["display_name"] = card["name"]
            if not faces or not matched_query:
                continue
            for face in faces:
                names = [face.get("name"), face.get("printed_name")]
                if any(normalize_name(n) == matched_query for n in names if n):
                    card["matched_face"] = face["face_index"]
                    card["display_name"] = face.get("name") or card["name"]
                    break

    def faces(self, card_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM card_faces WHERE card_id = ? ORDER BY face_index", (card_id,)
        ).fetchall()
        return [dict(r) for r in rows]

    def aliases_for_oracle(self, oracle_id: str) -> list[str]:
        """Every normalized name this card may be listed under -- full name,
        face names, Russian forms. Used to match seller listings exactly."""
        rows = self.conn.execute(
            "SELECT DISTINCT name_norm FROM card_names WHERE oracle_id = ?", (oracle_id,)
        ).fetchall()
        return [r["name_norm"] for r in rows if r["name_norm"]]

    def resolve_names(self, name: str) -> list[dict[str, Any]]:
        """Every card a given name may legitimately refer to. Exact match only."""
        norm = normalize_name(name)
        if not norm:
            return []
        rows = self.conn.execute(
            "SELECT DISTINCT oracle_id, name_display, lang, kind, face_index "
            "FROM card_names WHERE name_norm = ?",
            (norm,),
        ).fetchall()
        return [dict(r) for r in rows]

    def printings(self, oracle_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM cards WHERE oracle_id = ? ORDER BY released_at DESC",
            (oracle_id,),
        ).fetchall()
        return [self._card_dict(r) for r in rows]

    def by_name(self, name: str) -> dict[str, Any] | None:
        """Resolve a name to a card, EXACTLY.

        Used by deck import and offer matching, where a wrong answer means
        buying the wrong card. Goes through card_names, so "Petty Theft" and
        "Удар Молнии" both work, while "Tiamat" never resolves to
        "Tiamat's Fanatics".
        """
        matches = self.resolve_names(name)
        if not matches:
            return None

        # Prefer a full-name match over a face match: if some card is literally
        # called "X", that beats another card whose back face is called "X".
        matches.sort(key=lambda m: 0 if m["kind"] == "full" else 1)
        oracle_id = matches[0]["oracle_id"]

        row = self.conn.execute(
            "SELECT * FROM cards WHERE oracle_id = ? AND %s "
            "ORDER BY representative DESC, %s ASC, released_at DESC LIMIT 1"
            % (NOISE_LAYOUT_SQL, PREF_RANK_SQL),
            (oracle_id,),
        ).fetchone()
        if not row:
            return None

        card = self._card_dict(row)
        self._attach_faces([card], matched_query=normalize_name(name))
        card["ambiguous_name"] = len({m["oracle_id"] for m in matches}) > 1
        return card

    def by_set_number(self, set_code: str, number: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM cards WHERE set_code = ? AND collector_number = ? LIMIT 1",
            ((set_code or "").lower(), str(number)),
        ).fetchone()
        return self._card_dict(row) if row else None

    @staticmethod
    def _card_dict(row: sqlite3.Row) -> dict[str, Any]:
        d = dict(row)
        for key in ("legalities", "prices"):
            try:
                d[key] = json.loads(d.get(key) or "{}")
            except (TypeError, ValueError):
                d[key] = {}
        return d


def _fts_escape(text: str) -> str:
    """FTS5 MATCH needs bare words quoted to survive punctuation."""
    words = re.findall(r"[\w']+", text, re.UNICODE)
    return " ".join('"%s"' % w for w in words) if words else '""'
