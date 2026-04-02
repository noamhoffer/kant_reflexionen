#!/usr/bin/env python3
"""
Kant Reflexionen Parser
=======================
Parses the digitized Nachlass volumes (AA 14–19) and builds a SQLite database
of all Reflexionen.  Works from a local HTTrack mirror (recommended) or by
fetching pages over HTTP directly from https://www.korpora.org/Kant/

Dependencies
------------
    pip install beautifulsoup4 lxml requests

Database schema
---------------
reflexionen
    number      TEXT  PRIMARY KEY   e.g. "1562" or "158a"
    volume      INTEGER             AA volume number (14–19)
    page_start  INTEGER             first page the Reflexion appears on
    page_end    INTEGER             last page (same as page_start when on one page)
    dating_raw  TEXT                raw dating string, e.g. "α2" or "κ -- ξ"
    date_from   INTEGER             earliest possible year derived from dating_raw
    date_to     INTEGER             latest possible year derived from dating_raw
    source_raw  TEXT                raw source/location string, e.g. "L 1" or "M §. 7"
    note_raw    TEXT                any additional note in the header (4th field)
    text        TEXT                body text of the Reflexion
    url_start   TEXT                URL of the first page
    source_url  TEXT                direct URL into the digitized source text (if available)

Dating resolution
-----------------
Adickes assigned each phase a Greek-letter code (α1, β2, γ … ω5).
date_from / date_to are the union of all phases mentioned in dating_raw:
  - "α2"          → 1754–1755
  - "β1--ε2"      → 1752–1764  (all phases from β1 through ε2, inclusive)
  - "κ -- ξ"      → 1769–1772
  - "μ ? ν ?"     → 1770–1771  (uncertain but still bounded)
  - "φ ??"        → 1776–1778  (doubly uncertain, still included)
  - "(κ ? ρ ?)"   → parenthesised less-likely alternatives widen the range
NULL in both columns means the dating string was absent or unrecognisable.

Usage
-----
    # From a local HTTrack mirror (fast, no network required):
    python kant_reflexionen_parser.py --local C:/schriften

    # From the live website (slower, needs internet):
    python kant_reflexionen_parser.py --delay 0.5

Flags
-----
--local     path to the HTTrack mirror root directory (e.g. C:/schriften).
            When given, reads files from disk instead of fetching over HTTP.
            The mirror must contain subdirectories like www.korpora.org/Kant/aa16/
            as HTTrack creates them.
--volumes   space-separated list of AA volume numbers to process (default: 14 15 16 17 18 19)
--delay     seconds between HTTP requests, only used without --local (default: 0.5)
--db        path to the output SQLite database file (default: kant_reflexionen.db)
--resume    skip pages already present in the DB (useful after an interrupted run)
"""

import argparse
import re
import sqlite3
import time
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from kant_sources import resolve_source_url
from kant_provenienzen import load_provenienzen


# ── Volume page ranges ─────────────────────────────────────────────────────────
# Approximate upper bounds; the scraper stops as soon as it receives a 404.
VOLUME_RANGES = {
    14: (1, 400),
    15: (1, 700),
    16: (1, 870),
    17: (1, 750),
    18: (1, 750),
    19: (1, 650),
}

BASE_URL   = "https://www.korpora.org/Kant"

# ── Provenienzen lookup table ─────────────────────────────────────────────────
# Populated at startup from the korpora.org Provenienzen HTML tables.
# Maps Adickes number → {source_raw, note_raw, url_start, source_url, brief_url}
PROVENIENZEN: dict = {}
USER_AGENT = "KantReflexionenBot/1.0 (research; contact: researcher@example.com)"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": USER_AGENT})



# ── Adickes dating phases → year ranges ───────────────────────────────────────
# Source: https://www.korpora.org/Kant/nachlass-a.html
# Each entry is (date_from, date_to) as integers.

PHASE_YEARS: dict[str, tuple[int, int]] = {
    "α1": (1753, 1754),
    "α2": (1754, 1755),
    "β1": (1752, 1756),   # "1752 - W.S. 1755/56"
    "β2": (1758, 1759),
    "γ":  (1760, 1764),
    "δ":  (1762, 1763),
    "ε":  (1762, 1764),
    "ζ":  (1764, 1766),
    "η":  (1764, 1768),
    "θ":  (1766, 1768),
    "ι":  (1766, 1768),
    "κ":  (1769, 1769),
    "λ":  (1769, 1770),
    "μ":  (1770, 1771),
    "ν":  (1771, 1771),
    "ξ":  (1772, 1772),
    "ο":  (1769, 1772),
    "π":  (1772, 1775),
    "ρ":  (1773, 1775),
    "σ":  (1774, 1777),
    "τ":  (1775, 1776),
    "υ":  (1776, 1778),
    "φ":  (1776, 1778),
    "χ":  (1778, 1779),
    "ψ1": (1780, 1783),
    "ψ2": (1783, 1784),
    "ψ3": (1785, 1788),
    "ψ4": (1788, 1789),
    "ω1": (1790, 1791),
    "ω2": (1792, 1794),
    "ω3": (1794, 1795),
    "ω4": (1796, 1798),
    "ω5": (1798, 1804),
}

