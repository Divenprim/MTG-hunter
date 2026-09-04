"""Backfill cards.flavor_name and rebuild the name index.

Secret Lair and Universes Beyond print cards under a themed name: "Hammer of
Nazahn" is printed as "Piko Piko Hammer" in the Sonic drop, and Lightning Bolt
as "Vivi's Thunder Magic". 661 printings carry one.

It matters twice over: that is the name a user reads on the card and types into
the search box, and it is a name topdeck sellers write in their listings -- so
without it those offers cannot be matched to the card at all.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.cards import (  # noqa: E402
    _stream_bulk,
    build_name_index,
    checkpoint,
    connect,
)


def log(msg: str) -> None:
    print(msg, flush=True)


conn = connect()
existing = {r["name"] for r in conn.execute("PRAGMA table_info(cards)")}
if "flavor_name" not in existing:
    conn.execute("ALTER TABLE cards ADD COLUMN flavor_name TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_flavor ON cards(flavor_name)")
    log("added column flavor_name")

rows = []
found = 0
with conn:
    for card in _stream_bulk("default_cards", log):
        if "paper" not in (card.get("games") or []):
            continue
        flavor = card.get("flavor_name")
        if not flavor:
            continue
        rows.append((flavor, card["id"]))
        found += 1
        if len(rows) >= 2000:
            conn.executemany("UPDATE cards SET flavor_name = ? WHERE id = ?", rows)
            rows.clear()
    if rows:
        conn.executemany("UPDATE cards SET flavor_name = ? WHERE id = ?", rows)

log("stored %d flavour names" % found)

build_name_index(conn, log)
checkpoint(conn, log)

log("")
log("--- examples ---")
for r in conn.execute(
    "SELECT name, flavor_name, set_code, collector_number FROM cards "
    "WHERE flavor_name IS NOT NULL AND set_code = 'sld' "
    "ORDER BY CAST(collector_number AS INTEGER) DESC LIMIT 8"
):
    log("   %-30s -> %-28s %s #%s" % (
        r["name"][:30], r["flavor_name"][:28], r["set_code"], r["collector_number"]))
conn.close()
