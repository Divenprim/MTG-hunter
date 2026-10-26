"""Deck import: from a URL on another site, or from pasted text.

Sources:
  * Archidekt   -- public JSON API, no auth.
  * Deckstats   -- undocumented but stable JSON export (api.php), no auth.
  * Moxfield    -- undocumented API behind Cloudflare; may refuse us. We try,
                   and on refusal we say so clearly instead of failing silently,
                   because the user can always paste the list as text.
  * mtgtop8     -- serves a plain-text export at /mtgo?d=<id>, far more stable
                   than scraping the event page.
  * plain text  -- "4 Lightning Bolt", Arena "4 Lightning Bolt (M10) 146",
                   "SB: 2 ..." and `Sideboard` / `Commander` section markers.

Everything funnels into the same DeckList, so text import is the fallback for
any site we cannot reach. Each online site is one DeckSource (see below): to
teach the program a new site, add a subclass and list it in SOURCES -- the
dispatch never grows another `if host == ...` branch.
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
# Deck sources
# --------------------------------------------------------------------------- #
#
# Each online site is one DeckSource. A source answers two questions: is this
# URL mine (`deck_id` returns the site's deck id, or None), and how do I turn
# that id into a DeckList (`fetch`). `import_from_url` asks each registered
# source in turn, so adding a site is one subclass plus one line in SOURCES.
#
# A clean refusal -- a private deck, a 403/404/429, an empty answer -- is an
# ImportError_ whose text is written for the user to read. A transient network
# error is left as the underlying requests exception: the caller decides whether
# that is fatal (the web handler) or just a deck to skip (the sampler).


class DeckSource:
    """One site a deck can be imported from."""

    id: str = ""
    label: str = ""

    def deck_id(self, url: str) -> str | None:
        """The site's deck id in this URL, or None if the URL isn't ours."""
        raise NotImplementedError

    def fetch(self, deck_id: str, session: requests.Session) -> DeckList:
        """Fetch and normalise one deck into a DeckList."""
        raise NotImplementedError


class ArchidektSource(DeckSource):
    """Archidekt -- public JSON API, no auth."""

    id = "archidekt"
    label = "Archidekt"
    _ID = re.compile(r"archidekt\.com/(?:decks|api/decks)/(\d+)")

    def deck_id(self, url: str) -> str | None:
        m = self._ID.search(url or "")
        return m.group(1) if m else None

    def fetch(self, deck_id: str, session: requests.Session) -> DeckList:
        api = "https://archidekt.com/api/decks/%s/" % deck_id
        resp = session.get(api, timeout=45)
        if resp.status_code == 404:
            raise ImportError_(
                "Archidekt deck %s not found (is it private?)" % deck_id)
        if resp.status_code == 429:
            raise ImportError_(
                "Archidekt is asking us to wait (429). Try again shortly.")
        resp.raise_for_status()
        payload = resp.json()

        deck = DeckList(
            name=payload.get("name") or "Archidekt deck %s" % deck_id,
            source="archidekt",
            url="https://archidekt.com/decks/%s" % deck_id,
        )

        # Archidekt keeps section membership in per-card `categories`, and the
        # deck's own `categories` list says which of those count as maybeboard.
        cat_flags = {
            c["name"].lower(): c
            for c in (payload.get("categories") or [])
            if isinstance(c, dict) and c.get("name")
        }
        for item in payload.get("cards") or []:
            card = item.get("card") or {}
            oracle = card.get("oracleCard") or {}
            cname = oracle.get("name") or card.get("name")
            if not cname:
                continue
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
                    quantity=int(item.get("quantity") or 1),
                    name=cname,
                    section=section,
                    set_code=(edition.get("editioncode") or "").lower() or None,
                    collector_number=str(card.get("collectorNumber") or "") or None,
                )
            )

        if not deck.entries:
            deck.warnings.append("Archidekt returned no cards for this deck")
        return deck


class DeckstatsSource(DeckSource):
    """Deckstats -- undocumented but stable JSON export, no auth.

    A deck URL carries two numbers, the owner id and the saved deck id
    (deckstats.net/decks/<owner>/<deck>-slug). `deck_id` returns them joined as
    "<owner>/<deck>"; `fetch` splits them back for the api.php call.
    """

    id = "deckstats"
    label = "Deckstats"
    _ID = re.compile(r"deckstats\.net/decks/(\d+)/(\d+)")

    def deck_id(self, url: str) -> str | None:
        m = self._ID.search(url or "")
        return "%s/%s" % (m.group(1), m.group(2)) if m else None

    def fetch(self, deck_id: str, session: requests.Session) -> DeckList:
        owner_id, _, saved_id = deck_id.partition("/")
        api = (
            "https://deckstats.net/api.php?action=get_deck"
            "&id_type=saved&owner_id=%s&id=%s&response_type=json"
            % (owner_id, saved_id)
        )
        resp = session.get(api, timeout=45)
        # deckstats answers a missing or private deck with 400 "Deck not found".
        if resp.status_code == 400:
            raise ImportError_(
                "Deckstats deck %s not found (is it private?)" % saved_id)
        resp.raise_for_status()

        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            raise ImportError_(
                "Deckstats returned something that is not JSON: %s" % exc) from exc
        if not isinstance(payload, dict) or "sections" not in payload:
            raise ImportError_(
                "Deckstats deck %s is not available (is it private?)" % saved_id)

        deck = DeckList(
            name=payload.get("name") or "Deckstats deck %s" % saved_id,
            source="deckstats",
            url="https://deckstats.net/decks/%s/%s" % (owner_id, saved_id),
        )

        def add(cards: Any, section: str) -> None:
            # Deckstats gives no set/number -- only a name and an amount. That is
            # all we need; the printing is decided later from the topdeck listing.
            for card in cards or []:
                cname = card.get("name")
                if not cname:
                    continue
                deck.entries.append(
                    DeckEntry(
                        quantity=int(card.get("amount") or 1),
                        name=cname,
                        section=section,
                    )
                )

        # The mainboard comes split into named sections; the commander sits in a
        # section deckstats names "Commander" (the same name its text export
        # emits as "//Commander"). Everything else in `sections` is the main deck.
        for sec in payload.get("sections") or []:
            name = (sec.get("name") or "").strip().lower()
            section = "commander" if name in ("commander", "commanders") else "main"
            add(sec.get("cards"), section)
        add(payload.get("sideboard"), "side")
        add(payload.get("maybeboard"), "maybe")

        if not deck.entries:
            deck.warnings.append("Deckstats returned no cards for this deck")
        return deck


class MoxfieldSource(DeckSource):
    """Moxfield -- undocumented API behind Cloudflare; may refuse us.

    On refusal we say so clearly instead of failing silently, because the user
    can always open the deck, Export -> Text, and paste the list.
    """

    id = "moxfield"
    label = "Moxfield"
    _ID = re.compile(r"moxfield\.com/decks/([A-Za-z0-9_\-]+)")

    def deck_id(self, url: str) -> str | None:
        m = self._ID.search(url or "")
        return m.group(1) if m else None

    def fetch(self, deck_id: str, session: requests.Session) -> DeckList:
        resp = session.get(
            "https://api2.moxfield.com/v3/decks/all/%s" % deck_id,
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
            raise ImportError_(
                "Moxfield deck %s not found (is it private?)" % deck_id)
        resp.raise_for_status()

        try:
            payload = resp.json()
        except json.JSONDecodeError as exc:
            raise ImportError_(
                "Moxfield returned something that is not JSON: %s" % exc) from exc

        deck = DeckList(
            name=payload.get("name") or "Moxfield deck",
            source="moxfield",
            url="https://moxfield.com/decks/%s" % deck_id,
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


class Mtgtop8Source(DeckSource):
    """mtgtop8 -- a plain-text export at /mtgo?d=<id>, far more stable than
    scraping the event page."""

    id = "mtgtop8"
    label = "mtgtop8"
    _ID = re.compile(r"mtgtop8\.com/(?:event|mtgo|deck)\?(?:.*?&)?d=(\d+)", re.I)

    def deck_id(self, url: str) -> str | None:
        m = self._ID.search(url or "")
        return m.group(1) if m else None

    def fetch(self, deck_id: str, session: requests.Session) -> DeckList:
        resp = session.get("https://mtgtop8.com/mtgo?d=%s" % deck_id, timeout=45)
        resp.raise_for_status()
        body = resp.text
        if not body.strip():
            raise ImportError_(
                "mtgtop8 returned an empty decklist for d=%s" % deck_id)

        deck = parse_text(body, name="mtgtop8 deck %s" % deck_id)
        deck.source = "mtgtop8"
        deck.url = "https://mtgtop8.com/event?d=%s" % deck_id
        return deck


# The sources import_from_url tries, in order. The URL patterns do not overlap,
# so the order is for readability, not correctness.
SOURCES: list[DeckSource] = [
    ArchidektSource(),
    DeckstatsSource(),
    MoxfieldSource(),
    Mtgtop8Source(),
]


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #

def import_from_url(url: str) -> DeckList:
    url = (url or "").strip()
    if not url:
        raise ImportError_("no URL given")
    if not re.match(r"^https?://", url, re.I):
        url = "https://" + url

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    for source in SOURCES:
        deck_id = source.deck_id(url)
        if deck_id is not None:
            return source.fetch(deck_id, session)

    # No source claimed the URL. A couple of sites get a pointed hint instead of
    # the generic "unsupported" message, because people reach for them often.
    host = (urllib.parse.urlparse(url).hostname or "").lower()
    if "mtgtop8.com" in host:
        raise ImportError_(
            "no deck id in that mtgtop8 URL -- open a single deck (the link "
            "contains d=<number>), not the event summary"
        )
    if "topdeck.ru" in host:
        raise ImportError_(
            "topdeck decklists are republished from mtgtop8 -- open the deck on "
            "mtgtop8 and paste that link, or paste the list as text"
        )
    raise ImportError_(
        "unsupported site: %s. Supported: %s. Anything else: paste the "
        "decklist as text." % (host or url, ", ".join(s.label for s in SOURCES))
    )
