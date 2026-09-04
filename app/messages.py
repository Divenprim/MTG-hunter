"""Purchase-offer message drafts, one per seller.

Written the way a person writes on a forum, not the way a shop prints a bill.
The user's instruction was explicit: greet, then list the cards by copying the
seller's own lines from their thread -- no invoice.

So a draft looks like this:

    Здравствуйте!

    Интересует из вашей продажи:

    11 Burgeoning (NM, CN2)
    4 Lightning Bolt (NM EN CLB #187) - 145 руб

    Актуально?

Why the seller's raw line and nothing else:

  * The seller recognises their own text instantly. A normalized
    "Lightning Bolt, M10, English, LP" makes them go and look it up.
  * The line already carries the count and usually the price, so restating them
    as "1 шт. × 2074 руб. = 2074 руб." adds nothing and reads like a demand.
  * Nothing is invented: no totals we computed, no prices we re-stated. If the
    seller's number is wrong, that is between them and their own line.

The draft is text, and it is never sent for the user -- they paste it into
topdeck themselves, so nothing goes out under their name without them.
"""

from __future__ import annotations

import re
from typing import Any

GREETING = "Здравствуйте!"

TEMPLATES = {
    "ru_polite": {
        "intro": "Интересует из вашей продажи:",
        "outro": "Ещё актуально? Если да, подскажите, как удобнее оплатить и получить. Спасибо!",
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


def _item_line(item: dict[str, Any]) -> str:
    """One line of the request: the seller's own text, as written.

    The only thing added is a count, and only when the user is taking fewer
    copies than the listing offers -- otherwise the seller cannot know that
    "11 Burgeoning" means one copy is wanted.
    """
    offer = item.get("offer") or {}
    quoted = _quote_line(offer.get("line", ""))
    if not quoted:
        # No line from the seller: fall back to the plain name, which is all we
        # honestly have.
        return "%s — %d шт." % (item.get("want", ""), item.get("quantity", 1))

    want_qty = int(item.get("quantity") or 0)
    have_qty = int(offer.get("qty") or 0)
    if want_qty and have_qty and want_qty < have_qty:
        return "%s — нужно %d шт." % (quoted, want_qty)
    return quoted


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
