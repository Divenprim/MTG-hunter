"""Client for topdeck.ru TOPTrade singles search.

The search page has no public API, but it bootstraps its Knockout viewmodel with
the full result set already encoded as a JSON string literal:

    new SinglesSearchVM(
        JSON.parse("[{\"rus_name\":...}]"),
        ...

So we do not scrape HTML rows -- we lift that JSON out and decode it. This is far
more stable than parsing the rendered table, which is built client-side anyway.

Search needs no authentication. A session cookie is only required for the parts
that act as a logged-in user (seller stock pages, private messages).
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

import requests

BASE = "https://topdeck.ru"
SEARCH_PATH = "/apps/toptrade/singles/search"

# A plain browser UA. topdeck's robots.txt does not disallow TOPTrade for '*',
# but we still stay polite: one request at a time with a delay between them.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)

VM_MARKER = "new SinglesSearchVM("
JSON_MARKER = 'JSON.parse("'
BACKSLASH = chr(92)


class TopdeckError(RuntimeError):
    pass


@dataclass
class Seller:
    """A seller. topdeck returns two shapes in the same field:
    a dict for a topdeck forum user, a bare string for an aggregated shop."""

    name: str
    kind: str  # "user" | "shop"
    id: str | None = None
    city: str | None = None
    refs: int | None = None  # forum reputation count, only for users

    @property
    def is_shop(self) -> bool:
        return self.kind == "shop"

    @property
    def profile_url(self) -> str | None:
        if self.id:
            return f"{BASE}/profile/{self.id}/"
        return None


@dataclass
class Offer:
    """One sale listing for one card, as topdeck reports it."""

    name: str  # name topdeck matched on
    eng_name: str
    rus_name: str
    qty: int
    cost: int  # rubles, per copy
    seller: Seller
    source: str  # "topdeck" or a shop domain
    url: str
    stamp: str
    line: str  # VERBATIM text the seller wrote. Always shown to the user.
    city: str | None = None
    # filled in by lineparse
    parsed: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable id for one listing, so the interface can refer back to it.

        Needed because a plan can be rebuilt after the user changes their mind
        about a card, and the offer they refused has to be recognised again in
        the same result set. topdeck gives no listing id, so the identity is
        the seller plus the exact text they wrote plus the price.
        """
        raw = "|".join([
            self.seller.kind or "", str(self.seller.id or ""), self.seller.name or "",
            (self.line or "").strip(), str(self.cost), str(self.qty),
        ])
        return hashlib.sha1(raw.encode("utf-8", "replace")).hexdigest()[:16]

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["seller"] = asdict(self.seller)
        d["key"] = self.key
        return d


def _extract_json_literals(html: str) -> list[str]:
    """Return the raw (still JS-escaped) string literals passed to JSON.parse
    inside the SinglesSearchVM bootstrap call.

    Note: do NOT cap the scan window. Result payloads routinely exceed several
    hundred KB, and truncating mid-escape corrupts the literal.
    """
    start = html.find(VM_MARKER)
    if start < 0:
        return []
    seg = html[start:]

    out: list[str] = []
    pos = 0
    while True:
        a = seg.find(JSON_MARKER, pos)
        if a < 0:
            break
        a += len(JSON_MARKER)
        j = a
        while j < len(seg):
            c = seg[j]
            if c == BACKSLASH:
                j += 2
                continue
            if c == '"':
                break
            j += 1
        out.append(seg[a:j])
        pos = j + 1
    return out


def _decode_js_string(raw: str) -> Any:
    """The payload is a JS string literal whose contents are JSON.
    Decode twice: once to unescape the literal, once to parse the JSON."""
    return json.loads(json.loads('"' + raw + '"'))


def _seller_from_raw(raw: Any, source: str, city: str | None) -> Seller:
    if isinstance(raw, dict):
        refs = raw.get("refs")
        try:
            refs = int(refs) if refs not in (None, "") else None
        except (TypeError, ValueError):
            refs = None
        return Seller(
            name=raw.get("name") or "?",
            kind="user",
            id=str(raw["id"]) if raw.get("id") else None,
            city=raw.get("city") or city,
            refs=refs,
        )
    return Seller(name=str(raw), kind="shop", city=city)


def parse_search_html(html: str) -> list[Offer]:
    """Turn a TOPTrade search response into Offer objects."""
    literals = _extract_json_literals(html)
    if not literals:
        raise TopdeckError(
            "SinglesSearchVM payload not found -- topdeck likely changed its "
            "page structure, or the response was an error/captcha page."
        )

    rows = _decode_js_string(literals[0])
    if not isinstance(rows, list):
        raise TopdeckError(f"expected a list of offers, got {type(rows).__name__}")

    offers: list[Offer] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        city = r.get("city")
        try:
            qty = int(r.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0
        try:
            cost = int(float(r.get("cost") or 0))
        except (TypeError, ValueError):
            cost = 0
        offers.append(
            Offer(
                name=r.get("name") or "",
                eng_name=r.get("eng_name") or "",
                rus_name=r.get("rus_name") or "",
                qty=qty,
                cost=cost,
                seller=_seller_from_raw(r.get("seller"), r.get("source") or "", city),
                source=r.get("source") or "",
                url=r.get("url") or "",
                stamp=r.get("stamp") or "",
                line=r.get("line") or "",
                city=city,
            )
        )
    return offers


class TopdeckClient:
    """Polite, session-reusing client. `cookies` lets you pass your own
    topdeck session for the logged-in-only features."""

    def __init__(
        self,
        cookies: dict[str, str] | None = None,
        delay: float = 1.5,
        timeout: float = 30.0,
    ) -> None:
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": USER_AGENT,
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            }
        )
        if cookies:
            self.session.cookies.update(cookies)
        self.delay = delay
        self.timeout = timeout
        self._last_request = 0.0

    def _throttle(self) -> None:
        wait = self.delay - (time.monotonic() - self._last_request)
        if wait > 0:
            time.sleep(wait)
        self._last_request = time.monotonic()

    def search_raw(self, names: Iterable[str]) -> str:
        """The `q` field is a textarea: many card names, one per line, one request."""
        query = "\n".join(n.strip() for n in names if n and n.strip())
        if not query:
            return ""
        self._throttle()
        url = f"{BASE}{SEARCH_PATH}?" + urllib.parse.urlencode({"q": query})
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.text

    def search(self, names: Iterable[str]) -> list[Offer]:
        html = self.search_raw(names)
        if not html:
            return []
        return parse_search_html(html)

    def logged_in_as(self) -> str | None:
        """Verify a supplied session cookie actually works."""
        self._throttle()
        resp = self.session.get(BASE, timeout=self.timeout)
        resp.raise_for_status()
        html = resp.text
        # IPS renders a sign-in link for guests and the member bar for members.
        if "/logout/" in html or "data-role=\"userBar\"" in html:
            marker = 'data-ipsmenu-activeitem'
            _ = marker  # best-effort; name extraction is UI-dependent
            return "authenticated"
        return None
