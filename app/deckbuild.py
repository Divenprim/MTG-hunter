"""Deck analysis: enrichment, rule validation, stats, and rouble pricing.

Validation is the part a builder lives or dies by. It is easy to assemble 100
cards that cannot legally be played -- a card outside the commander's colour
identity, a second copy of a non-basic in a singleton format, a banned card --
and the whole point is to be told before you spend money on them.
"""

from __future__ import annotations

import statistics
from typing import Any, Iterable

from .cards import CardDB, normalize_name
from .decks import DeckStore
from .offermatch import MATCH, OfferMatcher, price_check
from .topdeck import TopdeckClient

BASIC_LAND_NAMES = {
    "plains", "island", "swamp", "mountain", "forest", "wastes",
    "snow-covered plains", "snow-covered island", "snow-covered swamp",
    "snow-covered mountain", "snow-covered forest",
}

SINGLETON_FORMATS = {"commander", "brawl", "oathbreaker", "duel", "paupercommander", "predh"}
DECK_SIZE = {
    "commander": 100, "brawl": 60, "oathbreaker": 60, "duel": 100,
    "paupercommander": 100, "predh": 100,
}


def _is_basic_land(card: dict[str, Any] | None, name: str) -> bool:
    if name.strip().lower() in BASIC_LAND_NAMES:
        return True
    return bool(card and "basic land" in (card.get("type_line") or "").lower())


def enrich(
    deck: dict[str, Any],
    db: CardDB,
    store: DeckStore,
    collection: dict[str, int] | None = None,
) -> dict[str, Any]:
    """Attach card data, ownership, and both price sources to every row."""
    collection = {str(k).lower(): int(v or 0) for k, v in (collection or {}).items()}
    prices = store.get_prices([c["name"] for c in deck.get("cards", [])])

    total_usd = 0.0
    total_rub = 0
    missing_rub = 0
    priced = 0
    unpriced: list[str] = []

    for row in deck.get("cards", []):
        card = db.by_name(row["name"])
        row["card"] = (
            {
                "oracle_id": card.get("oracle_id"),
                "name": card.get("name"),
                "ru_name": card.get("ru_name"),
                "flavor_name": card.get("flavor_name"),
                "image_small": card.get("image_small"),
                "image_normal": card.get("image_normal"),
                "set_code": card.get("set_code"),
                "type_line": card.get("type_line"),
                "mana_cost": card.get("mana_cost"),
                "cmc": card.get("cmc"),
                "colors": card.get("colors"),
                "color_identity": card.get("color_identity"),
                "rarity": card.get("rarity"),
                "keywords": card.get("keywords"),
                "prices": card.get("prices"),
                "legalities": card.get("legalities"),
            }
            if card
            else None
        )

        owned = collection.get(row["name"].lower(), 0)
        if not owned and card:
            for alias in (card.get("name"), card.get("ru_name")):
                if alias and alias.lower() in collection:
                    owned = collection[alias.lower()]
                    break
        row["owned"] = owned
        row["missing"] = max(0, int(row["quantity"]) - owned)

        try:
            usd = float(((card or {}).get("prices") or {}).get("usd") or 0)
        except (TypeError, ValueError):
            usd = 0.0
        row["unit_usd"] = usd or None
        total_usd += usd * int(row["quantity"])

        cached = prices.get(normalize_name(row["name"])) or prices.get(row["name"].lower())
        if cached and cached.get("rub_min"):
            row["rub"] = {
                "min": cached["rub_min"],
                "median": cached["rub_median"],
                "offers": cached["offers"],
                "seller": cached["cheapest_seller"],
                "line": cached["cheapest_line"],
                "url": cached["cheapest_url"],
                "checked_at": cached["checked_at"],
            }
            total_rub += cached["rub_min"] * int(row["quantity"])
            missing_rub += cached["rub_min"] * row["missing"]
            priced += 1
        else:
            row["rub"] = None
            unpriced.append(row["name"])

    deck["total_usd"] = round(total_usd, 2)
    deck["total_rub"] = total_rub
    deck["missing_rub"] = missing_rub
    deck["priced_cards"] = priced
    deck["unpriced_cards"] = unpriced
    deck["missing_copies"] = sum(r["missing"] for r in deck.get("cards", []))
    deck["stats"] = stats(deck)
    deck["problems"] = validate(deck)
    return deck


