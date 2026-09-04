"""One-off: add cards.set_type and backfill it from data/sets.json.

Rebuilding from the bulk file would also work but takes minutes; the set index
we already have on disk carries the same information.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.cards import DATA_DIR, connect  # noqa: E402

conn = connect()
cols = {r["name"] for r in conn.execute("PRAGMA table_info(cards)")}
if "set_type" not in cols:
    conn.execute("ALTER TABLE cards ADD COLUMN set_type TEXT")
    print("added column set_type")
else:
    print("column set_type already present")

sets = json.load(open(os.path.join(DATA_DIR, "sets.json"), encoding="utf-8"))
rows = [
    ((s.get("set_type") or ""), (s.get("code") or "").lower())
    for s in sets.get("data", sets)
]
with conn:
    conn.executemany("UPDATE cards SET set_type = ? WHERE set_code = ?", rows)

missing = conn.execute(
    "SELECT COUNT(*) AS n FROM cards WHERE set_type IS NULL OR set_type = ''"
).fetchone()["n"]
total = conn.execute("SELECT COUNT(*) AS n FROM cards").fetchone()["n"]
print("backfilled set_type: %d/%d rows still empty" % (missing, total))

by_type = conn.execute(
    "SELECT set_type, COUNT(*) n FROM cards GROUP BY set_type ORDER BY n DESC LIMIT 8"
).fetchall()
for r in by_type:
    print("  %-18s %d" % (r["set_type"], r["n"]))
conn.close()
