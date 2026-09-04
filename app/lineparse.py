"""Normalizer for topdeck.ru seller listing lines.

This is the heart of the project. topdeck gives us quantity, price, seller and a
VERBATIM `line` -- but set, language, condition and foil live only inside that
free-form line, and every seller writes it differently:

    1x Lightning Bolt (EN) (SP) (A25 #141) 160
    3 Удар Молнии (м11) sp 130                     <- Cyrillic 'м'
    4 Lightning Bolt (NM EN CLB #187) - 145 руб
    1 <b>Lightning Bolt (JP)</b> (PL, m11-149)
    1 Lightning Bolt (M/NM, Commander Legends: Battle for Baldur's Gate)
    3 Удар Молнии (#146) [2 рус, 1 eng] - 130 руб.  <- MIXED lot

Design rules:
  * Never guess silently. Every field carries a confidence, and anything we could
    not consume is kept in `residue` so the UI can show it and we can improve.
  * A mixed lot ("разные", "[2 рус, 1 eng]") is flagged, not resolved. The user
    decides -- which is why we always show the original line.
  * Strip the known card names FIRST. Otherwise words inside card names collide
    with set codes and language tokens.
"""

from __future__ import annotations

import html
import json
import os
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from typing import Any, Iterable

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# --------------------------------------------------------------------------- #
# Cyrillic look-alikes. Sellers type set codes on a Russian keyboard layout:
# "м11" is Cyrillic м + 11, and must resolve to the M11 set.
# --------------------------------------------------------------------------- #
HOMOGLYPHS = str.maketrans(
    {
        "а": "a", "в": "b", "с": "c", "е": "e", "н": "h", "к": "k", "м": "m",
        "о": "o", "р": "p", "т": "t", "у": "y", "х": "x", "і": "i", "ѕ": "s",
        "А": "A", "В": "B", "С": "C", "Е": "E", "Н": "H", "К": "K", "М": "M",
        "О": "O", "Р": "P", "Т": "T", "У": "Y", "Х": "X",
    }
)

# --------------------------------------------------------------------------- #
# Condition grades. Raw token is preserved; `grade` is the normalized scale.
# --------------------------------------------------------------------------- #
CONDITION_PATTERNS: list[tuple[str, str]] = [
    # (regex, normalized grade)  -- order matters, longest/most specific first
    (r"m\s*/\s*nm", "NM"),
    (r"nm\s*/\s*m", "NM"),
    (r"near\s+mint", "NM"),
    (r"nm\s*\+\s*-", "NM"),
    (r"nm[+-]?", "NM"),
    (r"gem\s*mint", "M"),
    (r"mint", "M"),
    (r"excellent", "EX"),
    (r"very\s+good", "EX"),
    (r"lightly\s+played", "LP"),
    (r"slightly\s+played", "LP"),
    (r"moderately\s+played", "MP"),
    (r"heavily\s+played", "HP"),
    (r"damaged", "DMG"),
    (r"sp\s*/\s*sp\+", "LP"),
    (r"sp[+-]?", "LP"),
    (r"lp[+-]?", "LP"),
    (r"mp[+-]?", "MP"),
    (r"hp[+-]?", "HP"),
    (r"pl[+-]?", "MP"),
    (r"gd[+-]?", "EX"),
    (r"ex[+-]?", "EX"),
    (r"vg[+-]?", "EX"),
    (r"dmg", "DMG"),
    (r"poor", "DMG"),
    # Russian shorthand
    (r"идеал\w*", "M"),
    (r"отл\w*", "NM"),
    (r"хор\w*", "EX"),
    (r"уд\w*", "MP"),
]