# Bare-letter fallback ranges (when no superscript digit is present)
_BARE_PHASE_YEARS: dict[str, tuple[int, int]] = {
    "α": (1753, 1755),
    "β": (1752, 1759),
    "ψ": (1780, 1789),
    "ω": (1790, 1804),
}

PHASE_ORDER: list[str] = list(PHASE_YEARS.keys())

# Superscript digit → ASCII digit
_SUP_DIGIT = str.maketrans("¹²³⁴⁵⁶⁷⁸⁹⁰", "1234567890")

# Greek letters used in Adickes phases
_GREEK = "αβγδεζηθικλμνξοπρστυφχψως"  # ς = final sigma variant

# Regex for a single phase token: Greek letter + optional superscript digit(s)
# handles both ASCII digits (β1) and Unicode superscript (ω¹)
_PHASE_TOKEN_RE = re.compile(
    rf"([{_GREEK}])"          # Greek letter
    r"([¹²³⁴⁵]|\d)?"         # optional superscript or ASCII digit suffix
)

# Regex for a phase range written with superscripts: ω³⁻⁴  or  ω¹⁻²
_SUP_RANGE_RE = re.compile(
    rf"([{_GREEK}])"          # Greek letter (same for both ends)
    r"([¹²³⁴⁵]|\d)"          # start superscript
    r"[⁻\-–—]"               # dash separator
    r"([¹²³⁴⁵]|\d)"          # end superscript
)

# Regex for explicit year in parentheses: (1790), (1793—4), (Nov. 1797), ω(1800)
_PAREN_YEAR_RE = re.compile(
    r"\s?\(\s*"
    r"(?:um\s+|[A-Za-zäöüÄÖÜ]+\.?\s+(?:[A-Za-z]+\.?\s+)?)?"
    r"(1[678]\d\d)"
    r"(?:\s*[\u2014\u2013\-–]\s*(\d{1,4}))?"
    r"\s*\)"
)

# Regex for bare year ranges like "1788—91" or "1788—1790"
_BARE_YEAR_RANGE_RE = re.compile(
    r"(1[678]\d\d)\s*[\u2014\u2013\-]\s*(\d{1,4})"
)

# Regex for decade strings like "60er Jahre", "70er — 80er Jahre"
_DECADE_RE = re.compile(r"(\d0)er")


def _normalise_digit(ch: str) -> str:
    """Convert superscript digit to ASCII ('¹' → '1')."""
    return ch.translate(_SUP_DIGIT).strip()


def _token_to_phase(letter: str, digit_ch: str | None) -> "str | None":
    """Resolve a (letter, optional-digit-char) pair to a PHASE_YEARS key.
    Returns the bare letter for ψ/ω/α/β even if not in PHASE_YEARS,
    so that _phase_range can use _BARE_FIRST/_BARE_LAST for range expansion.
    Isolated bare-letter tokens (step 7) will return None here and fall
    through to step 8 (_BARE_PHASE_YEARS) for the correct full range.
    """
    # Normalise final sigma ς → σ (same Adickes phase)
    letter = "σ" if letter == "ς" else letter
    if digit_ch:
        d = _normalise_digit(digit_ch)
        key = letter + d
        if key in PHASE_YEARS:
            return key
    # Key for use in _phase_range (bare letter)
    if letter in PHASE_YEARS or letter in _BARE_PHASE_YEARS:
        return letter
    return None


_BARE_FIRST = {"α": "α1", "β": "β1", "ψ": "ψ1", "ω": "ω1"}
_BARE_LAST  = {"α": "α2", "β": "β2", "ψ": "ψ4", "ω": "ω5"}

def _phase_range(key1: str, key2: str) -> list[str]:
    """Return all phase keys between key1 and key2 in PHASE_ORDER, inclusive.
    Bare-letter endpoints are expanded: ψ as start → ψ1, ψ as end → ψ4.
    """
    k1 = _BARE_FIRST.get(key1, key1)
    k2 = _BARE_LAST.get(key2, key2)
    try:
        i, j = PHASE_ORDER.index(k1), PHASE_ORDER.index(k2)
    except ValueError:
        return [k for k in (k1, k2) if k in PHASE_YEARS]
    if i > j:
        i, j = j, i
    return PHASE_ORDER[i: j + 1]


def _year_range_from_phases(phases: list[str]) -> "tuple[int|None, int|None]":
    _all = {**PHASE_YEARS, **_BARE_PHASE_YEARS}
    years_from = [_all[p][0] for p in phases if p in _all]
    years_to   = [_all[p][1] for p in phases if p in _all]
    if not years_from:
        return None, None
    return min(years_from), max(years_to)


