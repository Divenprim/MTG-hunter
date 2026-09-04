"""Preparing an order at a shop, without pretending to be you.

A private seller on topdeck gets a private message. A shop does not: it has a
site with a cart, and the order is placed there. So for a shop lot the program
prepares everything needed and stops at the point where you press "buy":

  * the list of cards in a paste-ready form;
  * a direct link to each card's page in that shop -- topdeck's singles search
    already gives us those, and a direct link beats any search;
  * a search link in that shop for anything without a direct one.

It does not fill the cart itself. Filling a cart means acting on a commercial
site under your account, which is the same line the program does not cross when
it refuses to send private messages for you. It would also break on the shop's
next redesign, and would need doing separately for every shop.

Every URL pattern here was checked against the live site. A guessed pattern that
silently searches for nothing is worse than no link at all, so a shop with no
verified pattern simply has none -- angrybottlegnome searches by POST form, and
so gets direct links only.
"""

from __future__ import annotations

import re
import urllib.parse
from typing import Any, Iterable

# domain -> what we know about it. `search` takes the card name as {q}.
SHOPS: dict[str, dict[str, Any]] = {
    "mtgsale.ru": {
        "name": "MTGSale",
        "home": "https://mtgsale.ru/",
        # <form action="/home/search-results" method="GET"> with name=Name
        "search": "https://mtgsale.ru/home/search-results?Name={q}",
    },
    "spellmarket.ru": {
        "name": "SpellMarket",
        "home": "https://spellmarket.ru/",
        # OpenCart's own search route
        "search": "https://spellmarket.ru/index.php?route=product/search&search={q}",
    },
    "angrybottlegnome.ru": {
        "name": "Angry Bottle Gnome",
        "home": "http://angrybottlegnome.ru/",
        # Its search is a POST form, so there is no link to build. The direct
        # card links from topdeck work, and that is what gets used.
        "search": None,
        "note": "поиск у магазина работает только формой, поэтому — прямые ссылки на карточки",
    },
    "mtgtrade.net": {
        "name": "MTGTrade",
        "home": "https://mtgtrade.net/",
        "search": None,
        "note": "сайт не отвечал при проверке, ссылка на поиск не подтверждена",
    },
}

DOMAIN_RE = re.compile(r"([a-z0-9][a-z0-9-]*(?:\.[a-z0-9-]+)+)")


def domain_of(text: str) -> str | None:
    """The shop domain mentioned in a seller name or a URL."""
    low = (text or "").strip().lower()
    if not low:
        return None
    if "://" in low:
        low = urllib.parse.urlparse(low).netloc or low
    if low.startswith("www."):
        low = low[4:]
    match = DOMAIN_RE.search(low)
    return match.group(1) if match else None


def shop_for(seller_name: str, url: str = "") -> dict[str, Any]:
    """What we know about the shop behind a lot.

    An unknown shop is still a shop: it gets a name and its own domain, just no
    search link.
    """
    domain = domain_of(seller_name) or domain_of(url)
    if domain and domain in SHOPS:
        known = dict(SHOPS[domain])
        known["domain"] = domain
        known["known"] = True
        return known
    return {
        "name": seller_name or domain or "магазин",
        "domain": domain,
        "home": ("https://%s/" % domain) if domain else None,
        "search": None,
        "known": False,
        "note": "магазин нам незнаком: списком и прямыми ссылками пользоваться можно, поиск не проверен",
    }


def _clean(line: str) -> str:
    text = re.sub(r"<[^>]*>", " ", line or "")
    return " ".join(text.replace("\xa0", " ").split())


def order_for_lot(lot: dict[str, Any]) -> dict[str, Any]:
    """Everything needed to place this lot as an order at its shop."""
    shop = shop_for(lot.get("seller_name", ""), lot.get("seller_url") or "")

    cards = []
    for item in lot.get("items", []) or []:
        offer = item.get("offer") or {}
        name = item.get("want") or offer.get("eng_name") or ""
        quantity = int(item.get("quantity") or 0)
        link = offer.get("url") or ""
        search = (
            shop["search"].format(q=urllib.parse.quote(name))
            if shop.get("search") and name else None
        )
        cards.append({
            "name": name,
            "quantity": quantity,
            "unit_price": item.get("unit_price"),
            "subtotal": item.get("subtotal"),
            # The seller's own line, for checking you are buying the right print.
            "line": _clean(offer.get("line", "")),
            "url": link,
            "search_url": search,
        })

    # The universal paste format: quantity then name, one per line. Every deck
    # tool and every shop that accepts a list understands this one.
    listing = "\n".join(
        "%d %s" % (c["quantity"], c["name"]) for c in cards if c["name"]
    )

    return {
        "shop": shop,
        "seller_name": lot.get("seller_name"),
        "total": lot.get("total"),
        "cards": cards,
        "list_text": listing,
        "links": [c["url"] for c in cards if c["url"]],
        "missing_links": [c["name"] for c in cards if not c["url"]],
    }


def orders_for_plan(plan: dict[str, Any]) -> list[dict[str, Any]]:
    """One order per shop lot. Private sellers are not shops and are skipped."""
    out = []
    for lot in plan.get("lots", []) or []:
        if lot.get("seller_kind") != "shop":
            continue
        out.append(order_for_lot(lot))
    return out


def order_for_names(names: Iterable[str], domain: str) -> dict[str, Any]:
    """A bare order for a shop when there is no plan -- just names.

    Used for "everything I am missing, at this shop": no direct links, because
    without offers we do not know the shop's own page for a card, but the list
    and the search links are still worth having.
    """
    shop = shop_for(domain)
    cards = []
    for name in names:
        name = (name or "").strip()
        if not name:
            continue
        cards.append({
            "name": name,
            "quantity": 1,
            "url": "",
            "search_url": (
                shop["search"].format(q=urllib.parse.quote(name))
                if shop.get("search") else None
            ),
        })
    return {
        "shop": shop,
        "cards": cards,
        "list_text": "\n".join("1 %s" % c["name"] for c in cards),
        "links": [],
        "missing_links": [c["name"] for c in cards],
    }


__all__ = ["SHOPS", "domain_of", "order_for_lot", "order_for_names",
           "orders_for_plan", "shop_for"]
