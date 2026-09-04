"""Add card_faces + card_names to an existing database.

Re-streams the Scryfall bulk file because face data (names and per-face images)
was never stored. Cheaper than a full rebuild: the cards table is left alone.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.cards import (  # noqa: E402
    FACE_INSERT_SQL,
    SCHEMA,
    _face_rows,
    _stream_bulk,
    build_name_index,
    connect,
)


def log(msg: str) -> None:
    print(msg, flush=True)


conn = connect()
conn.executescript(SCHEMA)
log("schema ensured")

faces = 0
batch = []
with conn:
    conn.execute("DELETE FROM card_faces")
    for card in _stream_bulk("default_cards", log):
        if "paper" not in (card.get("games") or []):
            continue
        rows = _face_rows(card)
        if not rows:
            continue
        batch.extend(rows)
        faces += len(rows)
        if len(batch) >= 5000:
            conn.executemany(FACE_INSERT_SQL, batch)
            batch.clear()
    if batch:
        conn.executemany(FACE_INSERT_SQL, batch)
log("stored %d faces" % faces)

build_name_index(conn, log)

n = conn.execute("SELECT COUNT(*) n FROM card_names").fetchone()["n"]
multi = conn.execute(
    "SELECT COUNT(DISTINCT oracle_id) n FROM card_faces"
).fetchone()["n"]
log("done: %d name entries, %d multi-face cards" % (n, multi))
conn.close()