def _expand_year(year_str: str, anchor: int) -> int:
    """
    Expand a possibly-abbreviated year relative to an anchor.
    '4'  with anchor 1793 → 1794  (same decade)
    '94' with anchor 1793 → 1794  (same century)
    '1794' → 1794  (already full)
    """
    y = int(year_str)
    if y >= 1000:
        return y
    if y < 10:
        return (anchor // 10) * 10 + y   # same decade
    return (anchor // 100) * 100 + y      # same century


def _extract_year_from_text(text: str) -> "int | None":
    """Extract the first 4-digit year from a free-text string (for letter dates)."""
    m = re.search(r"\b(1[678]\d\d)\b", text)
    return int(m.group(1)) if m else None


def parse_dating(
    raw: str,
    note_raw: str = "",
    source_raw: str = "",
) -> "tuple[int | None, int | None]":
    """
    Derive (date_from, date_to) from an Adickes dating string plus optional
    supplementary context (note_raw, source_raw — used for letter dates).

    Priority order
    --------------
    1. Exact year in parentheses inside raw:  ω¹ (1790)  → 1790
    2. Date extracted from a linked letter in note_raw/source_raw (year only)
    3. Bare year range in raw:  1788—91  → (1788, 1791)
    4. Decade string in raw:  60er Jahre  → (1760, 1769)
    5. Phase range with shared letter + superscript dash:  ω³⁻⁴ → ω3..ω4
    6. Explicit dashed phase range:  ρ—σ
    7. All individual phase tokens (union of their ranges)
    8. Bare-letter fallback:  ψ → (1780, 1789)
    """
    if not raw or not raw.strip():
        return None, None

    raw_s = raw.strip()

    # ── 1. Exact year in parentheses ─────────────────────────────────────────
    # A year in parentheses means Adickes is providing the definitive date,
    # overriding the phase range. Return it directly.
    paren_m = _PAREN_YEAR_RE.search(raw_s)
    if paren_m:
        y_from = int(paren_m.group(1))
        y_to   = _expand_year(paren_m.group(2), y_from) if paren_m.group(2) else y_from
        return y_from, y_to

    # ── 2. Letter date from note_raw or source_raw ────────────────────────────
    # Used when the reflexion is written ON a dated letter.
    # note_raw example: "Bemerkung Kants auf dem Brief ... vom 7. Febr. 1784"
    for field in (note_raw, source_raw):
        if not field:
            continue
        if any(kw in field for kw in ("Brief", "Letter", "letter")):
            y = _extract_year_from_text(field)
            if y:
                return y, y

    # ── 3. Bare year range in raw: 1788—91 or 1788—1790 ─────────────────────
    yr_m = _BARE_YEAR_RANGE_RE.search(raw_s)
    if yr_m:
        y1 = int(yr_m.group(1))
        y2 = _expand_year(yr_m.group(2), y1)
        return min(y1, y2), max(y1, y2)

    # Check for bare single year with no phase code
    bare_yr = re.fullmatch(r"\s*(1[678]\d\d)\s*", raw_s)
    if bare_yr:
        y = int(bare_yr.group(1))
        return y, y

    # ── 4. Decade strings ─────────────────────────────────────────────────────
    # Collect all decade values including both sides of "60-70er"
    decades = re.findall(r"(\d0)er", raw_s)  # "70er" from "60-70er" and "70er"
    decades += re.findall(r"(\d0)[-–\u2013\u2014]\d0er", raw_s)  # "60" from "60-70er"
    if decades and not any(c in raw_s for c in _GREEK):
        years = [1700 + int(d) for d in decades]
        return min(years), max(years) + 9

    # From here we work with Greek phase codes.

    # ── 5. Superscript range on shared letter: ω³⁻⁴  ω¹⁻² ─────────────────
    phases: list[str] = []
    consumed: list[tuple[int, int]] = []
    for m in _SUP_RANGE_RE.finditer(raw_s):
        letter = m.group(1)
        k1 = _token_to_phase(letter, m.group(2))
        k2 = _token_to_phase(letter, m.group(3))
        if k1 and k2:
            phases.extend(_phase_range(k1, k2))
        consumed.append((m.start(), m.end()))

    # ── 6. Explicit dashed phase range: ρ—σ  or  ρ--σ ───────────────────────
    _DASH_RANGE_RE = re.compile(
        rf"([{_GREEK}])([¹²³⁴⁵]|\d)?\s*[—\-–]{{1,2}}\s*([{_GREEK}])([¹²³⁴⁵]|\d)?"
    )
    for m in _DASH_RANGE_RE.finditer(raw_s):
        if any(s <= m.start() < e for s, e in consumed):
            continue
        k1 = _token_to_phase(m.group(1), m.group(2))
        k2 = _token_to_phase(m.group(3), m.group(4))
        if k1 and k2:
            phases.extend(_phase_range(k1, k2))
        consumed.append((m.start(), m.end()))

    # ── 7. Individual phase tokens ────────────────────────────────────────────
    for m in _PHASE_TOKEN_RE.finditer(raw_s):
        if any(s <= m.start() < e for s, e in consumed):
            continue
        k = _token_to_phase(m.group(1), m.group(2))
        if k:
            phases.append(k)

    if phases:
        return _year_range_from_phases(phases)

    # ── 8. Bare-letter fallback (no superscript digit) ────────────────────────
    for letter, yr in _BARE_PHASE_YEARS.items():
        if letter in raw_s:
            return yr

    return None, None

# ── Source abbreviation expansion ─────────────────────────────────────────────
# From Adickes, AA 14 Vorwort (summarised in nachlass-a.html).
# Applied to source_raw before storing in the DB.

SOURCE_ABBR_EXPANSIONS: dict[str, str] = {
    "L Bl.":  "Loses Blatt",
    "L Bl":   "Loses Blatt",
    "L. Bl.": "Loses Blatt",
    "L. Bl":  "Loses Blatt",
    "Ms.":    "Manuscript",
    "Ms":     "Manuscript",
    "R V":    "Kants Handexemplar der Kritik der reinen Vernunft",
    "A.M.":   "Altpreußische Monatsschrift",
}

# Longer, unambiguous expansions that stand alone as source_raw
_LONG_SOURCE_PREFIXES: dict[str, str] = {
    "L Bl.":  "Loses Blatt",
    "L. Bl.": "Loses Blatt",
    "L Bl":   "Loses Blatt",
    "L. Bl":  "Loses Blatt",
}


def expand_source_abbr(source_raw: str | None) -> str | None:
    """
    Expand leading abbreviations in source_raw so the UI shows readable text.

    Only the prefix is expanded; the rest (e.g. the leaf number) is kept.
    Examples:
        "L Bl. A 7"  → "Loses Blatt A 7"
        "Ms. Zusatz" → "Manuscript Zusatz"
        "L 18"       → "L 18"   (no change — L alone is the Meier textbook)
    """
    if not source_raw:
        return source_raw
    s = source_raw.strip()
    for abbr, expansion in SOURCE_ABBR_EXPANSIONS.items():
        if s == abbr or s.startswith(abbr + " ") or s.startswith(abbr + "."):
            rest = s[len(abbr):].lstrip(". ")
            return (expansion + (" " + rest if rest else "")).strip()
    return s


#
# The korpora.org HTML embeds machine-readable boundary markers for every
# reflexion as HTML comments:
#
#   <!-- NOTIZ-1668-A -->   ← reflexion 1668 begins here
#   <tr>...</tr>            ← header row + text rows
#   <!-- NOTIZ-1668-E -->   ← reflexion 1668 ends here
#
# A reflexion spanning a page break has only -A on the start page and
# only -E on the end page.
#
# Header metadata lives inside <a href="...nachlass-a.html">.
# The reflexion number is in a preceding <b> tag.
# Greek phase digits appear as <sup> inside the <a> (β<sup>1</sup> → "β1").
#
# Formatting preserved in text_html:
#   <i>                                        Latin / emphasis
#   <span style="text-decoration:line-through"> Kant's deletions
#   <span style="letter-spacing:.3ex">          Gesperrt (spaced emphasis)
#   ( g ... )  ( s ... )                        Interlinear / marginal additions

_NOTIZ_RE = re.compile(r'<!--\s*NOTIZ-(\d+[a-z]?)-([AE])\s*-->', re.IGNORECASE)
_KEEP_STYLES = ("text-decoration:line-through", "letter-spacing")


def _clean(s):
    """Strip leading/trailing dots, nbsp, spaces from a captured group."""
    return (s or "").strip(".\xa0 ")


def _parse_meta(block_html):
    """
    Extract (number, dating) from a reflexion block.
    Number from <b>, dating from <a href="nachlass-a">.
    Source and note come from the provenienzen tables, not from HTML.
    """
    soup = BeautifulSoup(block_html, "lxml")
    bold = soup.find("b")
    number = bold.get_text().strip().rstrip(".") if bold else ""
    if not re.match(r"^\d+[a-z]?$", number):
        number = ""

    a_tag = soup.find("a", href=re.compile("nachlass-a"))
    if not a_tag:
        return number, ""

    meta  = a_tag.get_text(" ", strip=True)
    parts = [_clean(p) for p in re.split(r"\.?\xa0{2,}", meta)]
    dating = parts[0] if len(parts) > 0 else ""
    return number, dating


def _img_tag(img_tag) -> str:
    """Rewrite a relative img src to the full korpora.org URL."""
    src = img_tag.get("src", "")
    if src and not src.startswith("http"):
        fname = src.split("/")[-1]       # "14_008_03.jpg"
        try:
            vol = int(fname.split("_")[0])
            src = (f"https://www.korpora.org/Kant/aa{vol:02d}"
                   f"/Bilder/{fname}")
        except (ValueError, IndexError):
            pass  # leave src as-is if filename doesn't match pattern
    alt = img_tag.get("alt", "Figur")
    return f'<img src="{src}" alt="{alt}" style="max-width:100%;display:block;margin:.5em 0">'


def _sanitize_td(td_tag):
    """
    Inner HTML of a text <td> with meaningful formatting preserved.

    Handles both standard HTML tags (AA16/17) and the custom XML-style tags
    used in AA14: <durchgestrichen>, <zusatz>, <zentiert>, <ueberschrift>.
    Images are replaced with a [Figur: filename] placeholder.
    """
    from bs4 import NavigableString
    out = []
    for child in td_tag.children:
        if isinstance(child, NavigableString):
            out.append(str(child))
        elif child.name in ("i", "sup", "sub"):
            out.append(str(child))
        elif child.name in ("s", "del", "durchgestrichen"):
            # All three mean strikethrough / deleted text
            out.append(
                f'<span style="text-decoration:line-through">{child.get_text()}</span>'
            )
        elif child.name == "span":
            style = child.get("style", "")
            if any(k in style for k in _KEEP_STYLES):
                out.append(str(child))
            else:
                out.append(child.get_text())
        elif child.name in ("center", "zentiert"):
            # Centred content (math formulas, section labels) — recurse
            out.append(_sanitize_td(child))
        elif child.name in ("ueberschrift",):
            # Section heading — wrap in bold
            out.append(f"<b>{child.get_text()}</b>")
        elif child.name == "zusatz":
            # Simultaneous addition — treat like interlinear ( g ... )
            out.append(f"( g {child.get_text()} )")
        elif child.name == "img":
            out.append(_img_tag(child))
        elif child.name == "a":
            # <a> wrapping an <img> (JavaScript lightbox links in AA14)
            img = child.find("img")
            if img:
                out.append(_img_tag(img))
            else:
                out.append(child.get_text())
        elif child.name in ("h2", "br"):
            out.append(child.get_text())
        else:
            out.append(child.get_text())
    return "".join(out).strip()


def _extract_text(block_html):
    """Return (text_html, text_plain) from a reflexion block.

    Primary strategy: pick the <td> with the largest colspan per row
    (handles AA15 colspan=4/5, AA16/17 colspan=3).

    Fallback for AA14 math/table content: when all text cells in a row
    have colspan=1 or =2 (narrow columns), concatenate them all —
    these are mathematical equations or tabular data.
    """
    soup = BeautifulSoup(block_html, "lxml")
    lines = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        line_num = None
        text_td  = None
        max_span = 2

        content_tds = []   # all non-empty, non-linenum tds in this row

        for td in tds:
            raw = td.get_text(strip=True)
            if re.match(r"^\d{1,2}$", raw) and line_num is None:
                line_num = raw
                continue
            has_img = bool(td.find("img"))
            if (not raw or raw == "\xa0") and not has_img:
                continue
            # Skip navigation rows
            if re.search(r"Seite \d.*Inhaltsverzeichnis", raw):
                continue
            cs = int(td.get("colspan", 1))
            # Skip header row (reflexion-number <b> tag)
            b = td.find("b")
            if b and re.match(r"^\d+[a-z]?\.", b.get_text(strip=True)):
                continue
            content_tds.append((cs, td))
            if cs > max_span:
                max_span = cs
                text_td  = td

        if not line_num:
            continue

        if text_td:
            # Normal case: one dominant wide column
            lines.append(_sanitize_td(text_td))
        elif content_tds:
            # Fallback: narrow columns only (math tables, equations in AA14)
            # Concatenate all content cells with a space separator
            parts = [_sanitize_td(td) for _, td in content_tds if _sanitize_td(td)]
            if parts:
                lines.append(" ".join(parts))

    text_html  = "\n".join(l for l in lines if l)
    text_plain = BeautifulSoup(text_html, "lxml").get_text("\n").strip()
    return text_html, text_plain


def parse_page(html):
    """
    Parse one page using NOTIZ boundary comments.

    Returns a list of dicts:
      number, dating, text, text_html,
      continuation (bool), complete (bool)

    Three cases for a reflexion that spans multiple pages:
      Start page:  has NOTIZ-N-A, no NOTIZ-N-E  → complete=False
      Middle page: no NOTIZ markers at all       → continuation=True, number=None
      End page:    has NOTIZ-N-E, no NOTIZ-N-A  → continuation=True, complete=True
    """
    results  = []
    markers  = list(_NOTIZ_RE.finditer(html))
    spans    = [(m.group(1), m.group(2).upper(), m.start(), m.end())
                for m in markers]
    seen_a   = {n for n, k, _, _ in spans if k == "A"}
    seen_e   = {n for n, k, _, _ in spans if k == "E"}

    # ── Middle pages: no NOTIZ markers at all ────────────────────────────────
    # The entire page content belongs to whatever reflexion is currently open.
    # We don't know the number here — process_page resolves it from the DB.
    if not spans:
        text_html, text_plain = _extract_text(html)
        if text_plain:
            results.append(dict(number=None, dating="",
                                text=text_plain, text_html=text_html,
                                continuation=True, complete=False))
        return results

    # ── End pages: -E present but no matching -A ──────────────────────────────
    for num in seen_e - seen_a:
        e_pos = next(s for n, k, s, _ in spans if n == num and k == "E")
        text_html, text_plain = _extract_text(html[:e_pos])
        if text_plain:
            results.append(dict(number=num, dating="",
                                text=text_plain, text_html=text_html,
                                continuation=True, complete=True))

    # ── Start (and single-page) reflexionen ───────────────────────────────────
    for num, kind, a_start, a_end in spans:
        if kind != "A":
            continue
        e_pos    = next((s for n, k, s, _ in spans if n == num and k == "E"), None)
        complete = e_pos is not None
        block    = html[a_end:e_pos] if e_pos else html[a_end:]

        number, dating = _parse_meta(block)
        if not number:
            number = num
        text_html, text_plain = _extract_text(block)
        results.append(dict(number=number, dating=dating,
                            text=text_plain, text_html=text_html,
                            continuation=False, complete=complete))

    # Sort by document order
    def _sort_key(r):
        for n, k, s, _ in spans:
            if n == r["number"] and k == "A":
                return s
        return 0
    results.sort(key=_sort_key)
    return results


# ── Page source: local mirror or live HTTP ────────────────────────────────────

# Retry settings for transient network errors (DNS failures, timeouts, resets).
# Waits: 5s, 10s, 20s, 40s between attempts before giving up on a single page.
_RETRY_DELAYS = [5, 10, 20, 40]


def fetch_page_http(url: str) -> str | None:
    """
    Fetch one page over HTTP.  Returns None on 404; retries on transient errors.
    """
    last_exc = None
    for attempt, wait in enumerate([0] + _RETRY_DELAYS, start=1):
        if wait:
            print(
                f"    network error — retrying in {wait}s "
                f"(attempt {attempt}/{1 + len(_RETRY_DELAYS)}) ...",
                flush=True,
            )
            time.sleep(wait)
        try:
            resp = SESSION.get(url, timeout=30)
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
            resp.encoding = "iso-8859-1"
            return resp.text
        except (requests.exceptions.ConnectionError,
                requests.exceptions.Timeout,
                requests.exceptions.ChunkedEncodingError) as exc:
            last_exc = exc
            continue
    raise RuntimeError(
        f"Failed to fetch {url} after {1 + len(_RETRY_DELAYS)} attempts. "
        f"Last error: {last_exc}"
    ) from last_exc


def read_page_local(path: Path) -> str:
    """Read one page from a local HTTrack mirror (ISO-8859-1 encoding)."""
    return path.read_text(encoding="iso-8859-1", errors="replace")


def iter_volume_pages(volume: int, delay: float, local_root: Path | None = None):
    """
    Yield (page_number, url, html) for every existing page in a volume.

    local_root — if given, read files from the HTTrack mirror at this path.
                 HTTrack stores pages as:
                   <local_root>/www.korpora.org/Kant/aa16/003.html
                 We glob for all ???.html files so gaps in numbering
                 are handled naturally — only files that actually exist
                 are yielded, in numeric order.

    HTTP mode  — fetches pages sequentially; already-missing pages are
                 skipped silently (no consecutive-404 logic needed since
                 the local mode makes it redundant for most users).
    """
    vol_str = f"aa{volume:02d}"

    # ── Local mirror mode ──────────────────────────────────────────────────────
    if local_root is not None:
        # HTTrack mirrors the site under www.korpora.org/Kant/
        vol_dir = local_root / "www.korpora.org" / "Kant" / vol_str
        if not vol_dir.exists():
            print(f"  WARNING: directory not found: {vol_dir}", flush=True)
            return

        # Collect all page files (exactly three-digit names) and sort numerically
        page_files = sorted(
            vol_dir.glob("???.html"),
            key=lambda p: int(p.stem),
        )

        if not page_files:
            print(f"  WARNING: no ???.html files found in {vol_dir}", flush=True)
            return

        for path in page_files:
            page = int(path.stem)
            url  = f"{BASE_URL}/{vol_str}/{path.name}"
            html = read_page_local(path)
            yield page, url, html
        return

    # ── HTTP mode ─────────────────────────────────────────────────────────────
    lo, hi      = VOLUME_RANGES.get(volume, (1, 1000))
    consecutive = 0
    _MAX_CONSECUTIVE_404 = 20

    for page in range(lo, hi + 1):
        url = f"{BASE_URL}/{vol_str}/{page:03d}.html"
        try:
            html = fetch_page_http(url)
        except RuntimeError as exc:
            print(f"  WARNING: skipping p.{page:04d} after repeated failures: {exc}",
                  flush=True)
            continue

        if html is None:
            consecutive += 1
            if consecutive >= _MAX_CONSECUTIVE_404:
                print(
                    f"  Volume {volume}: {_MAX_CONSECUTIVE_404} consecutive 404s "
                    f"ending at page {page} — stopping.",
                    flush=True,
                )
                break
            continue

        consecutive = 0
        yield page, url, html
        time.sleep(delay)


# ── Database ───────────────────────────────────────────────────────────────────

def init_db(path: str) -> sqlite3.Connection:
    con = sqlite3.connect(path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("""
        CREATE TABLE IF NOT EXISTS reflexionen (
            number      TEXT PRIMARY KEY,
            volume      INTEGER,
            page_start  INTEGER,
            page_end    INTEGER,
            dating_raw  TEXT,
            date_from   INTEGER,
            date_to     INTEGER,
            source_raw  TEXT,
            note_raw    TEXT,
            text        TEXT,
            text_html   TEXT,
            url_start   TEXT,
            source_url  TEXT,
            brief_url   TEXT
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS scrape_progress (
            volume  INTEGER,
            page    INTEGER,
            PRIMARY KEY (volume, page)
        )
    """)
    con.commit()
    return con


def page_already_scraped(con: sqlite3.Connection, volume: int, page: int) -> bool:
    return con.execute(
        "SELECT 1 FROM scrape_progress WHERE volume=? AND page=?", (volume, page)
    ).fetchone() is not None


def mark_page_scraped(con: sqlite3.Connection, volume: int, page: int):
    con.execute(
        "INSERT OR IGNORE INTO scrape_progress(volume, page) VALUES (?,?)", (volume, page)
    )


def upsert_reflexion(con: sqlite3.Connection, rec: dict):
    """Insert a new Reflexion, or append text/html if it spans a page break."""
    existing = con.execute(
        "SELECT text, text_html FROM reflexionen WHERE number=?", (rec["number"],)
    ).fetchone()

    if existing is None:
        con.execute(
            """INSERT INTO reflexionen
               (number, volume, page_start, page_end,
                dating_raw, date_from, date_to,
                source_raw, note_raw, text, text_html, url_start, source_url, brief_url)
               VALUES
               (:number, :volume, :page_start, :page_end,
                :dating_raw, :date_from, :date_to,
                :source_raw, :note_raw, :text, :text_html, :url_start, :source_url, :brief_url)
            """,
            rec,
        )
    else:
        # Continuation across a page break — append both fields
        combined_text = ((existing[0] or "") + "\n" + (rec["text"]      or "")).strip()
        combined_html = ((existing[1] or "") + "\n" + (rec["text_html"] or "")).strip()
        con.execute(
            """UPDATE reflexionen
               SET text=?, text_html=?, page_end=?
               WHERE number=?""",
            (combined_text, combined_html, rec["page_end"], rec["number"]),
        )


# ── Page processor ─────────────────────────────────────────────────────────────

def process_page(reflexionen: list[dict], volume: int, page: int, url: str,
                 con: sqlite3.Connection):
    """
    Write the list of reflexion dicts from parse_page() into the database.

    Each dict has: number, dating, text, text_html,
                   continuation (bool), complete (bool).
    """
    for r in reflexionen:
        if r["continuation"]:
            # Determine which reflexion this continuation belongs to.
            # If number is None (middle page, no NOTIZ markers), find the most
            # recently inserted reflexion for this volume that is still open
            # (page_end == page_start, i.e. hasn't been closed by an -E yet).
            # If number is known (-E page), use it directly.
            if r["number"] is None:
                row = con.execute(
                    """SELECT number FROM reflexionen
                       WHERE volume=? AND page_start = page_end
                       ORDER BY page_start DESC, rowid DESC LIMIT 1""",
                    (volume,),
                ).fetchone()
            else:
                row = (r["number"],)

            if row and r["text"]:
                existing = con.execute(
                    "SELECT text, text_html FROM reflexionen WHERE number=?",
                    (row[0],)
                ).fetchone()
                if existing:
                    combined_text = ((existing[0] or "") + "\n" + r["text"]).strip()
                    combined_html = ((existing[1] or "") + "\n" + r["text_html"]).strip()
                    con.execute(
                        """UPDATE reflexionen
                           SET text=?, text_html=?, page_end=?
                           WHERE number=?""",
                        (combined_text, combined_html, page, row[0]),
                    )
            continue

        # Source and location data come exclusively from the provenienzen tables.
        # Reflexionen not in the table (variant 'a'-suffix numbers, manuscript
        # sources) have source_raw / note_raw left as None.
        prov = PROVENIENZEN.get(r["number"])
        if prov:
            source_raw = expand_source_abbr(prov["source_raw"])
            note_raw   = prov["note_raw"]
            url_start  = prov["url_start"] or url
            source_url = (prov.get("source_url")
                          or resolve_source_url(source_raw, note_raw))
            brief_url  = prov.get("brief_url") or None
        else:
            source_raw = None
            note_raw   = None
            url_start  = url
            source_url = None
            brief_url  = None

        date_from, date_to = parse_dating(
            r["dating"],
            note_raw=note_raw or "",
            source_raw=source_raw or "",
        )

        upsert_reflexion(con, {
            "number":     r["number"],
            "volume":     volume,
            "page_start": page,
            "page_end":   page,
            "dating_raw": r["dating"],
            "date_from":  date_from,
            "date_to":    date_to,
            "source_raw": source_raw,
            "note_raw":   note_raw,
            "text":       r["text"],
            "text_html":  r["text_html"],
            "url_start":  url_start,
            "source_url": source_url,
            "brief_url":  brief_url,
        })


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Parse Kant Reflexionen into SQLite from a local mirror or live HTTP",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--local", metavar="DIR", default="schriften",
        help=(
            "Path to the HTTrack mirror root (default: schriften). "
            "Reads HTML files from disk instead of fetching over HTTP. "
            "The mirror must contain www.korpora.org/Kant/aa16/ etc. "
            "Pass an empty string to force HTTP mode: --local \"\""
        ),
    )
    ap.add_argument(
        "--volumes", nargs="+", type=int,
        default=list(VOLUME_RANGES.keys()), metavar="N",
        help="AA volume numbers to process (default: 14 15 16 17 18 19)",
    )
    ap.add_argument(
        "--delay", type=float, default=0.5,
        help="Seconds between HTTP requests; ignored when --local is used (default: 0.5)",
    )
    ap.add_argument(
        "--db", default="kant_reflexionen.db",
        help="Output SQLite database path (default: kant_reflexionen.db)",
    )
    ap.add_argument(
        "--resume", action="store_true",
        help="Skip pages already recorded in scrape_progress",
    )
    ap.add_argument(
        "--provenienzen", metavar="DIR",
        default=str(Path(__file__).parent / "provenienzen"),
        help=(
            "Path to directory containing L-notizen.html, M-notizen.html etc. "
            "(default: provenienzen/ next to this script)"
        ),
    )
    args = ap.parse_args()

    # Load provenienzen lookup table
    prov_dir = Path(args.provenienzen)
    if not prov_dir.exists():
        print(f"Warning: provenienzen directory not found: {prov_dir} — "
              f"source_raw/note_raw will be NULL for all reflexionen.",
              file=sys.stderr)
    else:
        global PROVENIENZEN
        PROVENIENZEN = load_provenienzen(prov_dir)
        print(f"Loaded {len(PROVENIENZEN)} provenienzen entries from {prov_dir}")

    local_root = Path(args.local) if args.local else None
    if local_root is not None and not local_root.exists():
        print(f"Warning: --local directory '{local_root}' not found — falling back to HTTP", file=sys.stderr)
        local_root = None
    if local_root is not None:
        print(f"Using local mirror: {local_root.resolve()}")
    else:
        print("Using live HTTP (no local mirror)")

    con = init_db(args.db)
    total = 0

    for vol in args.volumes:
        if vol not in VOLUME_RANGES:
            print(f"Warning: volume {vol} not in known range, skipping.", file=sys.stderr)
            continue

        print(f"\n── Volume AA{vol:02d} ──────────────────────────────")
        vol_new = 0

        for page, url, html in iter_volume_pages(vol, args.delay, local_root):
            if args.resume and page_already_scraped(con, vol, page):
                continue

            before = con.execute("SELECT COUNT(*) FROM reflexionen").fetchone()[0]

            items = parse_page(html)
            process_page(items, vol, page, url, con)

            after = con.execute("SELECT COUNT(*) FROM reflexionen").fetchone()[0]
            new   = after - before

            mark_page_scraped(con, vol, page)
            con.commit()

            vol_new += new
            total    = after

            if new:
                print(f"  p.{page:04d}  +{new} reflexionen  (total in DB: {total})")
            elif page % 10 == 0:
                print(f"  p.{page:04d}  …", flush=True)

        print(f"  Volume AA{vol:02d} done — {vol_new} new entries")

    print(f"\n✓ Finished.  Total reflexionen in DB: {total}")
    print(f"  Database: {Path(args.db).resolve()}")

    summary = con.execute(
        "SELECT volume, COUNT(*) FROM reflexionen GROUP BY volume ORDER BY volume"
    ).fetchall()
    print("\n  Volume | Count")
    print("  -------+------")
    for r in summary:
        print(f"  AA{r[0]:02d}   | {r[1]}")

    con.close()


if __name__ == "__main__":
    main()