# --------------------------------------------------------------------------- #
# Languages. 2-letter codes cannot collide with Scryfall set codes (min 3 chars),
# but they must still be standalone tokens.
# --------------------------------------------------------------------------- #
LANGUAGE_PATTERNS: list[tuple[str, str]] = [
    (r"english", "en"),
    (r"eng?", "en"),
    (r"англ\w*", "en"),
    (r"russian", "ru"),
    (r"rus", "ru"),
    (r"ru", "ru"),
    (r"рус\w*", "ru"),
    (r"japanese", "ja"),
    (r"jpn?", "ja"),
    (r"ja", "ja"),
    (r"яп\w*", "ja"),
    (r"german", "de"),
    (r"ger", "de"),
    (r"de", "de"),
    (r"нем\w*", "de"),
    (r"french", "fr"),
    (r"fre", "fr"),
    (r"fr", "fr"),
    (r"фр\w*", "fr"),
    (r"italian", "it"),
    (r"ita", "it"),
    (r"it", "it"),
    (r"итал\w*", "it"),
    (r"spanish", "es"),
    (r"spa", "es"),
    (r"es", "es"),
    (r"исп\w*", "es"),
    (r"portuguese", "pt"),
    (r"por", "pt"),
    (r"pt", "pt"),
    (r"korean", "ko"),
    (r"kor", "ko"),
    (r"ko", "ko"),
    (r"chinese", "zh"),
    (r"chs|cht|zhs|zht", "zh"),
    (r"zh|cn", "zh"),
]

# --------------------------------------------------------------------------- #
# Print treatments / variants worth surfacing -- they change the price a lot.
# --------------------------------------------------------------------------- #
TREATMENT_PATTERNS: list[tuple[str, str]] = [
    (r"borderless", "borderless"),
    (r"без\s*рамки", "borderless"),
    (r"showcase", "showcase"),
    (r"textless", "textless"),
    (r"без\s*текста", "textless"),
    (r"extended\s*art|ext\s*art|extart", "extended-art"),
    (r"full\s*art", "full-art"),
    (r"retro(\s*frame)?", "retro"),
    (r"etched", "etched"),
    (r"serial\w*", "serialized"),
    (r"surge\s*foil", "surge-foil"),
    (r"galaxy\s*foil", "galaxy-foil"),
    (r"gilded", "gilded"),
    (r"promo|промо", "promo"),
    (r"prerelease|пререлиз", "prerelease"),
    (r"buy\s*-?\s*a\s*-?\s*box|bab", "buy-a-box"),
    (r"alt(ernate)?\s*art|альт\w*", "alt-art"),
    (r"signed|подпис\w*", "signed"),
    (r"proxy|прокси", "proxy"),
    (r"altered|кастом\w*", "altered"),
]

# topdeck strips images out of listings, so a seller with a photo pastes a link
# instead -- Telegram channels and Yandex.Disk in practice. Rare (5 lines out of
# 1212 measured), but the only actual photo evidence the data contains.
LINK_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.I)

FOIL_PATTERN = re.compile(r"\b(foil|фойл\w*|фоил\w*|фольг\w*)\b", re.I)
NONFOIL_PATTERN = re.compile(r"\b(non\s*-?\s*foil|nonfoil|нефойл\w*)\b", re.I)

# Explicit signals that one listing bundles different printings/languages.
MIXED_PATTERN = re.compile(
    r"\b(разные|разн\.|mixed|микс|ассорти|different)\b", re.I
)

# The number must NOT swallow spaces: a greedy "\d[\d\s.,]+\d" turns
# "m10 143р." into the price "10 143" and destroys the set code m10.
# Also refuse a match that starts right after a letter, so "m10" stays intact.
PRICE_PATTERN = re.compile(
    r"(?<![^\W\d_])(\d[\d.,]{0,8}\d|\d)\s*(?:р\.?|руб\.?|рублей|₽|rub)(?![\w])", re.I
)
TRAILING_PRICE = re.compile(r"(?:^|[-–—\s,])(\d{2,6})\s*$")

# Community set abbreviations Scryfall does not use as codes.
SET_ALIASES = {
    # core-set ordinal shorthands sellers actually type
    "2e": "2ed", "2nd": "2ed", "unlimited": "2ed",
    "3e": "3ed", "3rd": "3ed", "rev": "3ed", "revised": "3ed",
    "4e": "4ed", "4th": "4ed", "4wb": "4ed",
    "5e": "5ed", "5th": "5ed",
    "6e": "6ed", "6th": "6ed",
    "7e": "7ed", "7th": "7ed",
    "8e": "8ed", "8th": "8ed",
    "9e": "9ed", "9th": "9ed",
    "10e": "10e", "10th": "10e",
    "alpha": "lea",
    "beta": "leb",
    "unl": "2ed",
}

