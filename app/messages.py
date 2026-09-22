"""Purchase-offer message drafts, one per seller.

Written the way a person writes on a forum, not the way a shop prints a bill.
The user's instruction was explicit: greet, then list the cards by copying the
seller's own lines from their thread -- no invoice.

So a draft looks like this:

    Добрый день!

    По Вашей торговой теме интересуют:

    11 Burgeoning (NM, CN2)
    4 Lightning Bolt (NM EN CLB #187) - 145 руб

    Подскажите, всё в наличии?

Why the seller's raw line and nothing else:

  * The seller recognises their own text instantly. A normalized
    "Lightning Bolt, M10, English, LP" makes them go and look it up.
  * The line already carries the count and usually the price, so restating them
    as "1 шт. × 2074 руб. = 2074 руб." adds nothing and reads like a demand.
  * Nothing is invented: no totals we computed, no prices we re-stated. If the
    seller's number is wrong, that is between them and their own line.

The one exception is a line with no price in it at all. Those exist: the price
lived in the listing's own field, not in the text, so the plan shows it and the
draft used to show nothing -- money simply disappeared between the screen and
the message. Then the price from that same listing is added once, as their
number and in their terms, with no arithmetic and no total.

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


# Признак того, что цена в строке уже есть: любое число с рублёвой пометкой.
# Нарочно узко -- по пометке, а не по «есть цифры»: в строках полно номеров
# карт (#187), кодов сетов (CN2) и годов, и принимать их за цену значило бы
# промолчать там, где цену как раз надо дописать.
HAS_PRICE = re.compile(
    r"\d+\s*(?:руб|рубл|р\b|р\.|₽|rub)", re.IGNORECASE | re.UNICODE
)


def _item_line(item: dict[str, Any]) -> str:
    """One line of the request: the seller's own text, as written.

    Two things may be added, both because the seller otherwise cannot know
    them from their own line:

      * the count, when fewer copies are wanted than the listing offers --
        "11 Burgeoning" does not say that one is enough;
      * the price, and only when their line has none in it. That happens when
        the price lived in the listing's field rather than in its text: the
        plan shows the number, and without this the draft showed nothing at
        all. It is still their price, stated their way, with no total and no
        multiplication.
    """
    offer = item.get("offer") or {}
    quoted = _quote_line(offer.get("line", ""))
    if not quoted:
        # No line from the seller: fall back to the plain name, which is all we
        # honestly have.
        return "%s — %d шт." % (item.get("want", ""), item.get("quantity", 1))

    want_qty = int(item.get("quantity") or 0)
    # Сколько у продавца -- по нашим сведениям, а не по числу topdeck:
    # строку "4 x Growth Spiral" topdeck считает за одну штуку.
    have_qty = int(offer.get("stock") or offer.get("qty") or 0)
    notes = []
    if want_qty and have_qty and want_qty < have_qty:
        notes.append("нужно %d шт." % want_qty)

    price = int(item.get("unit_price") or 0)
    if price and not HAS_PRICE.search(quoted):
        notes.append("%d ₽ за шт." % price)

    # Одна вставка через тире, а не две: «строка — нужно 1 шт., 2074 ₽ за шт.»
    if notes:
        quoted = "%s — %s" % (quoted, ", ".join(notes))
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
