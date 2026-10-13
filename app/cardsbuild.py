"""Сборка локальной базы карт: скачать Scryfall и разложить по таблицам.

Отделено от `cards.py`, где остался читатель. Это два разных занятия: сборка
бывает раз в месяц, идёт десять минут, качает 27 МБ и ходит в сеть; чтение
идёт при каждом нажатии и наружу не ходит никогда.

Про `requests` стоит сказать точно, потому что в плане ревью было записано
иначе: сервер тянет `requests` не ради этого файла. Он нужен topdeck, кешу
картинок, ввозу колод по ссылке и сканеру -- то есть остался бы в зависимостях
при любом разделении. Разделение здесь не ради зависимости, а ради того, что
читать проще файл про одно: было 1716 строк на два занятия сразу.

Зовут отсюда ровно два места: `build_db.py` и проверка здоровья базы.
"""

from __future__ import annotations

import gzip
import io
import json
import os
import sqlite3
import time
from typing import Any, Iterator

import requests

from .cards import (
    BULK_INDEX, DB_PATH, SCRYFALL_SEARCH, SCHEMA, USER_AGENT, Progress,
    _noop, connect, normalize_name,
)

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


def fetch_russian_printings_bulk(
    progress: Progress = _noop,
) -> list[tuple[str, str, str, str]]:
    """Read Russian printings from Scryfall's all_cards bulk file.

    This is intentionally used by release CI: one large static download is
    slower/heavier than the paginated search, but it avoids API rate limits on
    shared GitHub runner IPs and makes release production deterministic.
    """
    out: list[tuple[str, str, str, str]] = []
    for c in _stream_bulk("all_cards", progress):
        if c.get("lang") != "ru":
            continue
        if "paper" not in (c.get("games") or []):
            continue
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
    progress("  russian names from bulk: %d printings" % len(out))
    return out


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
        resp = None
        for attempt in range(8):
            resp = s.get(url, params=params, timeout=60)
            if resp.status_code == 404:
                return out
            if resp.status_code == 429 or 500 <= resp.status_code < 600:
                retry_after = resp.headers.get("Retry-After")
                try:
                    wait = float(retry_after) if retry_after else min(2 ** attempt, 15)
                except (TypeError, ValueError):
                    wait = min(2 ** attempt, 15)
                wait = max(0.5, min(wait, 30))
                progress(
                    "  Scryfall %d on Russian page %d; retrying in %.1fs"
                    % (resp.status_code, page + 1, wait)
                )
                time.sleep(wait)
                continue
            break
        if resp is None:
            raise RuntimeError("Scryfall request did not start")
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
    external_batch: list[tuple[str, int | None]] = []
    with conn:
        conn.execute("DELETE FROM cards_fts")
        conn.execute("DELETE FROM card_faces")
        conn.execute("DELETE FROM card_external_ids")
        for card in _stream_bulk("default_cards", progress):
            row = _row_from_card(card)
            if row is None:
                continue
            batch.append(row)
            multiverse = card.get("multiverse_ids") or []
            external_batch.append(
                (card["id"], int(multiverse[0]) if multiverse else None)
            )
            n += 1
            faces = _face_rows(card)
            face_batch.extend(faces)
            faces_n += len(faces)
            if len(batch) >= 5000:
                conn.executemany(INSERT_SQL, batch)
                conn.executemany(
                    "INSERT OR REPLACE INTO card_external_ids "
                    "(card_id, multiverse_id) VALUES (?,?)",
                    external_batch,
                )
                batch.clear()
                external_batch.clear()
            if len(face_batch) >= 5000:
                conn.executemany(FACE_INSERT_SQL, face_batch)
                face_batch.clear()
        if batch:
            conn.executemany(INSERT_SQL, batch)
            conn.executemany(
                "INSERT OR REPLACE INTO card_external_ids "
                "(card_id, multiverse_id) VALUES (?,?)",
                external_batch,
            )
        if face_batch:
            conn.executemany(FACE_INSERT_SQL, face_batch)
    progress("stored %d paper printings, %d faces" % (n, faces_n))

    ru_count = 0
    if include_russian:
        progress("fetching Russian printed names")
        if os.environ.get("MTGH_RUSSIAN_BULK") == "1":
            ru = fetch_russian_printings_bulk(progress)
        else:
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