# Multi-word community names that are not exact Scryfall set names.
# Matched as substrings, longest first. Only unambiguous ones belong here --
# "Judge Gift Cards" and "From the Vault" span many years, so they are treated
# as promo families below instead of being guessed at.
SET_NAME_ALIASES = {
    "strixhaven mystical archive": "sta",
    "mystical archive": "sta",
    "strixhaven": "stx",
    "time spiral remastered": "tsr",
    "double masters 2022": "2x2",
}

# Promo families where the exact set is genuinely ambiguous from the line alone.
# We label them so the UI can warn, and leave the set unresolved.
PROMO_FAMILY_PATTERNS: list[tuple[str, str]] = [
    (r"judge\s*(gift|rewards?|cards?)?|jgc", "judge-promo"),
    (r"magic\s*player\s*rewards|player\s*rewards|mpr", "player-rewards"),
    (r"from\s*the\s*vault|ftv", "from-the-vault"),
    (r"premium\s*decks?", "premium-deck"),
    (r"magicfest", "magicfest"),
    (r"magiccon", "magiccon"),
    (r"f?wb|white\s*border", "white-border"),
    (r"fbb|foreign\s*black\s*border", "foreign-black-border"),
    (r"gold\s*border|goldborder|wcd", "gold-border"),
    (r"textured", "textured-foil"),
]


@dataclass
class ParsedLine:
    set_code: str | None = None
    set_name: str | None = None
    set_confidence: str = "none"  # code | alias | name | number-only | none
    collector_number: str | None = None
    language: str | None = None
    languages: list[str] = field(default_factory=list)
    condition: str | None = None  # normalized grade
    condition_raw: str | None = None
    foil: bool | None = None  # None = not stated
    treatments: list[str] = field(default_factory=list)
    promo_family: str | None = None  # set genuinely ambiguous (e.g. judge promos)
    links: list[str] = field(default_factory=list)  # photos the seller linked to
    mixed: bool = False
    price_in_line: int | None = None
    residue: str = ""
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class SetIndex:
    """Lookup of Scryfall set codes and names."""

    def __init__(self, sets: list[dict[str, Any]]) -> None:
        self.by_code: dict[str, dict[str, Any]] = {}
        self.by_name: dict[str, dict[str, Any]] = {}
        for s in sets:
            code = (s.get("code") or "").lower()
            if code:
                self.by_code[code] = s
            name = (s.get("name") or "").lower()
            if name:
                self.by_name[name] = s
        # Longest names first so "Commander Legends: Battle for Baldur's Gate"
        # wins over "Commander Legends".
        self._names_by_len = sorted(self.by_name, key=len, reverse=True)

    @classmethod
    def load(cls, path: str | None = None) -> "SetIndex":
        path = path or os.path.join(DATA_DIR, "sets.json")
        with open(path, encoding="utf-8") as fh:
            payload = json.load(fh)
        return cls(payload.get("data", payload))

    def resolve_code(self, token: str) -> dict[str, Any] | None:
        t = token.lower()
        if t in self.by_code:
            return self.by_code[t]
        alias = SET_ALIASES.get(t)
        if alias and alias in self.by_code:
            return self.by_code[alias]
        return None

    def find_name(self, text: str) -> tuple[dict[str, Any], str] | None:
        low = text.lower()
        for name in self._names_by_len:
            if len(name) < 5:
                continue
            if name in low:
                return self.by_name[name], name
        return None


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]*>", " ", text)
    return html.unescape(text)


def _normalize_space(text: str) -> str:
    # NBSP and friends are everywhere in these listings.
    text = text.replace("\xa0", " ").replace(" ", " ").replace("\t", " ")
    text = unicodedata.normalize("NFKC", text)
    return re.sub(r"\s+", " ", text).strip()


def clean_line(line: str) -> str:
    return _normalize_space(_strip_html(line))


def _remove_names(text: str, names: Iterable[str]) -> str:
    """Remove the known card names so their words cannot be mistaken for
    set codes or language tokens."""
    for name in sorted({n for n in names if n and len(n) >= 3}, key=len, reverse=True):
        text = re.sub(re.escape(name), " ", text, flags=re.I)
        # Sellers often drop the part after a comma ("Ragavan, Nimble Pilferer").
        head = name.split(",")[0].strip()
        if len(head) >= 5 and head.lower() != name.lower():
            text = re.sub(re.escape(head), " ", text, flags=re.I)
    return _normalize_space(text)