def stats(deck: dict[str, Any]) -> dict[str, Any]:
    """Curve, colours, type spread -- computed over what is actually played."""
    playable = [
        r for r in deck.get("cards", []) if r["section"] in ("main", "commander")
    ]
    curve: dict[int, int] = {}
    colors: dict[str, int] = {}
    types: dict[str, int] = {}
    mv_values: list[float] = []
    lands = 0
    copies = 0

    for row in playable:
        card = row.get("card")
        qty = int(row["quantity"])
        copies += qty
        if not card:
            continue
        type_line = (card.get("type_line") or "").lower()
        is_land = "land" in type_line
        if is_land:
            lands += qty
        else:
            bucket = min(7, int(card.get("cmc") or 0))
            curve[bucket] = curve.get(bucket, 0) + qty
            mv_values.extend([float(card.get("cmc") or 0)] * qty)

        for letter in (card.get("colors") or "") or "C":
            colors[letter] = colors.get(letter, 0) + qty

        for kind in ("creature", "instant", "sorcery", "artifact", "enchantment",
                     "planeswalker", "battle", "land"):
            if kind in type_line:
                types[kind] = types.get(kind, 0) + qty

    return {
        "copies": copies,
        "lands": lands,
        "curve": curve,
        "colors": colors,
        "types": types,
        "avg_mv": round(sum(mv_values) / len(mv_values), 2) if mv_values else None,
        "median_mv": round(statistics.median(mv_values), 2) if mv_values else None,
    }


def validate(deck: dict[str, Any]) -> list[dict[str, str]]:
    """Rule problems, each as {level, text}. `level` is 'error' or 'warn'."""
    fmt = (deck.get("format") or "commander").lower()
    problems: list[dict[str, str]] = []

    rows = deck.get("cards", [])
    commanders = [r for r in rows if r["section"] == "commander"]
    main = [r for r in rows if r["section"] == "main"]
    side = [r for r in rows if r["section"] == "side"]

    # --- unknown names -------------------------------------------------- #
    for row in rows:
        if not row.get("card"):
            problems.append({
                "level": "error",
                "text": "«%s» — такой карты нет в базе, проверьте написание" % row["name"],
            })

    # --- size ----------------------------------------------------------- #
    playable = sum(int(r["quantity"]) for r in main + commanders)
    if fmt in DECK_SIZE:
        need = DECK_SIZE[fmt]
        if playable != need:
            problems.append({
                "level": "error" if playable > need else "warn",
                "text": "В колоде %d карт, для %s нужно ровно %d" % (playable, fmt, need),
            })
    else:
        if playable < 60:
            problems.append({
                "level": "warn",
                "text": "В колоде %d карт, минимум для конструкта — 60" % playable,
            })
        if sum(int(r["quantity"]) for r in side) > 15:
            problems.append({"level": "error", "text": "В сайдборде больше 15 карт"})

    # --- copies --------------------------------------------------------- #
    singleton = fmt in SINGLETON_FORMATS
    seen: dict[str, int] = {}
    for row in main + commanders:
        card = row.get("card")
        if _is_basic_land(card, row["name"]):
            continue
        key = (card or {}).get("name") or row["name"]
        seen[key] = seen.get(key, 0) + int(row["quantity"])
    for name, count in seen.items():
        if singleton and count > 1:
            problems.append({
                "level": "error",
                "text": "«%s» — %d копии, а формат синглтонный" % (name, count),
            })
        elif not singleton and count > 4:
            problems.append({
                "level": "error",
                "text": "«%s» — %d копий, разрешено максимум 4" % (name, count),
            })

    # --- commander ------------------------------------------------------ #
    if fmt in SINGLETON_FORMATS:
        commander_copies = sum(int(r["quantity"]) for r in commanders)
        if commander_copies == 0:
            problems.append({"level": "error", "text": "Не выбран командир"})
        elif commander_copies > 2:
            problems.append({
                "level": "error",
                "text": "Командиров %d — допустимо один, или двое с Partner" % commander_copies,
            })

        identity: set[str] = set()
        for row in commanders:
            card = row.get("card")
            if card:
                identity.update(card.get("color_identity") or "")
                type_line = (card.get("type_line") or "").lower()
                if "legendary" not in type_line:
                    problems.append({
                        "level": "error",
                        "text": "«%s» не легендарная — командиром быть не может" % row["name"],
                    })

        if commanders:
            for row in main:
                card = row.get("card")
                if not card:
                    continue
                extra = set(card.get("color_identity") or "") - identity
                if extra:
                    problems.append({
                        "level": "error",
                        "text": "«%s» вне цветовой идентичности командира (лишнее: %s)"
                                % (row["name"], "".join(sorted(extra))),
                    })

    # --- legality ------------------------------------------------------- #
    for row in rows:
        card = row.get("card")
        if not card or row["section"] == "maybe":
            continue
        status = (card.get("legalities") or {}).get(fmt)
        if status == "banned":
            problems.append({
                "level": "error",
                "text": "«%s» забанена в %s" % (row["name"], fmt),
            })
        elif status == "not_legal":
            problems.append({
                "level": "warn",
                "text": "«%s» не входит в %s" % (row["name"], fmt),
            })
        elif status == "restricted":
            problems.append({
                "level": "warn",
                "text": "«%s» ограничена в %s (не больше одной)" % (row["name"], fmt),
            })

    return problems


