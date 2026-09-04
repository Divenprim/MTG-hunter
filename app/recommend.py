"""Commander suggestions, turned into something you can act on.

EDHREC says what people put in decks with a commander (app/edhrec.py). On its
own that is a list of English names -- useful on the site, not in a tool whose
whole point is the Russian market. So every suggestion is joined with what we
already know locally:

  * the card itself from the Scryfall database (type, mana, art, USD);
  * whether you already own it, from the collection;
  * whether it is already in this deck, and how many copies;
  * the rouble price we cached the last time topdeck was asked.

No topdeck requests are made here. A commander page is 150+ cards, and asking
topdeck for each at 1.5s a request would be four minutes and rude. Suggestions
show the prices already known; getting new ones stays a deliberate act.
"""

from __future__ import annotations

import json
import re
from typing import Any

from .cards import CardDB, normalize_name
from .decks import DeckStore
from .edhrec import EdhrecError, RecClient, recommendations

# A commander page includes the whole staple list; these are the cards nobody
# needs suggested, being in every deck of every commander.
ALWAYS_SUGGESTED = {"sol ring", "arcane signet", "command tower"}


def _usd(card: dict[str, Any] | None) -> float | None:
    if not card:
        return None
    prices = card.get("prices")
    if isinstance(prices, str):
        try:
            prices = json.loads(prices)
        except ValueError:
            prices = {}
    if not isinstance(prices, dict):
        return None
    for key in ("usd", "usd_foil", "usd_etched"):
        value = prices.get(key)
        if value:
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
    return None


def enrich(
    rec: dict[str, Any],
    db: CardDB,
    store: DeckStore,
    collection: dict[str, int] | None = None,
    deck: dict[str, Any] | None = None,
    identity: list[str] | None = None,
) -> dict[str, Any]:
    """Attach local card data, ownership, deck membership and cached prices."""
    have = {normalize_name(k): int(v or 0) for k, v in (collection or {}).items()}

    in_deck: dict[str, int] = {}
    for row in (deck or {}).get("cards", []) or []:
        key = normalize_name(row.get("name", ""))
        in_deck[key] = in_deck.get(key, 0) + int(row.get("quantity") or 0)

    names = [c["name"] for s in rec.get("sections", []) for c in s["cards"]]
    prices = store.get_prices(names)

    # The commander's colour identity bounds what may be suggested. EDHREC
    # respects it, but a card that slipped through would be unplayable, and
    # silently unplayable is the worst kind.
    allowed = set(x.upper() for x in (identity or rec["commander"].get("color_identity") or []))

    for section in rec.get("sections", []):
        kept = []
        for entry in section["cards"]:
            name = entry["name"]
            key = normalize_name(name)
            card = db.by_name(name)

            entry["card"] = {
                "name": (card or {}).get("name") or name,
                "ru_name": (card or {}).get("ru_name"),
                "image_small": (card or {}).get("image_small"),
                "image_normal": (card or {}).get("image_normal"),
                "type_line": (card or {}).get("type_line"),
                "mana_cost": (card or {}).get("mana_cost"),
                "cmc": (card or {}).get("cmc"),
                "set_code": (card or {}).get("set_code"),
                "rarity": (card or {}).get("rarity"),
                "color_identity": (card or {}).get("color_identity"),
                "oracle_id": (card or {}).get("oracle_id"),
            } if card else None
            entry["known"] = bool(card)
            entry["usd"] = _usd(card)
            entry["owned"] = have.get(key, 0)
            entry["in_deck"] = in_deck.get(key, 0)
            entry["staple"] = key in ALWAYS_SUGGESTED

            cached = prices.get(key)
            entry["rub"] = (
                {
                    "min": cached.get("rub_min"),
                    "median": cached.get("rub_median"),
                    "offers": cached.get("offers"),
                    "checked_at": cached.get("checked_at"),
                }
                if cached
                else None
            )

            if allowed and card:
                ci = card.get("color_identity") or ""
                letters = set(re.findall(r"[WUBRG]", str(ci).upper()))
                if letters - allowed:
                    entry["off_identity"] = True
            kept.append(entry)
        section["cards"] = kept

    rec["totals"] = {
        "cards": len(names),
        "owned": sum(
            1 for s in rec["sections"] for c in s["cards"] if c["owned"] > 0
        ),
        "in_deck": sum(
            1 for s in rec["sections"] for c in s["cards"] if c["in_deck"] > 0
        ),
        "priced": sum(
            1 for s in rec["sections"] for c in s["cards"] if c["rub"]
        ),
        "unknown": sum(
            1 for s in rec["sections"] for c in s["cards"] if not c["known"]
        ),
    }
    return rec


def for_commander(
    name: str,
    db: CardDB,
    store: DeckStore,
    collection: dict[str, int] | None = None,
    deck: dict[str, Any] | None = None,
    refresh: bool = False,
    client: RecClient | None = None,
) -> dict[str, Any]:
    """Everything the interface needs for one commander."""
    rec = recommendations(name, refresh=refresh, client=client)
    return enrich(rec, db, store, collection=collection, deck=deck)


__all__ = ["EdhrecError", "RecClient", "enrich", "for_commander"]
