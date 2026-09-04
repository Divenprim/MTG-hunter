"""Backfill cards.keywords from the Scryfall bulk file.

"Направление" is not always a functional tag: Defender, Flash, Flying and the
other 223 keyword abilities are printed keywords, and Tagger has no tag for
them (only `turns-off-defender-self` exists, which is the opposite thing).
So grouping or filtering by them needs the keyword list itself.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.cards import _stream_bulk, checkpoint, connect  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


conn = connect()
existing = {r["name"] for r in conn.execute("PRAGMA table_info(cards)")}
if "keywords" not in existing:
    conn.execute("ALTER TABLE cards ADD COLUMN keywords TEXT")
    log("added column keywords")

rows = []
seen = 0
with conn:
    for card in _stream_bulk("default_cards", log):
        if "paper" not in (card.get("games") or []):
            continue
        rows.append((",".join(card.get("keywords") or []), card["id"]))
        seen += 1
        if len(rows) >= 5000:
            conn.executemany("UPDATE cards SET keywords = ? WHERE id = ?", rows)
            rows.clear()
    if rows:
        conn.executemany("UPDATE cards SET keywords = ? WHERE id = ?", rows)
log("updated %d printings" % seen)

checkpoint(conn, log)

log("")
log("--- commonest keywords ---")
import collections
counter = collections.Counter()
for r in conn.execute("SELECT keywords FROM cards WHERE keywords <> ''"):
    for kw in r["keywords"].split(","):
        counter[kw] += 1
for kw, n in counter.most_common(14):
    log("   %-22s %d" % (kw, n))
log("")
log("distinct keywords: %d" % len(counter))
conn.close()
