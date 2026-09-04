"""Deck import: from a URL on another site, or from pasted text.

Sources:
  * Archidekt   -- public JSON API, no auth.
  * Moxfield    -- undocumented API behind Cloudflare; may refuse us. We try,
                   and on refusal we say so clearly instead of failing silently,
                   because the user can always paste the list as text.
  * mtgtop8     -- serves a plain-text export at /mtgo?d=<id>, far more stable
                   than scraping the event page.
  * plain text  -- "4 Lightning Bolt", Arena "4 Lightning Bolt (M10) 146",
                   "SB: 2 ..." and `Sideboard` / `Commander` section markers.

Everything funnels into the same DeckList, so text import is the fallback for
any site we cannot reach.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from dataclasses import dataclass, field, asdict
from typing import Any

import requests

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


class ImportError_(RuntimeError):
    """Import failed in a way worth showing the user verbatim."""


@dataclass
class DeckEntry:
    quantity: int
    name: str
    section: str = "main"  # main | side | commander | maybe
    set_code: str | None = None
    collector_number: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DeckList:
    name: str = "Untitled deck"
    source: str = "text"
    url: str | None = None
    format: str | None = None
    entries: list[DeckEntry] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def total_cards(self) -> int:
        return sum(e.quantity for e in self.entries)

    def as_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["total_cards"] = self.total_cards
        return d


# --------------------------------------------------------------------------- #
# Text
# --------------------------------------------------------------------------- #

SECTION_MARKERS = {
    "sideboard": "side",
    "sb": "side",
    "deck": "main",
    "maindeck": "main",
    "main": "main",
    "mainboard": "main",
    "commander": "commander",
    "companion": "side",
    "maybeboard": "maybe",
    "considering": "maybe",
    # Russian headings people actually type
    "сайд": "side",
    "сайдборд": "side",
    "мейн": "main",
    "мейнборд": "main",
    "командир": "commander",
}

# "4 Lightning Bolt (M10) 146"  /  "4x Lightning Bolt"  /  "1 Sol Ring *F*"
LINE_RE = re.compile(
    r"""^\s*
    (?:(?P<sb>SB:)\s*)?
    (?P<qty>\d{1,3})\s*[xX]?\s+
    (?P<name>.+?)
    (?:\s+\((?P<set>[0-9A-Za-z]{2,6})\)\s*(?P<num>[0-9A-Za-z\-]+)?)?
    (?:\s*\*[^*]*\*)?
    \s*$""",
    re.VERBOSE,
)


def parse_text(text: str, name: str = "Pasted deck") -> DeckList:
    deck = DeckList(name=name, source="text")
    section = "main"
    saw_blank = False

    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            saw_blank = True
            continue
        if line.startswith("//") or line.startswith("#"):
            continue

        # A bare heading like "Sideboard" or "Commander (1)"
        heading = re.sub(r"[:\s]*\(?\d*\)?\s*$", "", line).strip().lower()
        if heading in SECTION_MARKERS and not re.match(r"^\s*\d", line):
            section = SECTION_MARKERS[heading]
            saw_blank = False
            continue

        m = LINE_RE.match(line)
        if not m:
            deck.warnings.append("could not read line: %s" % line[:80])
            continue

        entry_section = "side" if m.group("sb") else section
        # Arena exports separate the sideboard with a blank line and no heading.
        if saw_blank and section == "main" and deck.entries and not m.group("sb"):
            entry_section = "side"
        saw_blank = False

        deck.entries.append(
            DeckEntry(
                quantity=int(m.group("qty")),
                name=m.group("name").strip(),
                section=entry_section,
                set_code=(m.group("set") or "").lower() or None,
                collector_number=m.group("num") or None,
            )
        )
    return deck


# --------------------------------------------------------------------------- #
# Archidekt
# --------------------------------------------------------------------------- #

ARCHIDEKT_ID = re.compile(r"archidekt\.com/(?:decks|api/decks)/(\d+)")


def fetch_archidekt(url: str, session: requests.Session) -> DeckList:
    m = ARCHIDEKT_ID.search(url)
    if not m:
        raise ImportError_("not an Archidekt deck URL: %s" % url)
    deck_id = m.group(1)
    api = "https://archidekt.com/api/decks/%s/" % deck_id
    resp = session.get(api, timeout=45)
    if resp.status_code == 404:
        raise ImportError_("Archidekt deck %s not found (is it private?)" % deck_id)
    resp.raise_for_status()
    payload = resp.json()

    deck = DeckList(
        name=payload.get("name") or "Archidekt deck %s" % deck_id,
        source="archidekt",
        url="https://archidekt.com/decks/%s" % deck_id,
    )

    # Archidekt keeps section membership in per-card `categories`, and the deck's
    # own `categories` list says which of those count as maybeboard/sideboard.
    cat_flags = {}
    for c in payload.get("categories") or []:
        if isinstance(c, dict) and c.get("name"):
            cat_flags[c["name"].lower()] = c

    for item in payload.get("cards") or []:
        card = item.get("card") or {}
        oracle = card.get("oracleCard") or {}
        cname = oracle.get("name") or card.get("name")
        if not cname:
            continue
        qty = int(item.get("quantity") or 1)
        cats = [str(c).lower() for c in (item.get("categories") or [])]

        section = "main"
        for c in cats:
            if c in ("sideboard", "side"):
                section = "side"
                break
            if c in ("commander", "commanders"):
                section = "commander"
                break
            if c in ("maybeboard", "considering"):
                section = "maybe"
                break
            flag = cat_flags.get(c)
            if flag and flag.get("includedInDeck") is False:
                section = "maybe"

        edition = card.get("edition") or {}
        deck.entries.append(
            DeckEntry(
                quantity=qty,
                name=cname,
                section=section,
                set_code=(edition.get("editioncode") or "").lower() or None,
                collector_number=str(card.get("collectorNumber") or "") or None,
            )
        )

    if not deck.entries:
        deck.warnings.append("Archidekt returned no cards for this deck")
    return deck


# --------------------------------------------------------------------------- #
# Moxfield
# --------------------------------------------------------------------------- #

MOXFIELD_ID = re.compile(r"moxfield\.com/decks/([A-Za-z0-9_\-]+)")


def fetch_moxfield(url: str, session: requests.Session) -> DeckList:
    m = MOXFIELD_ID.search(url)
    if not m:
        raise ImportError_("not a Moxfield deck URL: %s" % url)
    public_id = m.group(1)

    resp = session.get(
        "https://api2.moxfield.com/v3/decks/all/%s" % public_id,
        timeout=45,
        headers={"Accept": "application/json"},
    )
    if resp.status_code in (401, 403, 429):
        raise ImportError_(
            "Moxfield refused the request (HTTP %d). Their API sits behind "
            "Cloudflare and only allows approved clients. Open the deck, use "
            "Export -> Text, and paste it into the text box instead."
            % resp.status_code
        )
    if resp.status_code == 404:
        raise ImportError_("Moxfield deck %s not found (is it private?)" % public_id)
    resp.raise_for_status()

    try:
        payload = resp.json()
    except json.JSONDecodeError as exc:
        raise ImportError_("Moxfield returned something that is not JSON: %s" % exc) from exc

    deck = DeckList(
        name=payload.get("name") or "Moxfield deck",
        source="moxfield",
        url="https://moxfield.com/decks/%s" % public_id,
        format=payload.get("format"),
    )

    boards = payload.get("boards") or {}
    board_sections = {
        "mainboard": "main",
        "sideboard": "side",
        "commanders": "commander",
        "maybeboard": "maybe",
        "companions": "side",
    }
    for board_name, section in board_sections.items():
        board = boards.get(board_name) or {}
        for item in (board.get("cards") or {}).values():
            card = item.get("card") or {}
            cname = card.get("name")
            if not cname:
                continue
            deck.entries.append(
                DeckEntry(
                    quantity=int(item.get("quantity") or 1),
                    name=cname,
                    section=section,
                    set_code=(card.get("set") or "").lower() or None,
                    collector_number=str(card.get("cn") or "") or None,
                )
            )
    if not deck.entries:
        deck.warnings.append("Moxfield returned no cards for this deck")
    return deck


# --------------------------------------------------------------------------- #
# mtgtop8
# --------------------------------------------------------------------------- #

MTGTOP8_DECK = re.compile(r"mtgtop8\.com/(?:event|mtgo|deck)\?(?:.*?&)?d=(\d+)", re.I)


def fetch_mtgtop8(url: str, session: requests.Session) -> DeckList:
    m = MTGTOP8_DECK.search(url)
    if not m:
        raise ImportError_(
            "no deck id in that mtgtop8 URL -- open a single deck (the link "
            "contains d=<number>), not the event summary"
        )
    deck_id = m.group(1)
    resp = session.get("https://mtgtop8.com/mtgo?d=%s" % deck_id, timeout=45)
    resp.raise_for_status()
    body = resp.text
    if not body.strip():
        raise ImportError_("mtgtop8 returned an empty decklist for d=%s" % deck_id)

    deck = parse_text(body, name="mtgtop8 deck %s" % deck_id)
    deck.source = "mtgtop8"
    deck.url = "https://mtgtop8.com/event?d=%s" % deck_id
    return deck


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #

def import_from_url(url: str) -> DeckList:
    url = (url or "").strip()
    if not url:
        raise ImportError_("no URL given")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url

    host = (urllib.parse.urlparse(url).hostname or "").lower()
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    if "archidekt.com" in host:
        return fetch_archidekt(url, session)
    if "moxfield.com" in host:
        return fetch_moxfield(url, session)
    if "mtgtop8.com" in host:
        return fetch_mtgtop8(url, session)
    if "topdeck.ru" in host:
        raise ImportError_(
            "topdeck decklists are republished from mtgtop8 -- open the deck on "
            "mtgtop8 and paste that link, or paste the list as text"
        )
    raise ImportError_(
        "unsupported site: %s. Supported: Archidekt, Moxfield, mtgtop8. "
        "Anything else: paste the decklist as text." % (host or url)
    )