# --------------------------------------------------------------------------- #
# Automatic categories
# --------------------------------------------------------------------------- #

# Ordered: a card is often several of these at once, and the first match wins.
# Land goes first because a ramp land is filed under lands, not ramp. Tutors
# before ramp because a land tutor is a tutor. Removal before draw because a
# removal spell that also draws is still removal.
#
# Every slug here was checked against the tags table -- guessed names like
# "blink" or "defender" simply do not exist in Tagger.
AUTO_CATEGORIES: list[tuple[str, str | None]] = [
    ("земли", None),                       # decided by type line, not by tag
    ("туторы", "tutor"),
    ("рампа", "ramp"),
    ("удаление", "removal"),
    ("контрмагия", "counterspell"),
    ("блинк", "flicker"),
    ("возврат в руку", "removal-bounce"),
    ("жертва", "repeatable-sacrifice-outlet"),
    ("смерть-триггеры", "death-trigger"),
    ("реанимация", "reanimate"),
    ("кладбище", "castable-from-graveyard"),
    ("мельница", "mill-any"),
    ("самомельница", "mill-self"),
    ("сброс у соперника", "discard"),
    ("сброс себе", "discard-outlet"),
    ("добор", "draw"),
    ("колесо", "wheel-symmetrical"),
    ("жетоны", "repeatable-creature-tokens"),
    ("счётчики +1/+1", "repeatable-pp-counters"),
    ("сокровища", "repeatable-treasures"),
    ("экипировка", "synergy-equipment"),
    ("чары на существо", "synergy-aura"),
    ("помехи соперникам", "hate-attacker"),
    ("защита", "protection"),
    ("эвейжн", "evasion"),
    ("кража и контроль", "control-changing-effects"),
    ("доп. ходы", "extra-turn"),
    ("лайфгейн", "lifegain"),
    ("групповое добро", "group-hug"),
]

# Keyword-based categories, checked after the tags: these are printed keywords,
# not functional tags, and a wall of Defenders is a real deck direction.
AUTO_CATEGORIES_BY_KEYWORD: list[tuple[str, str]] = [
    ("дефендеры", "defender"),
    ("мгновенная скорость", "flash"),
]


