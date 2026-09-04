"""Deciding which card a topdeck listing is actually for.

topdeck's search matches seller lines by substring, and it labels every result
with the name you SEARCHED FOR, not the card the seller is selling. Asking for
"Burgeoning" returns 69 offers all labelled `eng_name: "Burgeoning"`, whose
lines read:

    Urban burgeoning 10
    2 RTR Urban Burgeoning 10 руб.
    2 <b>Blighted Burgeoning</b> (NM, March of the Machine)

Those are three different cards, and the cheap ones are not the card you
wanted. So `eng_name` cannot be trusted at all: the only evidence is the
seller's own line.

The check therefore works the other way round. For a wanted card we collect its
own names, plus every OTHER card name that contains one of them as a substring
("Urban Burgeoning", "Blighted Burgeoning", "March of Burgeoning Life"). If a
line mentions one of those longer names, the listing is for that card and is
rejected -- with the real name reported, so the UI can say why.
"""

from __future__ import annotations

import html
import re
from typing import Any, Iterable

from .cards import CardDB, normalize_name
from .lineparse import price_in_line

MATCH = "match"
OTHER = "other"
UNCLEAR = "unclear"


def clean_line(line: str) -> str:
    """Seller line reduced to comparable text."""
    text = re.sub(r"<[^>]*>", " ", line or "")
    text = html.unescape(text)
    text = text.replace("\xa0", " ").replace("\t", " ")
    return normalize_name(re.sub(r"\s+", " ", text))


class OfferMatcher:
    """Per-card name evidence, cached for a batch of offers."""

    def __init__(self, db: CardDB) -> None:
        self.db = db
        self._aliases: dict[str, list[str]] = {}
        self._confusable: dict[str, list[tuple[str, str]]] = {}

    def aliases(self, name: str) -> list[str]:
        """Every name this card may legitimately be listed under."""
        key = normalize_name(name)
        if key in self._aliases:
            return self._aliases[key]

        names = {key}
        card = self.db.by_name(name)
        if card and card.get("oracle_id"):
            names.update(self.db.aliases_for_oracle(card["oracle_id"]))
        # Longest first: a line is checked against the most specific name we have.
        result = sorted((n for n in names if n), key=len, reverse=True)
        self._aliases[key] = result
        return result

    def confusable(self, name: str) -> list[tuple[str, str]]:
        """Other cards whose name CONTAINS one of this card's names.

        These are the traps: topdeck returns them for the shorter query and
        labels them with it.
        """
        key = normalize_name(name)
        if key in self._confusable:
            return self._confusable[key]

        own = set(self.aliases(name))
        found: dict[str, str] = {}
        for alias in own:
            if len(alias) < 3:
                continue
            rows = self.db.conn.execute(
                "SELECT DISTINCT name_norm, name_display FROM card_names "
                "WHERE name_norm LIKE ? AND name_norm <> ?",
                ("%" + alias + "%", alias),
            ).fetchall()
            for row in rows:
                other = row["name_norm"]
                if other in own:
                    continue
                found[other] = row["name_display"] or other
        # Longest first: "march of burgeoning life" must be tested before
        # "burgeoning life" if both existed.
        result = sorted(found.items(), key=lambda kv: len(kv[0]), reverse=True)
        self._confusable[key] = result
        return result

    def classify(self, want_name: str, line: str) -> dict[str, Any]:
        """Decide what a single seller line is for."""
        text = clean_line(line)
        if not text:
            return {"verdict": UNCLEAR, "reason": "продавец не указал строку"}

        # A longer, different card name in the line wins: it is what the seller
        # is selling.
        for other_norm, other_display in self.confusable(want_name):
            if other_norm in text:
                return {
                    "verdict": OTHER,
                    "actual": other_display,
                    "reason": "в строке продавца другая карта: «%s»" % other_display,
                }

        for alias in self.aliases(want_name):
            if alias and alias in text:
                return {"verdict": MATCH, "matched_alias": alias}

        return {
            "verdict": UNCLEAR,
            "reason": "в строке продавца не видно имени «%s»" % want_name,
        }


def classify_offers(
    db: CardDB, want_name: str, offers: Iterable[Any]
) -> list[dict[str, Any]]:
    """Classify a batch, returning one verdict per offer in order."""
    matcher = OfferMatcher(db)
    return [matcher.classify(want_name, getattr(o, "line", "") or "") for o in offers]


# A disagreement bigger than this is not rounding, it is a misread number.
PRICE_TOLERANCE = 1


def price_check(cost: int, line: str) -> dict[str, Any]:
    """Compare topdeck's price field with the price written in the line.

    topdeck parses seller lines itself and gets it wrong sometimes -- it read
    "#235/281" as 235 roubles for a card the seller priced at 1300. When the two
    disagree we cannot know which is right, so the offer is marked disputed and
    never allowed to be the headline cheapest.
    """
    written = price_in_line(line)
    if written is None or cost <= 0:
        return {"disputed": False, "written": written}
    if abs(written - cost) <= PRICE_TOLERANCE:
        return {"disputed": False, "written": written}
    return {
        "disputed": True,
        "written": written,
        "reason": "topdeck считает %d ₽, а в строке продавца %d ₽" % (cost, written),
    }
