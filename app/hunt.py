"""The hunt: deck + collection -> missing cards -> offers -> a buying plan.

Two ideas carry this module.

1. We never overwrite the seller's own words. topdeck's `line` is shown as-is
   next to whatever we managed to parse out of it, so the user can always see
   what they are actually buying and catch our mistakes.

2. Buying 8 cards from one seller beats buying them from 8 sellers -- one
   shipment, one conversation. So the plan is built by greedy seller coverage,
   not by picking the globally cheapest copy of each card independently.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

from .cards import CardDB, normalize_name
from .lineparse import ParsedLine, SetIndex, parse_line
from .offermatch import MATCH, OTHER, OfferMatcher, price_check
from .topdeck import Offer, TopdeckClient

CONDITION_ORDER = ["DMG", "HP", "MP", "LP", "EX", "NM", "M"]


def condition_rank(grade: str | None) -> int:
    if not grade:
        return -1
    try:
        return CONDITION_ORDER.index(grade)
    except ValueError:
        return -1


@dataclass
class Want:
    """A card the user needs, and how many."""

    name: str
    quantity: int
    set_code: str | None = None
    section: str = "main"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Filters:
    """User preferences. Nothing here silently drops data -- every rejected
    offer keeps a reason, so the UI can explain an empty result."""

    languages: list[str] = field(default_factory=list)  # empty = any
    min_condition: str | None = None
    max_price: int | None = None  # rubles per copy
    min_seller_refs: int | None = None
    include_shops: bool = True
    include_users: bool = True
    require_stated_language: bool = False
    require_stated_condition: bool = False
    exclude_proxy: bool = True
    cities: list[str] = field(default_factory=list)


"""How sure we are that this listing is the card the user asked for.

