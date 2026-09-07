"""Your deck against the average deck built on the same commander.

The recommendation panel answers "what else do people play". This answers a
different question, the one a list of cards cannot: is the *shape* of my deck
normal for this commander. Four ramp sources where the average deck runs ten
is a real answer; twenty-six creatures against twenty-eight is noise.

Where the numbers come from:

  * the type spread, the mana curve, the themes, the budget and bracket split
    are already on the commander page we cache for recommendations, so they
    cost no extra request at all;
  * how much ramp, draw and removal the average deck runs cannot be derived
    from counts of types, so the averaged decklist is fetched as well --
    json.edhrec.com/pages/average-decks/<slug>.json, one request, cached for
    two weeks like everything else from that site.

Both sides are then counted by the same local code, which matters more than it
sounds: the average deck's ramp is counted with our functional tags, not with
someone else's idea of what ramp is, so the two numbers are comparable.

The commander itself is left out of both sides -- EDHREC's average deck is the
99 cards around the commander.
"""

from __future__ import annotations

from typing import Any

from .cards import CardDB, _expand_tag_slugs
from .edhrec import EdhrecError, RecClient, parse_average, parse_shape

# Each card counts once, under the first type that matches. Land goes first
# because a creature land is a land in every deck list; this is also the order
# in which EDHREC's own counts add up to 99 cards plus the commander.
PRIMARY_TYPES: list[tuple[str, str]] = [
    ("land", "Земли"),
    ("creature", "Существа"),
    ("planeswalker", "Планисвокеры"),
    ("battle", "Битвы"),
    ("artifact", "Артефакты"),
    ("enchantment", "Чары"),
    ("instant", "Мгновенные"),
    ("sorcery", "Волшебства"),
]

# Functions, and the functional tag each one means. The slugs are the ones the
# automatic categories already use (app/deckbuild.AUTO_CATEGORIES), so "рампа"
# means the same thing in the builder, in the theme search and here.
#
# A card counts in every function it serves: a ramp spell that also draws a
# card is counted in both, because that is how it plays.
FUNCTIONS: list[tuple[str, str, str]] = [
    ("ramp", "Рампа", "ramp"),
    ("draw", "Добор", "draw"),
    ("removal", "Удаление", "removal"),
    ("tutor", "Туторы", "tutor"),
    ("counterspell", "Контрмагия", "counterspell"),
    ("protection", "Защита", "protection"),
]

# The one place where functions are not independent. Cultivate is tagged as a
# tutor (it does search a library) and as ramp, and counting it in both would
# report twenty "tutors" in a deck with two -- which is not what anyone means
# by the word. So ramp wins: a card that accelerates mana is ramp, not a tutor.
# The same order the automatic categories use, for the same reason.
BEATEN_BY: dict[str, set[str]] = {"tutor": {"ramp"}}

FUNCTION_LABELS: list[tuple[str, str]] = [
    (key, label) for key, label, _tag in FUNCTIONS
]

# Below this the difference is not worth a sentence: decks vary, and the
# average is an average, not a target.
NOTABLE_TYPE = 3
NOTABLE_FUNCTION = 2

_tag_cache: dict[str, set[str]] = {}


def _tags_for(slug: str) -> set[str]:
    """A functional tag plus everything filed under it.

    An empty answer is never cached: the tag tree is loaded per connection, so
    asking before this thread has one would otherwise poison the cache.
    """
    cached = _tag_cache.get(slug)
    if cached:
        return cached
    expanded = set(_expand_tag_slugs(slug))
    if expanded:
        _tag_cache[slug] = expanded
    return expanded


def _primary_type(type_line: str) -> str | None:
    lowered = (type_line or "").lower()
    for key, _label in PRIMARY_TYPES:
        if key in lowered:
            return key
    return None


