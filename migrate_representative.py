"""One-off: add cards.representative and flag Scryfall's chosen printing."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.cards import connect, mark_representative_printings  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


conn = connect()
cols = {r["name"] for r in conn.execute("PRAGMA table_info(cards)")}
if "representative" not in cols:
    conn.execute("ALTER TABLE cards ADD COLUMN representative INTEGER DEFAULT 0")
    log("added column representative")
else:
    log("column representative already present")

mark_representative_printings(conn, log)
conn.close()
