"""Purchase-offer message drafts, one per seller.

Written the way a person writes on a forum, not the way a shop prints a bill.
The user's instruction was explicit: greet, then list the cards by copying the
seller's own lines from their thread -- no invoice.

So a draft looks like this:

    Добрый день!

    По Вашей торговой теме интересуют:

    1 Burgeoning (NM, CN2)
    4 Lightning Bolt (NM EN CLB #187) - 145 руб

    Подскажите, всё в наличии?

Each line is the seller's own, with exactly one thing changed: the count at
its head is how many copies are wanted, not how many they have. Everything
after that first number is their text, character for character.

Why their raw line and nothing else:

  * The seller recognises their own text instantly. A normalized
    "Lightning Bolt, M10, English, LP" makes them go and look it up.
  * The line already carries the price, so restating it as "1 шт. × 2074 руб.
    = 2074 руб." adds nothing and reads like a demand.
  * Nothing is invented: no totals we computed, no prices we re-stated. If the
    seller's number is wrong, that is between them and their own line.

Why the count goes first and not at the end. It used to be appended -- "11
Burgeoning (NM, CN2) — нужно 1 шт., 2074 ₽ за шт." -- and that reads as a
correction to somebody else's line: the number a person has to act on sat
behind their own text and behind our commentary. In an order the count is
the first thing read, so it is the first character of the line.

This also means a price that lives in the listing's field rather than in its
text does not reach the message. It is in the plan on screen, where the user
reads it; the message is the seller's own words plus the count, and nothing
else.

The draft is text, and it is never sent for the user -- they paste it into
topdeck themselves, so nothing goes out under their name without them.
"""

from __future__ import annotations

import re
from typing import Any

GREETING = "Добрый день!"

TEMPLATES = {
    "ru_polite": {
        "intro": "По Вашей торговой теме интересуют:",
        "outro": "Подскажите, всё в наличии?",
    },
    "ru_short": {
        "intro": "Интересует:",
        "outro": "Актуально?",
    },
    "ru_bare": {
        # Nothing but the greeting and the lines, for people who add their own
        # wording every time.
        "intro": "",
        "outro": "",
    },
}


def _quote_line(line: str) -> str:
    """The seller's line, cleaned of the HTML some shops embed but otherwise
    untouched -- including their spacing quirks collapsed to single spaces."""
    text = re.sub(r"<[^>]*>", "", line or "")
    text = text.replace("\xa0", " ").replace("\t", " ")
    return " ".join(text.split())


# Количество, которым продавец начал свою строку: «11 Burgeoning»,
# «4 x Growth Spiral», «2шт. Sol Ring». Оно уступает место нашему -- всё
# остальное в строке остаётся как есть.
#
# Две цифры, не больше, и дальше обязательно не цифра: «1996 World Champion»
# начинается с числа, которое количеством не является, и срезать его значило
# бы заказать «1 World Champion» -- другую карту.
LEADING_COUNT = re.compile(r"^(\d{1,2})\s*(?:[xх×]\s*|шт\.?\s*)?(?=\D)")


def _item_line(item: dict[str, Any]) -> str:
    """One line of the request: the count, then the seller's own text.

    The count comes first because that is what the line is for -- how many
    copies are wanted. Their own leading count is replaced by it; the rest of
    the line is not touched at all, so they recognise their listing and read
    their own price in their own words.
    """
    offer = item.get("offer") or {}
    quoted = _quote_line(offer.get("line", ""))
    want_qty = int(item.get("quantity") or 0) or 1
    if not quoted:
        # No line from the seller: fall back to the plain name, which is all we
        # honestly have -- still with the count in front.
        return "%d %s" % (want_qty, item.get("want", ""))

    return "%d %s" % (want_qty, LEADING_COUNT.sub("", quoted, count=1))


def draft_for_lot(lot: dict[str, Any], template: str = "ru_polite") -> str:
    tpl = TEMPLATES.get(template, TEMPLATES["ru_polite"])
    blocks: list[str] = [GREETING]

    if tpl["intro"]:
        blocks.append(tpl["intro"])

    listing = [_item_line(item) for item in lot.get("items", [])]
    listing = [l for l in listing if l]
    if listing:
        blocks.append("\n".join(listing))

    if tpl["outro"]:
        blocks.append(tpl["outro"])

    # A blank line between blocks, single newlines inside the card list.
    return "\n\n".join(blocks)


def drafts_for_plan(plan: dict[str, Any], template: str = "ru_polite") -> list[dict[str, Any]]:
    out = []
    for lot in plan.get("lots", []):
        out.append(
            {
                "seller_name": lot["seller_name"],
                "seller_kind": lot["seller_kind"],
                "seller_url": lot.get("seller_url"),
                "seller_city": lot.get("seller_city"),
                "total": lot["total"],
                "message": draft_for_lot(lot, template),
                # Shops take orders on their own site, not by forum PM.
                "delivery": "site" if lot["seller_kind"] == "shop" else "pm",
            }
        )
    return out
