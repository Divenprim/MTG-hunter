"""Load Scryfall Tagger's functional tags into an existing database.

Gives search by PURPOSE: `otag:ramp`, `otag:theft-creature`, `otag:threaten`,
`otag:"spot removal"` -- 4524 tags and 231k taggings, curated by the community,
instead of guessing at oracle text with regexes.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.cards import SCHEMA, build_tag_index, checkpoint, connect  # noqa: E402


def log(msg: str) -> None:
    print(msg, flush=True)


conn = connect()
conn.executescript(SCHEMA)
build_tag_index(conn, log)
checkpoint(conn, log)

log("")
log("--- biggest tags ---")
for r in conn.execute(
    "SELECT slug, card_count, description FROM tags ORDER BY card_count DESC LIMIT 10"
):
    log("   %-30s %5d  %s" % (r["slug"], r["card_count"], (r["description"] or "")[:44]))
conn.close()