def _consume(text: str, pattern: re.Pattern[str]) -> tuple[str, list[str]]:
    """Remove every match of `pattern`, returning the leftover text and matches."""
    found: list[str] = []

    def sub(m: re.Match[str]) -> str:
        found.append(m.group(0))
        return " "

    return _normalize_space(pattern.sub(sub, text)), found


def parse_line(
    line: str,
    set_index: SetIndex,
    eng_name: str = "",
    rus_name: str = "",
    extra_names: Iterable[str] = (),
) -> ParsedLine:
    """Extract structured attributes from one seller line."""
    out = ParsedLine()
    if not line:
        out.warnings.append("empty line")
        return out

    text = clean_line(line)

    # 1a. Pull out any links the seller pasted (usually a photo of the card),
    #     before tokenisation mangles them.
    text, links = _consume(text, LINK_PATTERN)
    cleaned_links = []
    for link in links:
        link = link.rstrip(".,;")
        # Trailing ")" is usually the closing bracket of "(see photo: ...)" --
        # but not when the URL itself contains a bracket, as Scryfall's
        # Japanese card URLs do.
        if link.endswith(")") and "(" not in link:
            link = link[:-1]
        cleaned_links.append(link)
    out.links = cleaned_links

    # 1b. Mixed-lot signals, before anything else eats the words.
    if MIXED_PATTERN.search(text):
        out.mixed = True

    # 2. Full set NAME, matched against the original text (names contain
    #    spaces/punctuation that later tokenization would destroy).
    hit = set_index.find_name(text)
    if hit:
        s, matched = hit
        out.set_code = s["code"].lower()
        out.set_name = s["name"]
        out.set_confidence = "name"
        text = _normalize_space(re.sub(re.escape(matched), " ", text, flags=re.I))
    else:
        for alias in sorted(SET_NAME_ALIASES, key=len, reverse=True):
            if alias in text.lower():
                s = set_index.by_code.get(SET_NAME_ALIASES[alias])
                if s:
                    out.set_code = s["code"].lower()
                    out.set_name = s["name"]
                    out.set_confidence = "alias"
                    text = _normalize_space(re.sub(re.escape(alias), " ", text, flags=re.I))
                break

    # 3. Drop the card names.
    text = _remove_names(text, [eng_name, rus_name, *extra_names])

    # 4. Price (explicit currency first, then a bare trailing number).
    m = PRICE_PATTERN.search(text)
    if m:
        digits = re.sub(r"[^\d]", "", m.group(1))
        if digits:
            out.price_in_line = int(digits)
        text = _normalize_space(text[: m.start()] + " " + text[m.end() :])
    else:
        m = TRAILING_PRICE.search(text)
        if m:
            out.price_in_line = int(m.group(1))
            text = _normalize_space(text[: m.start(1)] + " " + text[m.end(1) :])

    # 5. Foil.
    text, nonfoil = _consume(text, NONFOIL_PATTERN)
    if nonfoil:
        out.foil = False
    text, foil = _consume(text, FOIL_PATTERN)
    if foil:
        out.foil = True

    # 6. Treatments.
    for pat, label in TREATMENT_PATTERNS:
        rx = re.compile(r"\b(?:" + pat + r")\b", re.I)
        text, hits = _consume(text, rx)
        if hits and label not in out.treatments:
            out.treatments.append(label)

    # 7. Collector number. Do this BEFORE set codes so "clb-401" and "M10 #146"
    #    give up both halves cleanly.
    text, out.collector_number = _extract_collector_number(text, set_index, out)

    # 8. Condition.
    for pat, grade in CONDITION_PATTERNS:
        rx = re.compile(r"(?<![\w#-])(?:" + pat + r")(?![\w-])", re.I)
        m = rx.search(text)
        if m:
            out.condition = grade
            out.condition_raw = m.group(0)
            text = _normalize_space(text[: m.start()] + " " + text[m.end() :])
            break

    # 9. Languages (collect all -- several means a mixed lot).
    langs: list[str] = []
    for pat, code in LANGUAGE_PATTERNS:
        rx = re.compile(r"(?<![\w#-])(?:" + pat + r")(?![\w-])", re.I)
        text, hits = _consume(text, rx)
        if hits and code not in langs:
            langs.append(code)
    out.languages = langs
    if len(langs) == 1:
        out.language = langs[0]
    elif len(langs) > 1:
        out.mixed = True
        out.warnings.append("several languages in one listing: " + ", ".join(langs))

    # 10. Set code from the remaining tokens.
    if not out.set_code:
        for token in re.findall(r"[0-9A-Za-zА-Яа-я]{2,6}", text):
            norm = token.translate(HOMOGLYPHS)
            s = set_index.resolve_code(norm)
            if s:
                out.set_code = s["code"].lower()
                out.set_name = s["name"]
                out.set_confidence = "code" if norm.lower() in set_index.by_code else "alias"
                text = _normalize_space(
                    re.sub(r"(?<![\w])" + re.escape(token) + r"(?![\w])", " ", text)
                )
                break

    # 11. Promo families -- LAST, so a real set code always wins over an
    #     annotation like "judge" or "white border". These families span many
    #     years, so the line alone cannot pin the exact set; we only label them.
    for pat, label in PROMO_FAMILY_PATTERNS:
        rx = re.compile(r"\b(?:" + pat + r")\b", re.I)
        text, hits = _consume(text, rx)
        if hits and out.promo_family is None:
            out.promo_family = label
            if not out.set_code:
                out.warnings.append(
                    "promo printing (%s): exact set not determinable from the line" % label
                )

    if not out.set_code and out.collector_number:
        out.set_confidence = "number-only"
        out.warnings.append("no set stated; only a collector number")
    elif not out.set_code:
        out.warnings.append("no set identified")

    out.residue = text
    return out