Necessary because a seller who writes nothing ("4 Lightning Bolt") or bundles
printings ("(разные)", "[2 рус, 1 eng]") passes almost any filter by default --
and since such lots are often the cheapest, a naive plan puts them first. Rank
by certainty before price so a guessed match never outranks a stated one.
"""
CERTAINTY_ORDER = {"exact": 0, "partial": 1, "ambiguous": 2}


def assess(parsed: ParsedLine, filters: "Filters") -> tuple[str, list[str]]:
    if parsed.mixed or len(parsed.languages) > 1:
        return "ambiguous", ["seller bundles different printings or languages"]

    gaps: list[str] = []
    if not parsed.set_code:
        gaps.append("set not stated")
    if filters.languages and not parsed.language:
        gaps.append("language not stated")
    if filters.min_condition and not parsed.condition:
        gaps.append("condition not stated")
    return ("partial" if gaps else "exact"), gaps


@dataclass
class Candidate:
    """One offer, parsed and judged against the filters."""

    offer: Offer
    parsed: ParsedLine
    want: str
    printing: dict[str, Any] | None = None
    rejected: str | None = None
    certainty: str = "partial"
    gaps: list[str] = field(default_factory=list)
    unmatched: bool = False
    # Why this offer's price cannot be trusted, when topdeck's number and the
    # seller's own line disagree. Kept apart from `rejected` because the filter
    # pass recomputes that one, and used to wipe this verdict with it -- which
    # is how a card the seller priced at 900 kept showing up as 13 roubles.
    price_dispute: str | None = None
    # Set when the user says "not this one" / "not this card at all". Separate
    # from `rejected` (a filter verdict) so a refusal can be taken back without
    # losing the filter's reason, and so the plan can be rebuilt from the same
    # offers with no new topdeck requests.
    refused: str | None = None

    @property
    def unit_price(self) -> int:
        return self.offer.cost

    @property
    def certainty_rank(self) -> int:
        return CERTAINTY_ORDER.get(self.certainty, 1)

    def as_dict(self) -> dict[str, Any]:
        d = self.offer.as_dict()
        d["parsed"] = self.parsed.as_dict()
        d["want"] = self.want
        d["rejected"] = self.rejected
        d["certainty"] = self.certainty
        d["gaps"] = self.gaps
        d["unmatched"] = self.unmatched
        d["refused"] = self.refused
        d["price_dispute"] = self.price_dispute
        d["printing"] = (
            {
                "set_code": self.printing.get("set_code"),
                "set_name": self.printing.get("set_name"),
                "collector_number": self.printing.get("collector_number"),
                "image_small": self.printing.get("image_small"),
                "image_normal": self.printing.get("image_normal"),
                "prices": self.printing.get("prices"),
                "rarity": self.printing.get("rarity"),
            }
            if self.printing
            else None
        )
        return d


def compute_wants(
    entries: Iterable[Any],
    collection: dict[str, int] | None = None,
    sections: Iterable[str] = ("main", "side", "commander"),
) -> list[Want]:
    """Deck minus collection. `collection` maps lowercased card name -> count."""
    collection = {k.lower(): v for k, v in (collection or {}).items()}
    needed: dict[str, Want] = {}
    wanted_sections = set(sections)

    for e in entries:
        section = getattr(e, "section", "main")
        if section not in wanted_sections:
            continue
        name = getattr(e, "name", "").strip()
        if not name:
            continue
        qty = int(getattr(e, "quantity", 1) or 1)
        key = name.lower()
        if key in needed:
            needed[key].quantity += qty
        else:
            needed[key] = Want(
                name=name, quantity=qty, set_code=getattr(e, "set_code", None), section=section
            )

    out: list[Want] = []
    for key, want in needed.items():
        owned = collection.get(key, 0)
        short = want.quantity - owned
        if short > 0:
            want.quantity = short
            out.append(want)
    return out


def judge(cand: Candidate, filters: Filters) -> str | None:
    """Return a rejection reason, or None if the offer passes."""
    p, o = cand.parsed, cand.offer

    if o.seller.is_shop and not filters.include_shops:
        return "shops excluded"
    if not o.seller.is_shop and not filters.include_users:
        return "private sellers excluded"

    if filters.exclude_proxy and "proxy" in p.treatments:
        return "proxy"

    if filters.max_price is not None and o.cost > filters.max_price:
        return "over the price cap (%d > %d rub)" % (o.cost, filters.max_price)

    if filters.languages:
        if p.language:
            if p.language not in filters.languages:
                return "language %s not wanted" % p.language
        elif p.languages:
            if not set(p.languages) & set(filters.languages):
                return "languages %s not wanted" % ",".join(p.languages)
        elif filters.require_stated_language:
            return "language not stated"

    if filters.min_condition:
        floor = condition_rank(filters.min_condition)
        if p.condition:
            if condition_rank(p.condition) < floor:
                return "condition %s below %s" % (p.condition, filters.min_condition)
        elif filters.require_stated_condition:
            return "condition not stated"

    if filters.min_seller_refs is not None and not o.seller.is_shop:
        if (o.seller.refs or 0) < filters.min_seller_refs:
            return "seller has %d refs (< %d)" % (o.seller.refs or 0, filters.min_seller_refs)

    if filters.cities:
        city = (o.seller.city or o.city or "").lower()
        if city and not any(c.lower() in city for c in filters.cities):
            return "city %s not wanted" % city

    return None


def resolve_printing(parsed: ParsedLine, offer: Offer, db: CardDB) -> dict[str, Any] | None:
    """Best effort: pin the offer to an actual printing so we can show the
    right image and a reference price."""
    if parsed.set_code and parsed.collector_number:
        hit = db.by_set_number(parsed.set_code, parsed.collector_number)
        if hit:
            return hit
    card = db.by_name(offer.eng_name or offer.name)
    if card and parsed.set_code:
        for pr in db.printings(card.get("oracle_id") or ""):
            if pr.get("set_code") == parsed.set_code:
                return pr
    return card


class Hunter:
    def __init__(
        self,
        db: CardDB,
        client: TopdeckClient | None = None,
        set_index: SetIndex | None = None,
    ) -> None:
        self.db = db
        self.client = client or TopdeckClient()
        self.set_index = set_index or SetIndex.load()

    def _alias_map(self, wants: list[Want]) -> dict[str, Want]:
        """Map every name a wanted card may be listed under -> that want.

        Built from the card_names index, so a want for "Brazen Borrower" also
        matches a listing that says "Petty Theft", and "Удар Молнии" matches
        "Lightning Bolt". Exact matching only: substring matching once let a
        listing for "Tiamat's Fanatics" be sold to us as "Tiamat".
        """
        alias_to_want: dict[str, Want] = {}
        for w in wants:
            aliases = {normalize_name(w.name)}
            card = self.db.by_name(w.name)
            if card and card.get("oracle_id"):
                aliases.update(self.db.aliases_for_oracle(card["oracle_id"]))
            for alias in aliases:
                if alias:
                    alias_to_want.setdefault(alias, w)
        return alias_to_want

    def gather(self, wants: list[Want], batch_size: int = 8) -> list[Candidate]:
        """Search topdeck for every wanted card and parse each listing."""
        alias_to_want = self._alias_map(wants)
        matcher = OfferMatcher(self.db)
        candidates: list[Candidate] = []
        names = [w.name for w in wants]

        for i in range(0, len(names), batch_size):
            batch = names[i : i + batch_size]
            offers = self.client.search(batch)
            for o in offers:
                parsed = parse_line(
                    o.line, self.set_index, o.eng_name, o.rus_name, [o.name]
                )
                want = None
                for raw in (o.eng_name, o.rus_name, o.name):
                    if not raw:
                        continue
                    want = alias_to_want.get(normalize_name(raw))
                    if want is not None:
                        break

                cand = Candidate(
                    offer=o,
                    parsed=parsed,
                    want=want.name if want else (o.eng_name or o.name),
                )

                if want is None:
                    cand.rejected = "другая карта: topdeck отдал %r" % (
                        o.eng_name or o.name
                    )
                    cand.unmatched = True
                else:
                    # `eng_name` is the name we ASKED FOR, not the card the
                    # seller lists -- topdeck answers "Burgeoning" with
                    # "Urban Burgeoning" at a tenth of the price. Verify
                    # against the seller's own line before spending money.
                    verdict = matcher.classify(want.name, o.line)
                    if verdict["verdict"] == OTHER:
                        cand.rejected = verdict["reason"]
                        cand.unmatched = True
                    elif verdict["verdict"] != MATCH:
                        cand.rejected = verdict["reason"]
                        cand.unmatched = True
                    else:
                        # A price topdeck misread must not win the cheapest
                        # slot; the offer stays visible with the reason.
                        price = price_check(o.cost, o.line)
                        if price["disputed"]:
                            cand.price_dispute = price["reason"]
                            cand.rejected = price["reason"]
                candidates.append(cand)
        return candidates

    def apply_filters(self, candidates: list[Candidate], filters: Filters) -> list[Candidate]:
        for c in candidates:
            # An offer for a different card stays rejected whatever the filters
            # say -- do not let judge() overwrite that verdict.
            if not c.unmatched:
                # A disputed price survives the filter pass: it is not a
                # preference, it is a number we cannot trust.
                c.rejected = judge(c, filters) or c.price_dispute
            c.certainty, c.gaps = assess(c.parsed, filters)
        return candidates

    def resolve(self, candidates: list[Candidate]) -> list[Candidate]:
        cache: dict[str, dict[str, Any] | None] = {}
        for c in candidates:
            key = "%s|%s|%s" % (
                c.offer.eng_name,
                c.parsed.set_code or "",
                c.parsed.collector_number or "",
            )
            if key not in cache:
                cache[key] = resolve_printing(c.parsed, c.offer, self.db)
            c.printing = cache[key]
        return candidates


# --------------------------------------------------------------------------- #
# Buying plan
# --------------------------------------------------------------------------- #

@dataclass
class PlanItem:
    want: str
    quantity: int
    unit_price: int
    candidate: Candidate

    def as_dict(self) -> dict[str, Any]:
        return {
            "want": self.want,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "subtotal": self.quantity * self.unit_price,
            "offer": self.candidate.as_dict(),
        }


@dataclass
class SellerLot:
    seller_name: str
    seller_kind: str
    seller_city: str | None
    seller_refs: int | None
    seller_url: str | None
    items: list[PlanItem] = field(default_factory=list)

    @property
    def total(self) -> int:
        return sum(i.quantity * i.unit_price for i in self.items)

    @property
    def distinct_cards(self) -> int:
        return len(self.items)

    def as_dict(self) -> dict[str, Any]:
        return {
            "seller_name": self.seller_name,
            "seller_kind": self.seller_kind,
            "seller_city": self.seller_city,
            "seller_refs": self.seller_refs,
            "seller_url": self.seller_url,
            "items": [i.as_dict() for i in self.items],
            "total": self.total,
            "distinct_cards": self.distinct_cards,
            "total_copies": sum(i.quantity for i in self.items),
        }


def seller_key_of(cand: "Candidate") -> str:
    """Seller identity: shops collapse by domain, users by profile id."""
    s = cand.offer.seller
    return "shop:%s" % s.name if s.is_shop else "user:%s" % (s.id or s.name)


@dataclass
class Assignment:
    """One decision: this many copies of this card, from this listing."""

    want_key: str
    candidate: "Candidate"
    quantity: int
    pinned: bool = False
    # Every listing for this card, so the improvement pass has somewhere to look.
    alternatives: list = field(default_factory=list)


def _lots_from(assignments: list[Assignment],
               name_of: dict[str, str]) -> list[SellerLot]:
    grouped: dict[str, list[Assignment]] = defaultdict(list)
    for a in assignments:
        if a.quantity > 0:
            grouped[seller_key_of(a.candidate)].append(a)

    lots: list[SellerLot] = []
    for _, group in grouped.items():
        sample = group[0].candidate.offer.seller
        lots.append(
            SellerLot(
                seller_name=sample.name,
                seller_kind=sample.kind,
                seller_city=sample.city,
                seller_refs=sample.refs,
                seller_url=sample.profile_url,
                items=[
                    PlanItem(
                        want=name_of.get(a.want_key, a.candidate.want),
                        quantity=a.quantity,
                        unit_price=a.candidate.unit_price,
                        candidate=a.candidate,
                    )
                    for a in group
                ],
            )
        )
    return lots


def _improve(assignments: list[Assignment]) -> list[dict[str, Any]]:
    """Move cards to sellers already in the plan when they are cheaper there.

    This is the fix for a plan that was simply wrong. The greedy pass assigns a
    card to the first seller who covers it, and never looks back -- so a Dark
    Ritual could sit in a shop's lot at 500 roubles while Animek, already in the
    plan for other cards, was selling it at 400. That is not a trade-off between
    price and postage: the same postage, less money. Nothing justified it except
    the order in which the greedy loop happened to run.

    So after any strategy, every unpinned assignment is offered to the cheapest
    listing among the sellers the plan already involves. Certainty is never
    traded away for price -- a listing that states its set and condition is not
    replaced by a vaguer cheaper one -- and a seller left with nothing simply
    drops out, which makes the plan cheaper AND shorter.
    """
    moves: list[dict[str, Any]] = []

    for _ in range(40):                      # converges in a couple of rounds
        used: dict[int, int] = defaultdict(int)
        for a in assignments:
            used[id(a.candidate)] += a.quantity
        in_plan = {seller_key_of(a.candidate) for a in assignments if a.quantity > 0}

        # Every listing that a seller already in the plan could supply.
        pool: dict[str, list[Candidate]] = defaultdict(list)
        for a in assignments:
            for alt in a.alternatives:
                if seller_key_of(alt) in in_plan:
                    pool[a.want_key].append(alt)

        changed = False
        for a in list(assignments):
            if a.pinned or a.quantity <= 0:
                continue
            here = a.candidate
            better = None
            for alt in pool.get(a.want_key, []):
                if alt is here:
                    continue
                free = alt.offer.qty - used[id(alt)]
                if free <= 0:
                    continue
                if alt.unit_price >= here.unit_price:
                    continue
                # Certainty first: this is the rule the whole program follows.
                if alt.certainty_rank > here.certainty_rank:
                    continue
                if better is None or (alt.unit_price, alt.certainty_rank) < (
                        better.unit_price, better.certainty_rank):
                    better = alt
            if better is None:
                continue

            take = min(a.quantity, better.offer.qty - used[id(better)])
            if take <= 0:
                continue

            moves.append({
                "want": a.candidate.want,
                "quantity": take,
                "from_seller": here.offer.seller.name,
                "from_price": here.unit_price,
                "to_seller": better.offer.seller.name,
                "to_price": better.unit_price,
                "saved": (here.unit_price - better.unit_price) * take,
            })
            used[id(here)] -= take
            used[id(better)] += take
            a.quantity -= take
            moved = Assignment(a.want_key, better, take)
            moved.alternatives = a.alternatives
            assignments.append(moved)
            if a.quantity <= 0:
                assignments.remove(a)
            changed = True

        if not changed:
            break

    # Merge assignments that ended up on the same listing.
    merged: dict[int, Assignment] = {}
    for a in assignments:
        if a.quantity <= 0:
            continue
        seen = merged.get(id(a.candidate))
        if seen is None:
            merged[id(a.candidate)] = a
        else:
            seen.quantity += a.quantity
    assignments[:] = list(merged.values())
    return moves


def build_plan(
    wants: list[Want],
    candidates: list[Candidate],
    prefer: str = "sellers",
    pins: dict[str, str] | None = None,
    prefer_seller: str | None = None,
) -> dict[str, Any]:
    """Work out what to buy where.

    prefer="sellers": repeatedly take the seller who can cover the most still-
    missing copies (cheapest as the tie-break). Fewer sellers means fewer
    shipments and fewer conversations, which usually beats saving 20 rub a card.

    prefer="price": take the cheapest copy of each card regardless of seller.

    `pins` maps a card name to an offer key the user chose by hand; that choice
    is honoured exactly and never second-guessed.

    `prefer_seller` gives one seller first refusal on everything they stock --
    "I would rather buy it all in this one shop".

    Whatever the strategy, the plan then goes through `_improve`, which stops it
    paying a shop 500 for a card that a seller already in the plan has at 400.
    """
    remaining = {w.name.lower(): w.quantity for w in wants}
    name_of = {w.name.lower(): w.name for w in wants}
    usable = [
        c for c in candidates
        if not c.rejected and not c.refused and c.offer.qty > 0
    ]

    # Everything anyone offers for each wanted card, cheapest-certain first.
    per_card: dict[str, list[Candidate]] = defaultdict(list)
    for c in usable:
        key = c.want.lower()
        if key in remaining:
            per_card[key].append(c)
    for key in per_card:
        per_card[key].sort(key=lambda c: (c.certainty_rank, c.unit_price))

    assignments: list[Assignment] = []
    used: dict[int, int] = defaultdict(int)

    def take_from(cand: Candidate, key: str, pinned: bool = False) -> int:
        free = cand.offer.qty - used[id(cand)]
        take = min(remaining.get(key, 0), free)
        if take <= 0:
            return 0
        remaining[key] -= take
        used[id(cand)] += take
        a = Assignment(key, cand, take, pinned=pinned)
        a.alternatives = per_card.get(key, [])
        assignments.append(a)
        return take

    # 1. What the user pinned by hand wins outright.
    pinned_keys: dict[str, str] = {
        (k or "").strip().lower(): v for k, v in (pins or {}).items() if v
    }
    for key, offer_key in pinned_keys.items():
        for cand in per_card.get(key, []):
            if cand.offer.key == offer_key:
                take_from(cand, key, pinned=True)
                break

    # 2. A seller the user wants to buy from gets first refusal. Their cards are
    #    pinned: "buy it all here" is an instruction, and the improvement pass
    #    would otherwise dismantle it card by card to save money the user has
    #    already said they do not want saved.
    if prefer_seller:
        for key, offers in per_card.items():
            if remaining.get(key, 0) <= 0:
                continue
            mine = [c for c in offers if seller_key_of(c) == prefer_seller]
            for cand in mine:
                if remaining.get(key, 0) <= 0:
                    break
                take_from(cand, key, pinned=True)

    # 3. The strategy fills whatever is still missing.
    if prefer == "price":
        for key, offers in per_card.items():
            # Price first (what the user asked for), certainty as the tie-break.
            for cand in sorted(offers, key=lambda c: (c.unit_price, c.certainty_rank)):
                if remaining.get(key, 0) <= 0:
                    break
                take_from(cand, key)
    else:
        by_seller: dict[str, list[Candidate]] = defaultdict(list)
        for c in usable:
            by_seller[seller_key_of(c)].append(c)

        while any(v > 0 for v in remaining.values()):
            best_key = None
            best_score: tuple[int, int, int] = (0, 0, 0)
            best_plan: list[tuple[Candidate, str, int]] = []

            for skey, cands in by_seller.items():
                # A seller often lists the same card several times (different
                # printings), so all of their listings count towards coverage.
                mine: dict[str, list[Candidate]] = defaultdict(list)
                for c in cands:
                    key = c.want.lower()
                    if remaining.get(key, 0) > 0:
                        mine[key].append(c)
                if not mine:
                    continue

                picks: list[tuple[Candidate, str, int]] = []
                copies = cost = uncertain = 0
                for key, offers in mine.items():
                    # Certainty before price: a stated set/language/condition
                    # beats a cheaper listing that leaves us guessing.
                    offers.sort(key=lambda c: (c.certainty_rank, c.unit_price))
                    need = remaining[key]
                    for c in offers:
                        if need <= 0:
                            break
                        free = c.offer.qty - used[id(c)]
                        take = min(need, free)
                        if take <= 0:
                            continue
                        need -= take
                        picks.append((c, key, take))
                        copies += take
                        cost += take * c.unit_price
                        if c.certainty != "exact":
                            uncertain += 1
                if not picks:
                    continue
                score = (copies, -uncertain, -cost)
                if score > best_score:
                    best_score, best_key, best_plan = score, skey, picks

            if best_key is None:
                break
            for cand, key, _take in best_plan:
                take_from(cand, key)
            del by_seller[best_key]

    # 4. The pass that makes the plan honest about its own numbers.
    moves = _improve(assignments)

    lots = _lots_from(assignments, name_of)
    lots.sort(key=lambda lot: (-lot.distinct_cards, lot.total))

    unfilled = [
        {"name": name_of.get(k, k), "still_missing": v}
        for k, v in remaining.items() if v > 0
    ]

    # Who else sells each wanted card, so the interface can offer a choice
    # instead of presenting one answer as if it were the only one.
    chosen: dict[str, set[str]] = defaultdict(set)
    for a in assignments:
        chosen[a.want_key].add(a.candidate.offer.key)
    in_plan = {seller_key_of(a.candidate) for a in assignments}

    alternatives: dict[str, list[dict[str, Any]]] = {}
    for key, offers in per_card.items():
        rows = []
        for c in sorted(offers, key=lambda c: (c.unit_price, c.certainty_rank)):
            rows.append({
                "key": c.offer.key,
                "seller_name": c.offer.seller.name,
                "seller_kind": c.offer.seller.kind,
                "seller_city": c.offer.seller.city,
                "price": c.unit_price,
                "qty": c.offer.qty,
                "certainty": c.certainty,
                "line": c.offer.line,
                "set_code": c.parsed.set_code,
                "language": c.parsed.language,
                "condition": c.parsed.condition,
                "in_plan": seller_key_of(c) in in_plan,
                "chosen": c.offer.key in chosen.get(key, set()),
                "pinned": pinned_keys.get(key) == c.offer.key,
            })
        alternatives[name_of.get(key, key)] = rows

    # Who could take the whole order, for "I would rather buy it all in one place".
    coverage: list[dict[str, Any]] = []
    seller_names: dict[str, Any] = {}
    covers: dict[str, set[str]] = defaultdict(set)
    for c in usable:
        key = c.want.lower()
        if key not in remaining:
            continue
        skey = seller_key_of(c)
        covers[skey].add(key)
        seller_names.setdefault(skey, c.offer.seller)
    for skey, keys in covers.items():
        seller = seller_names[skey]
        coverage.append({
            "key": skey,
            "name": seller.name,
            "kind": seller.kind,
            "cards": len(keys),
            "in_plan": skey in in_plan,
        })
    coverage.sort(key=lambda x: (-x["cards"], x["name"]))

    return {
        "lots": [lot.as_dict() for lot in lots],
        "unfilled": unfilled,
        "total": sum(lot.total for lot in lots),
        "sellers": len(lots),
        "strategy": prefer,
        "moves": moves,
        "saved": sum(m["saved"] for m in moves),
        "alternatives": alternatives,
        "coverage": coverage[:25],
        "prefer_seller": prefer_seller,
        "pins": {name_of.get(k, k): v for k, v in pinned_keys.items()},
    }
