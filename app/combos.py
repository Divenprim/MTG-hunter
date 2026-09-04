"""Combos people have found, from Commander Spellbook.

Commander Spellbook is the community database of combos: which cards, in what
order, and what comes out at the end. It publishes everything as one bulk file
(json.commanderspellbook.com/variants.json.gz -- 26 MB compressed, 600 MB of
JSON inside), which is downloaded once and reduced to a small local database.

Why local and not the REST API: the question a deckbuilder actually asks is
"what combos does MY deck already have, and which am I one card short of" --
that is a join across a hundred card names against every combo there is. Asking
a website that, per card, would be hundreds of requests. Locally it is one SQL
query.

What is kept per combo: the cards it uses, the templates it needs ("any
sacrifice outlet"), what it produces, the steps, mana needed, prerequisites,
format legality and Spellbook's popularity. What is thrown away: card images,
oracle text and prices, all of which we already have or do not want.

The download is a deliberate act -- the interface asks -- and the file is
rebuilt only when asked again.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import urllib.request
import zlib
from collections import defaultdict
from typing import Any, Callable, Iterable, Iterator

from .cards import normalize_name
from .storage import data_dir

BULK_URL = "https://json.commanderspellbook.com/variants.json.gz"
USER_AGENT = "mtg-hunter/1.0 (local deckbuilding tool)"
TIMEOUT = 180
# 256 KB of compressed data expands to roughly 6 MB of text, which is enough to
# keep the decoder busy without letting the buffer grow huge.
CHUNK = 256 << 10
# How much consumed text may sit in front of the buffer before it is trimmed.
COMPACT_AT = 1 << 20

SCHEMA = """
CREATE TABLE IF NOT EXISTS combo (
  id            TEXT PRIMARY KEY,
  identity      TEXT,
  popularity    INTEGER,
  status        TEXT,
  spoiler       INTEGER,
  mana_needed   TEXT,
  prereq        TEXT,
  steps         TEXT,
  results       TEXT,
  commander     INTEGER,
  bracket       TEXT,
  card_count    INTEGER,
  template_count INTEGER,
  -- The base combo this is a variant of, and how many variants that base has.
  -- Spellbook generates variants mechanically: one base combo with an
  -- interchangeable piece becomes dozens of rows that differ only by which
  -- card fills the slot. Without the base id, a deck holding the shared piece
  -- gets nine near-identical suggestions instead of one.
  base_id       TEXT,
  variant_count INTEGER
);
CREATE TABLE IF NOT EXISTS combo_card (
  combo_id  TEXT NOT NULL,
  name_norm TEXT NOT NULL,
  name      TEXT NOT NULL,
  kind      TEXT NOT NULL          -- 'card' or 'template'
);
CREATE INDEX IF NOT EXISTS combo_card_norm ON combo_card(name_norm);
CREATE INDEX IF NOT EXISTS combo_card_combo ON combo_card(combo_id);
CREATE INDEX IF NOT EXISTS combo_popular ON combo(popularity DESC);
CREATE INDEX IF NOT EXISTS combo_base ON combo(base_id);
CREATE TABLE IF NOT EXISTS combo_meta (key TEXT PRIMARY KEY, value TEXT);
"""

# Bump when the tables change shape. The combo database is a cache of somebody
# else's file, so an old one is dropped rather than migrated -- the interface
# then says it is not built and offers to download it again.
SCHEMA_VERSION = "2"


class ComboError(RuntimeError):
    """Said in Russian, because it reaches the interface."""


def db_path() -> str:
    return os.path.join(data_dir(), "combos.sqlite")


def _connect(path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(path or db_path(), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS combo_meta (key TEXT PRIMARY KEY, value TEXT)")

    row = conn.execute(
        "SELECT value FROM combo_meta WHERE key = 'schema'").fetchone()
    have = row["value"] if row else None
    if have != SCHEMA_VERSION:
        # Cache from an older shape: drop it instead of migrating.
        with conn:
            for table in ("combo", "combo_card", "combo_new", "combo_card_new"):
                conn.execute("DROP TABLE IF EXISTS %s" % table)
            conn.execute("DELETE FROM combo_meta WHERE key IN ('built_at', 'combos')")
            conn.execute("INSERT OR REPLACE INTO combo_meta VALUES ('schema', ?)",
                         (SCHEMA_VERSION,))
    conn.executescript(SCHEMA)
    return conn


# --------------------------------------------------------------- streaming

def stream_variants(raw: Iterable[bytes]) -> Iterator[dict[str, Any]]:
    """Decode `{"variants": [ ... ]}` one element at a time.

    600 MB will not fit in memory as a Python structure, and the file is a
    single JSON document, so it is decoded incrementally: keep a text buffer,
    pull one complete object off the front with raw_decode, drop it, repeat.
    """
    decomp = zlib.decompressobj(16 + zlib.MAX_WBITS)
    decoder = json.JSONDecoder()
    buf = ""
    pos = 0
    started = False

    for block in raw:
        if not block:
            continue
        buf += decomp.decompress(block).decode("utf-8", "replace")

        if not started:
            marker = buf.find('"variants"')
            if marker < 0:
                continue
            bracket = buf.find("[", marker)
            if bracket < 0:
                continue
            pos = bracket + 1
            started = True

        while True:
            # Step over separators by index. Slicing the buffer instead -- which
            # is what an lstrip() here does -- copies megabytes per object and
            # makes the whole parse quadratic: 44k combos took ten minutes that
            # way, against seconds like this.
            while pos < len(buf) and buf[pos] in " \n\r\t,":
                pos += 1
            if pos >= len(buf) or buf[pos] == "]":
                break
            try:
                obj, end = decoder.raw_decode(buf, pos)
            except ValueError:
                break               # incomplete object: wait for more bytes
            pos = end
            yield obj

        # Drop what has been consumed, but only once it is worth the copy.
        if pos > COMPACT_AT:
            buf = buf[pos:]
            pos = 0


def _names(entries: Any, key: str) -> list[str]:
    out = []
    for item in entries or []:
        holder = item.get(key) or {}
        name = (holder.get("name") or "").strip()
        if name:
            out.append(name)
    return out


def _row(v: dict[str, Any]) -> tuple[dict[str, Any], list[tuple[str, str, str]]]:
    cards = _names(v.get("uses"), "card")
    templates = _names(v.get("requires"), "template")
    results = _names(v.get("produces"), "feature")
    legal = v.get("legalities") or {}

    prereq = " ".join(
        x for x in (v.get("easyPrerequisites") or "", v.get("notablePrerequisites") or "")
        if x
    ).strip()

    combo = {
        "id": v.get("id"),
        "identity": v.get("identity") or "",
        "popularity": int(v.get("popularity") or 0),
        "status": v.get("status") or "",
        "spoiler": 1 if v.get("spoiler") else 0,
        "mana_needed": v.get("manaNeeded") or "",
        "prereq": prereq,
        "steps": v.get("description") or "",
        "results": "; ".join(results),
        "commander": 1 if legal.get("commander") else 0,
        "bracket": v.get("bracketTag") or "",
        "card_count": len(cards),
        "template_count": len(templates),
        "base_id": ",".join(
            str((x or {}).get("id") or "") for x in (v.get("of") or [])
        ) or (v.get("id") or ""),
        "variant_count": int(v.get("variantCount") or 0),
    }
    members = [(normalize_name(n), n, "card") for n in cards]
    members += [(normalize_name(n), n, "template") for n in templates]
    return combo, members


def build(progress: Callable[[int, int], None] | None = None,
          url: str = BULK_URL, path: str | None = None) -> dict[str, Any]:
    """Download the bulk file and rebuild the local combo database.

    The new data goes into scratch tables in the same file and is swapped in at
    the end. Building a separate file and replacing it cannot work while anyone
    has the database open -- on Windows the replace simply fails -- and the
    interface rebuilds while the server is running by definition.
    """
    target = path or db_path()
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    started = time.time()
    seen = 0
    bytes_in = 0

    conn = _connect(target)
    try:
        conn.executescript(
            "DROP TABLE IF EXISTS combo_new;"
            "DROP TABLE IF EXISTS combo_card_new;"
            + SCHEMA.replace("combo (", "combo_new (")
                    .replace("combo_card (", "combo_card_new (")
                    .replace("ON combo_card(", "ON combo_card_new(")
                    .replace("ON combo(", "ON combo_new(")
                    .replace("combo_card_norm", "combo_card_new_norm")
                    .replace("combo_card_combo", "combo_card_new_combo")
                    .replace("combo_popular", "combo_new_popular")
                    .replace("combo_base", "combo_new_base")
        )

        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            total = int(resp.headers.get("Content-Length") or 0)

            def blocks():
                nonlocal bytes_in
                while True:
                    block = resp.read(CHUNK)
                    if not block:
                        return
                    bytes_in += len(block)
                    yield block

            batch_combos: list[tuple] = []
            batch_members: list[tuple] = []
            for variant in stream_variants(blocks()):
                combo, members = _row(variant)
                if not combo["id"]:
                    continue
                batch_combos.append(tuple(combo.values()))
                batch_members.extend((combo["id"], n, d, k) for n, d, k in members)
                seen += 1

                if len(batch_combos) >= 2000:
                    _flush(conn, batch_combos, batch_members, suffix="_new")
                    batch_combos, batch_members = [], []
                    if progress:
                        progress(seen, total and bytes_in)
            _flush(conn, batch_combos, batch_members, suffix="_new")

        if not seen:
            raise ComboError("в скачанном файле не нашлось ни одного комбо")

        # The swap: readers see the old data until this commits, and the new
        # data immediately after.
        with conn:
            conn.execute("DROP TABLE IF EXISTS combo")
            conn.execute("DROP TABLE IF EXISTS combo_card")
            conn.execute("ALTER TABLE combo_new RENAME TO combo")
            conn.execute("ALTER TABLE combo_card_new RENAME TO combo_card")
            conn.execute(
                "INSERT OR REPLACE INTO combo_meta VALUES ('built_at', ?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"),))
            conn.execute("INSERT OR REPLACE INTO combo_meta VALUES ('combos', ?)",
                         (str(seen),))
        conn.executescript(SCHEMA)      # indexes for the renamed tables
        conn.execute("ANALYZE")
        conn.commit()
    except ComboError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise ComboError("не удалось собрать базу комбо: %s" % exc) from exc
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    return {
        "combos": seen,
        "seconds": round(time.time() - started, 1),
        "downloaded": bytes_in,
    }


def _flush(conn: sqlite3.Connection, combos: list[tuple], members: list[tuple],
           suffix: str = "") -> None:
    if not combos:
        return
    with conn:
        conn.executemany(
            "INSERT OR REPLACE INTO combo%s VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)" % suffix,
            combos)
        conn.executemany(
            "INSERT INTO combo_card%s VALUES (?,?,?,?)" % suffix, members)


# ------------------------------------------------------------------ reading

class ComboDB:
    """Read side. Thread-local connection: FastAPI runs handlers in a pool."""

    def __init__(self, path: str | None = None) -> None:
        self.path = path or db_path()
        import threading
        self._local = threading.local()

    @property
    def ready(self) -> bool:
        """Built, and built in the shape this version reads."""
        if not os.path.exists(self.path):
            return False
        try:
            probe = sqlite3.connect(self.path, timeout=10)
            try:
                row = probe.execute(
                    "SELECT value FROM combo_meta WHERE key = 'schema'").fetchone()
                if not row or row[0] != SCHEMA_VERSION:
                    return False
                return bool(probe.execute("SELECT 1 FROM combo LIMIT 1").fetchone())
            finally:
                probe.close()
        except sqlite3.Error:
            return False

    @property
    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            if not self.ready:
                raise ComboError(
                    "база комбо ещё не собрана — нажмите «Скачать базу комбо»")
            conn = sqlite3.connect(self.path, timeout=30)
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return conn

    def status(self) -> dict[str, Any]:
        if not self.ready:
            return {"ready": False}
        rows = self.conn.execute("SELECT key, value FROM combo_meta").fetchall()
        meta = {r["key"]: r["value"] for r in rows}
        return {
            "ready": True,
            "combos": int(meta.get("combos") or 0),
            "built_at": meta.get("built_at"),
            "size": os.path.getsize(self.path),
        }

    def _combos(self, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        ids = list(dict.fromkeys(ids))
        if not ids:
            return {}
        out: dict[str, dict[str, Any]] = {}
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            rows = self.conn.execute(
                "SELECT * FROM combo WHERE id IN (%s)" % ",".join("?" * len(chunk)),
                chunk,
            ).fetchall()
            for row in rows:
                out[row["id"]] = dict(row)
        # Attach the members in one more query rather than one per combo.
        for i in range(0, len(ids), 400):
            chunk = ids[i:i + 400]
            rows = self.conn.execute(
                "SELECT * FROM combo_card WHERE combo_id IN (%s)"
                % ",".join("?" * len(chunk)),
                chunk,
            ).fetchall()
            for row in rows:
                target = out.get(row["combo_id"])
                if target is None:
                    continue
                target.setdefault("cards", [])
                target.setdefault("templates", [])
                if row["kind"] == "template":
                    target["templates"].append(row["name"])
                else:
                    target["cards"].append(row["name"])
        return out

    # Spellbook generates variants mechanically -- one base combo with an
    # interchangeable piece becomes up to 858 rows -- and 46k of the 108k rows
    # are played by nobody. Both are why the first version of this looked like
    # nonsense: nine rows for one combo, and suggestions no one has ever run.
    MIN_POPULARITY = 1

    def _collapse(self, rows: list[dict[str, Any]], have: set[str]) -> list[dict[str, Any]]:
        """One entry per base combo, and what it is actually short of.

        Variants of the same base differ only by which card fills a slot, so a
        deck holding the shared piece is not nine cards away from nine combos --
        it is one card away from one combo, and any of nine cards will do. That
        list of interchangeable cards is the useful answer: buy the cheapest.
        """
        by_base: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_base[row.get("base_id") or row["id"]].append(row)

        out: list[dict[str, Any]] = []
        for base, group in by_base.items():
            for row in group:
                row["missing"] = [
                    c for c in row.get("cards", []) if normalize_name(c) not in have
                ]
                row["have"] = [
                    c for c in row.get("cards", []) if normalize_name(c) in have
                ]
            fewest = min(len(r["missing"]) for r in group)
            best = max(
                (r for r in group if len(r["missing"]) == fewest),
                key=lambda r: (r.get("popularity") or 0),
            )

            # Every card that would finish it, across the interchangeable variants.
            one_of: list[str] = []
            if fewest == 1:
                for r in group:
                    if len(r["missing"]) == 1 and r["missing"][0] not in one_of:
                        one_of.append(r["missing"][0])

            entry = dict(best)
            entry["variants"] = len(group)
            entry["base"] = base
            entry["one_of"] = one_of
            # A template ("any sacrifice outlet") cannot be checked against a
            # card list, so a combo needing one is never reported as finished.
            entry["needs_template"] = list(entry.get("templates") or [])
            out.append(entry)

        out.sort(key=lambda r: (len(r["missing"]),
                                1 if r["needs_template"] else 0,
                                -(r.get("popularity") or 0)))
        return out

    def for_card(self, name: str, limit: int = 40,
                 commander_only: bool = True,
                 min_popularity: int | None = None) -> list[dict[str, Any]]:
        """Combos this card takes part in, one row per base combo."""
        key = normalize_name(name)
        floor = self.MIN_POPULARITY if min_popularity is None else min_popularity
        sql = (
            "SELECT c.id FROM combo c JOIN combo_card m ON m.combo_id = c.id "
            "WHERE m.name_norm = ? AND m.kind = 'card' AND c.spoiler = 0 "
            "  AND c.status = 'OK' "
            "  AND c.popularity >= ? AND c.card_count > 1 "
        )
        params: list[Any] = [key, floor]
        if commander_only:
            sql += " AND c.commander = 1"
        # Take a generous slice, then collapse: the top rows by popularity can
        # all belong to one base combo.
        sql += " ORDER BY c.popularity DESC LIMIT ?"
        params.append(max(limit * 12, 400))

        ids = [r["id"] for r in self.conn.execute(sql, params).fetchall()]
        found = self._combos(ids)
        rows = [found[i] for i in ids if i in found]
        collapsed = self._collapse(rows, {key})
        collapsed.sort(key=lambda r: -(r.get("popularity") or 0))
        # There is no deck and no collection here, so "missing" would be a claim
        # about the one card being looked at -- and the interface would print
        # "не хватает 1" for every combo in the world. The card window shows
        # combos, not a verdict on them.
        for entry in collapsed:
            entry.pop("missing", None)
            entry.pop("have", None)
            entry.pop("one_of", None)
        return collapsed[:limit]

    def for_deck(self, names: Iterable[str], max_missing: int = 1,
                 limit: int = 400, commander_only: bool = True,
                 min_popularity: int | None = None) -> dict[str, Any]:
        """Combos the deck has, and the ones it is a card or two short of."""
        have = {normalize_name(n) for n in names if n and n.strip()}
        floor = self.MIN_POPULARITY if min_popularity is None else min_popularity
        if not have:
            return {"complete": [], "near": [], "checked": 0}

        marks = ",".join("?" * len(have))
        sql = (
            "SELECT c.id AS id, "
            "       SUM(CASE WHEN m.name_norm IN (%s) THEN 1 ELSE 0 END) AS got "
            "FROM combo c JOIN combo_card m ON m.combo_id = c.id "
            "WHERE m.kind = 'card' AND c.spoiler = 0 AND c.status = 'OK' "
            "  AND c.popularity >= ? AND c.card_count > 1 "
            "%s"
            "  AND c.id IN (SELECT combo_id FROM combo_card "
            "               WHERE kind = 'card' AND name_norm IN (%s)) "
            "GROUP BY c.id "
            "HAVING got >= c.card_count - ? "
            "ORDER BY (c.card_count - got) ASC, c.popularity DESC "
            "LIMIT ?"
        ) % (marks, "AND c.commander = 1 " if commander_only else "", marks)

        params = list(have) + [floor] + list(have) + [max_missing, limit * 8]
        rows = self.conn.execute(sql, params).fetchall()
        found = self._combos([r["id"] for r in rows])
        collapsed = self._collapse(
            [found[r["id"]] for r in rows if r["id"] in found], have)

        complete = [c for c in collapsed if not c["missing"] and not c["needs_template"]]
        # A combo whose cards are all present but which also needs "any sacrifice
        # outlet" is not finished, and saying so would be a lie.
        by_template = [c for c in collapsed if not c["missing"] and c["needs_template"]]
        near = [c for c in collapsed if c["missing"]]

        return {
            "complete": complete[:limit],
            "needs_template": by_template[:limit],
            "near": near[:limit],
            "checked": len(have),
            "min_popularity": floor,
        }


__all__ = ["ComboDB", "ComboError", "build", "db_path", "stream_variants"]