def measure(rows: list[tuple[str, int]], db: CardDB) -> dict[str, Any]:
    """Count one decklist: types, functions, curve, basics.

    `rows` is (name, copies). Cards the local database does not know are
    counted in `unknown` rather than silently dropped -- a suggestion built on
    a list we only half understand should say so.
    """
    types: dict[str, int] = {}
    functions: dict[str, int] = {}
    curve: dict[int, int] = {}
    cards = 0
    basics = 0
    unknown = 0

    # Touch the connection first: the tag tree the expansion needs is loaded
    # when this thread opens its own connection to the card database.
    conn = db.conn
    wanted = {key: _tags_for(tag) for key, _label, tag in FUNCTIONS}

    for name, quantity in rows:
        qty = int(quantity or 0)
        if qty <= 0:
            continue
        cards += qty
        card = db.by_name(name)
        if not card:
            unknown += qty
            continue

        type_line = (card.get("type_line") or "")
        kind = _primary_type(type_line)
        if kind:
            types[kind] = types.get(kind, 0) + qty
        if "basic" in type_line.lower():
            basics += qty

        if kind == "land":
            # A land is a land, not a function. Otherwise nine fetchlands are
            # reported as nine "tutors" and a deck looks full of something it
            # does not have. This is the rule the automatic categories use as
            # well: land wins over every tag.
            continue

        bucket = min(7, int(card.get("cmc") or 0))
        curve[bucket] = curve.get(bucket, 0) + qty

        oracle_id = card.get("oracle_id")
        if not oracle_id:
            continue
        tags = {
            row["slug"]
            for row in conn.execute(
                "SELECT slug FROM card_tags WHERE oracle_id = ?", (oracle_id,)
            )
        }
        if not tags:
            continue
        serves = {key for key, slugs in wanted.items() if tags & slugs}
        for key, winners in BEATEN_BY.items():
            if key in serves and serves & winners:
                serves.discard(key)
        for key in serves:
            functions[key] = functions.get(key, 0) + qty

    return {
        "cards": cards,
        "basics": basics,
        "unknown": unknown,
        "types": types,
        "functions": functions,
        "curve": curve,
    }


def _lines(labels: list[tuple[str, str]], mine: dict[str, int],
           theirs: dict[str, int], notable: int) -> list[dict[str, Any]]:
    out = []
    for key, label in labels:
        yours = int(mine.get(key) or 0)
        average = int(theirs.get(key) or 0)
        if not yours and not average:
            continue
        delta = yours - average
        out.append({
            "key": key,
            "label": label,
            "yours": yours,
            "average": average,
            "delta": delta,
            "notable": abs(delta) >= notable,
        })
    return out


def deck_rows(deck: dict[str, Any]) -> list[tuple[str, int]]:
    """The 99: everything played except the commander itself."""
    return [
        (row.get("name") or "", int(row.get("quantity") or 0))
        for row in deck.get("cards", []) or []
        if row.get("section") == "main"
    ]


def compare(
    deck: dict[str, Any],
    commander: str,
    db: CardDB,
    refresh: bool = False,
    client: RecClient | None = None,
) -> dict[str, Any]:
    """Your deck's shape beside the average deck's, ready to render."""
    rec = client or RecClient()

    page = rec.fetch(commander, refresh=refresh)
    shape = parse_shape(page)

    average = parse_average(rec.fetch(commander, refresh=refresh,
                                      kind="average-decks"))
    average_rows = [(name, 1) for name in average["cards"]]

    mine = measure(deck_rows(deck), db)
    theirs = measure(average_rows, db)

    # Types come from EDHREC's own counts where it has them: those are averaged
    # over every deck, while the averaged decklist is one rounded example.
    edhrec_types = {k: v for k, v in shape["types"].items() if k not in
                    ("basic", "nonbasic")}
    average_types = edhrec_types or theirs["types"]

    return {
        "commander": commander,
        "decks": shape["decks"],
        # The averaged decklist collapses duplicate basics, so its length is
        # not the deck's size; EDHREC's own counts are.
        "cards": {"yours": mine["cards"], "average": sum(average_types.values())},
        "unknown": mine["unknown"] + theirs["unknown"],
        "types": _lines(PRIMARY_TYPES, mine["types"], average_types, NOTABLE_TYPE),
        "functions": _lines(FUNCTION_LABELS, mine["functions"],
                            theirs["functions"], NOTABLE_FUNCTION),
        "basics": {"yours": mine["basics"],
                   "average": int(shape["types"].get("basic") or 0)},
        "curve": {"yours": mine["curve"], "average": shape["curve"] or theirs["curve"]},
        "themes": shape["themes"][:12],
        "budget": shape["budget"],
        "brackets": shape["brackets"],
        "combos": shape["combos"][:8],
        "average_cards": average["cards"],
        "cached": bool(page.get("_cached")) and bool(average.get("cached")),
        "fetched": average.get("fetched"),
    }


__all__ = [
    "BEATEN_BY", "EdhrecError", "FUNCTIONS", "FUNCTION_LABELS", "PRIMARY_TYPES",
    "compare", "deck_rows", "measure",
]