def auto_categorise(deck: dict[str, Any], db: CardDB, store: DeckStore) -> int:
    """Fill in card categories from the functional tags and keywords.

    Same data the theme search uses, so "рампа" as a deck category and
    `otag:ramp` in the search mean exactly the same thing.

    Only empty categories are filled -- a category you typed yourself is your
    decision and must not be overwritten.
    """
    from .cards import _expand_tag_slugs

    expanded: list[tuple[str, set[str]]] = []
    for label, slug in AUTO_CATEGORIES:
        if slug:
            slugs = set(_expand_tag_slugs(slug))
            if slugs:
                expanded.append((label, slugs))

    assigned = 0
    for row in deck.get("cards", []):
        if (row.get("category") or "").strip():
            continue
        card = row.get("card") or db.by_name(row["name"])
        if not card:
            continue

        type_line = (card.get("type_line") or "").lower()
        chosen = None

        if "land" in type_line:
            chosen = "земли"
        else:
            oracle_id = card.get("oracle_id")
            tags: set[str] = set()
            if oracle_id:
                tags = {
                    r["slug"]
                    for r in db.conn.execute(
                        "SELECT slug FROM card_tags WHERE oracle_id = ?", (oracle_id,)
                    )
                }
            for label, slugs in expanded:
                if tags & slugs:
                    chosen = label
                    break

            if chosen is None:
                keywords = {
                    k.strip().lower()
                    for k in (card.get("keywords") or "").split(",")
                    if k.strip()
                }
                for label, keyword in AUTO_CATEGORIES_BY_KEYWORD:
                    if keyword in keywords:
                        chosen = label
                        break

            if chosen is None:
                # Last resort: the card type. Better than "без категории".
                for kind, label in (
                    ("creature", "существа"),
                    ("planeswalker", "мироходцы"),
                    ("artifact", "артефакты"),
                    ("enchantment", "чары"),
                    ("instant", "мгновенные"),
                    ("sorcery", "волшебства"),
                    ("battle", "битвы"),
                ):
                    if kind in type_line:
                        chosen = label
                        break

        if chosen:
            store.update_card(deck["id"], row["id"], category=chosen)
            assigned += 1
    return assigned


# --------------------------------------------------------------------------- #
# Rouble prices
# --------------------------------------------------------------------------- #

def refresh_prices(
    names: Iterable[str],
    store: DeckStore,
    db: CardDB,
    client: TopdeckClient | None = None,
    batch_size: int = 8,
    progress: Any = None,
) -> dict[str, Any]:
    """Fetch topdeck prices for these cards and cache them.

    Only ever on demand: each request is a polite 1.5s, so a 100-card deck is
    around twenty seconds. Cheapest and median are stored -- the cheapest tells
    you the floor, the median tells you what it really goes for.
    """
    client = client or TopdeckClient()
    matcher = OfferMatcher(db)
    wanted = []
    seen = set()
    for name in names:
        key = (name or "").strip()
        if key and key.lower() not in seen:
            seen.add(key.lower())
            wanted.append(key)

    updated = 0
    not_found = []
    skipped_disputed: dict[str, int] = {}
    for i in range(0, len(wanted), batch_size):
        batch = wanted[i : i + batch_size]
        try:
            offers = client.search(batch)
        except Exception as exc:  # noqa: BLE001
            return {
                "updated": updated,
                "not_found": not_found,
                "error": "topdeck не ответил: %s" % exc,
            }

        by_name: dict[str, list[Any]] = {}
        for offer in offers:
            for candidate in (offer.eng_name, offer.name, offer.rus_name):
                key = normalize_name(candidate or "")
                if key:
                    by_name.setdefault(key, []).append(offer)

        for name in batch:
            labelled = by_name.get(normalize_name(name)) or []
            # Verify against the seller's line: topdeck labels every hit with
            # the searched name, so caching by label priced Burgeoning at 10
            # roubles when that was an Urban Burgeoning.
            found = [
                o for o in labelled
                if matcher.classify(name, o.line)["verdict"] == MATCH
            ]
            # Offers whose price topdeck misread cannot set the floor: one
            # bogus "235 roubles" would make a 2000-rouble card look cheap.
            trusted = [o for o in found if not price_check(o.cost, o.line)["disputed"]]
            disputed = len(found) - len(trusted)
            found = trusted
            costs = sorted(o.cost for o in found if o.cost > 0)
            if not costs:
                store.store_price(name, None, None, 0)
                not_found.append(name)
                continue
            cheapest = min(found, key=lambda o: o.cost if o.cost > 0 else 10**9)
            if disputed:
                skipped_disputed[name] = disputed
            store.store_price(
                name,
                rub_min=costs[0],
                rub_median=int(statistics.median(costs)),
                offers=len(costs),
                cheapest_seller=cheapest.seller.name,
                cheapest_line=cheapest.line,
                cheapest_url=cheapest.url,
            )
            updated += 1
        if progress:
            progress("prices: %d/%d" % (min(i + batch_size, len(wanted)), len(wanted)))

    return {
        "updated": updated,
        "not_found": not_found,
        "total": len(wanted),
        "price_disputed": skipped_disputed,
    }