def _extract_collector_number(
    text: str, set_index: SetIndex, out: ParsedLine
) -> tuple[str, str | None]:
    """Pull a collector number, opportunistically claiming an attached set code."""
    # a) "clb-401", "m11-149", "2x2-117"
    for m in re.finditer(r"\b([0-9A-Za-zА-Яа-я]{3,6})\s*-\s*([0-9]{1,4}[a-z]?)\b", text):
        code = m.group(1).translate(HOMOGLYPHS)
        s = set_index.resolve_code(code)
        if s:
            if not out.set_code:
                out.set_code = s["code"].lower()
                out.set_name = s["name"]
                out.set_confidence = "code"
            rest = _normalize_space(text[: m.start()] + " " + text[m.end() :])
            return rest, m.group(2)

    # b) "SLD 1822", "PW26 5", "A25 141", "SLD IFIYW-2"
    for m in re.finditer(
        r"\b([0-9A-Za-zА-Яа-я]{3,6})\s+#?\s*([0-9]{1,4}[a-z]?|[A-Z]{2,8}-\d{1,3})\b", text
    ):
        code = m.group(1).translate(HOMOGLYPHS)
        s = set_index.resolve_code(code)
        if s:
            if not out.set_code:
                out.set_code = s["code"].lower()
                out.set_name = s["name"]
                out.set_confidence = "code"
            rest = _normalize_space(text[: m.start()] + " " + text[m.end() :])
            return rest, m.group(2)

    # c) bare "#146", "# 146", "#IFIYW-2"
    m = re.search(r"#\s*([0-9]{1,4}[a-z]?|[A-Za-z]{2,8}-\d{1,3})\b", text)
    if m:
        rest = _normalize_space(text[: m.start()] + " " + text[m.end() :])
        return rest, m.group(1)

    return text, None


def price_in_line(line: str) -> int | None:
    """The price the seller wrote, read straight from the line.

    Needed because topdeck's own `cost` field is not always right: it read
    "1 Тиамат (Tiamat) #235/281 AFR RU 1300" as 235 roubles, taking the
    collector number for the price. Comparing the two is the only way to notice.
    """
    text = clean_line(line)
    if not text:
        return None
    m = PRICE_PATTERN.search(text)
    if m:
        digits = re.sub(r"[^\d]", "", m.group(1))
        return int(digits) if digits else None
    m = TRAILING_PRICE.search(text)
    if m:
        return int(m.group(1))
    return None
