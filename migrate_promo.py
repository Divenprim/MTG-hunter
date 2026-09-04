"""Backfill promo_types / frame_effects / border_color / full_art / textless.

Needed for Secret Lair and special-treatment search. Secret Lair drops are NOT
separate sets -- everything inside `sld` shares one set code, and the drops and
treatments are only distinguishable through these fields.

Re-streams the bulk file; the cards table keeps its rows, we only fill columns.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.cards import _stream_bulk, connect  # noqa: E402

NEW_COLUMNS = [
    ("promo_types", "TEXT"),
    ("frame_effects", "TEXT"),
    ("border_color", "TEXT"),
    ("full_art", "INTEGER DEFAULT 0"),
    ("textless", "INTEGER DEFAULT 0"),
]


def log(msg: str) -> None:
    print(msg, flush=True)


conn = connect()
existing = {r["name"] for r in conn.execute("PRAGMA table_info(cards)")}
for name, decl in NEW_COLUMNS:
    if name not in existing:
        conn.execute("ALTER TABLE cards ADD COLUMN %s %s" % (name, decl))
        log("added column %s" % name)

rows = []
seen = 0
with conn:
    for card in _stream_bulk("default_cards", log):
        if "paper" not in (card.get("games") or []):
            continue
        rows.append(
            (
                ",".join(card.get("promo_types") or []),
                ",".join(card.get("frame_effects") or []),
                card.get("border_color"),
                1 if card.get("full_art") else 0,
                1 if card.get("textless") else 0,
                card["id"],
            )
        )
        seen += 1
        if len(rows) >= 5000:
            conn.executemany(
                "UPDATE cards SET promo_types=?, frame_effects=?, border_color=?, "
                "full_art=?, textless=? WHERE id=?",
                rows,
            )
            rows.clear()
    if rows:
        conn.executemany(
            "UPDATE cards SET promo_types=?, frame_effects=?, border_color=?, "
            "full_art=?, textless=? WHERE id=?",
            rows,
        )

log("updated %d printings" % seen)

with conn:
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cards_promo ON cards(promo_types)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_cards_frame ON cards(frame_effects)"
    )

for label, sql in (
    ("promo_types", "SELECT promo_types v, COUNT(*) n FROM cards WHERE promo_types<>'' "
                    "GROUP BY promo_types ORDER BY n DESC LIMIT 12"),
    ("frame_effects", "SELECT frame_effects v, COUNT(*) n FROM cards WHERE frame_effects<>'' "
                      "GROUP BY frame_effects ORDER BY n DESC LIMIT 12"),
    ("border_color", "SELECT border_color v, COUNT(*) n FROM cards GROUP BY border_color "
                     "ORDER BY n DESC LIMIT 6"),
):
    log("")
    log("--- %s ---" % label)
    for r in conn.execute(sql):
        log("   %-34s %d" % (str(r["v"])[:34], r["n"]))

conn.close()
