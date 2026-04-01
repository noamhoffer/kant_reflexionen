"""
kant_sources.py
===============
Resolves Adickes source abbreviations (L, M, Pr, Th, J …) to:
  - a human-readable full title
  - a direct URL into the anchor-injected source texts hosted on GitHub Pages

All source texts are hosted at SOURCE_BASE with the same directory
structure as korpora.org:

    SOURCE_BASE/meier/vernunftlehre_1.html    §§ 1–284
    SOURCE_BASE/meier/vernunftlehre_2.html    §§ 285–563
    SOURCE_BASE/eberhard/eberhard.html
    SOURCE_BASE/agb-metaphysica/II1Ba.html    (and the other 8 files)
    SOURCE_BASE/agb-initia/index.html
    SOURCE_BASE/achenwall/achenwall_2.html    §§ 85–208
    SOURCE_BASE/achenwall/achenwall_3.html    §§ 209–288

Each file has two anchor types (added by inject_anchors.py):
    #N   — section anchor  (§ number)
    #pN  — page anchor     (page number in Kant's copy)

source_raw comes from the provenienzen tables and contains the page number
in Kant's copy (e.g. "L 18").  note_raw contains the § reference when known
(e.g. "Neben L §. 66-68").  The resolver prefers the § number from note_raw
for a section anchor, and falls back to the page number for a page anchor.

Usage
-----
    from kant_sources import resolve_source_url, full_title

    url   = resolve_source_url("L 18", "Neben L §. 66-68")  # → meier/...#66
    url   = resolve_source_url("M 196", "Neben M §. 554")   # → agb-metaphysica/...#554
    url   = resolve_source_url("L 18")                       # → meier/...#p18
    title = full_title("M 196")
"""

import re

# ── Full titles ────────────────────────────────────────────────────────────────

SOURCE_FULL_TITLES: dict[str, str] = {
    "L":   "Georg Friedrich Meier: Auszug aus der Vernunftlehre (Halle, 1752)",
    "M":   "Alexander Gottlieb Baumgarten: Metaphysica, Ed. IV (Halle, 1757)",
    "Pr":  "Alexander Gottlieb Baumgarten: Initia Philosophiae Practicae Primae (Halle, 1760)",
    "Th":  "Johan August Eberhard: Vorbereitung zur natürlichen Theologie (Halle, 1781)",
    "J":   "Gottfried Achenwall: Juris naturalis pars posterior, Ed. V (Göttingen, 1763)",
    "B":   "Immanuel Kant: Beobachtungen über das Gefühl des Schönen und Erhabenen (Handexemplar, 1764)",
    "R V": "Immanuel Kant: Kritik der reinen Vernunft (Handexemplar)",
}

# ── Base URL ───────────────────────────────────────────────────────────────────
# All anchor-injected source texts are served from this root.
# Override by setting SOURCE_BASE before calling resolve_source_url().

SOURCE_BASE = "https://noamhoffer.github.io/kant-sources"

# ── Meier: two-file split ──────────────────────────────────────────────────────
# vernunftlehre_1.html covers §§ 1–284, vernunftlehre_2.html covers §§ 285–563.
_MEIER_SPLIT = 285

# ── Eberhard: single file ──────────────────────────────────────────────────────
# eberhard.html contains §§ 1–74.

# ── Baumgarten Metaphysica: § → HTML file mapping ─────────────────────────────
_METAPHYSICA_SECTIONS: list[tuple[int, str]] = [
    (3,   "I.html"),
    (6,   "II1A.html"),
    (264, "II1Ba.html"),
    (350, "II1Bb.html"),
    (480, "II2.html"),
    (503, "II3A.html"),
    (739, "II3Ba.html"),
    (799, "II3Bb.html"),
    (999, "II4.html"),
]

# Page number → HTML file mapping (from inject_anchors.py output)
_METAPHYSICA_PAGES: list[tuple[int, str]] = [
    (2,   "I.html"),        # p1–p2
    (79,  "II1Ba.html"),    # p3–p79
    (110, "II1Bb.html"),    # p80–p110
    (173, "II2.html"),      # p111–p173
    (292, "II3Ba.html"),    # p174–p292
    (329, "II3Bb.html"),    # p293–p329
    (406, "II4.html"),      # p330–p406
]

def _metaphysica_file(paragraph: int) -> str:
    for max_p, filename in _METAPHYSICA_SECTIONS:
        if paragraph <= max_p:
            return filename
    return "II4.html"

def _metaphysica_page_file(page: int) -> str:
    for max_p, filename in _METAPHYSICA_PAGES:
        if page <= max_p:
            return filename
    return "II4.html"

# ── Achenwall: three-file split ────────────────────────────────────────────────
# achenwall_1.html = table of contents (skipped)
# achenwall_2.html = §§ 85–208
# achenwall_3.html = §§ 209–288
_ACHENWALL_SPLIT = 209   # §§ < 209 → file 2; §§ ≥ 209 → file 3

def _achenwall_file(paragraph: int) -> str:
    return "achenwall_3.html" if paragraph >= _ACHENWALL_SPLIT else "achenwall_2.html"

# ── Paragraph extraction ───────────────────────────────────────────────────────

_PARA_RE = re.compile(
    r"§\.?\s*(\d+)"   # explicit § sign followed by number
    r"|"
    r"\b(\d+)\b"      # bare number (page reference)
)

def _extract_paragraph(text: str) -> int | None:
    m = _PARA_RE.search(text)
    return int(m.group(1) or m.group(2)) if m else None


# ── Main resolver ──────────────────────────────────────────────────────────────

def resolve_source_url(source_raw: str, note_raw: str = "") -> str | None:
    """
    Return a URL into the hosted source text, or None.

    § number from note_raw → section anchor #N
    Bare page number from source_raw → page anchor #pN
    """
    if not source_raw:
        return None

    raw = source_raw.strip()

    # §-number from note_raw takes priority
    sec = _extract_paragraph(note_raw) if note_raw else None

    def has_sec(tail: str) -> bool:
        return bool(re.search(r"§", tail))

    # ── Meier (L) ─────────────────────────────────────────────────────────────
    if raw.startswith("L") and not raw.startswith("L Bl"):
        tail = raw[1:].strip()
        para = sec or _extract_paragraph(tail)
        if para is None:
            return f"{SOURCE_BASE}/meier/vernunftlehre_1.html"
        file   = "vernunftlehre_1.html" if para < _MEIER_SPLIT else "vernunftlehre_2.html"
        anchor = str(para) if (sec or has_sec(tail)) else f"p{para}"
        return f"{SOURCE_BASE}/meier/{file}#{anchor}"

    # ── Baumgarten Metaphysica (M) ────────────────────────────────────────────
    if raw.startswith("M") and not raw.startswith("Ms"):
        tail = raw[1:].strip()
        para = sec or _extract_paragraph(tail)
        if para is None:
            return f"{SOURCE_BASE}/agb-metaphysica/I.html"
        if sec or has_sec(tail):
            # § number → section anchor, use § → file mapping
            file = _metaphysica_file(para)
            return f"{SOURCE_BASE}/agb-metaphysica/{file}#{para}"
        else:
            # Page number → page anchor, use page → file mapping
            file = _metaphysica_page_file(para)
            return f"{SOURCE_BASE}/agb-metaphysica/{file}#p{para}"

    # ── Baumgarten Initia (Pr) ────────────────────────────────────────────────
    if raw.startswith("Pr"):
        tail = raw[2:].strip()
        para = sec or _extract_paragraph(tail)
        base = f"{SOURCE_BASE}/agb-initia/index.html"
        anchor = str(para) if (sec or has_sec(tail)) else f"p{para}"
        return f"{base}#{anchor}" if para else base

    # ── Eberhard (Th) ─────────────────────────────────────────────────────────
    if raw.startswith("Th"):
        tail = raw[2:].strip()
        para = sec or _extract_paragraph(tail)
        base = f"{SOURCE_BASE}/eberhard/eberhard.html"
        anchor = str(para) if (sec or has_sec(tail)) else f"p{para}"
        return f"{base}#{anchor}" if para else base

    # ── Achenwall (J) ─────────────────────────────────────────────────────────
    if raw.startswith("J") and not raw.startswith("J."):
        tail = raw[1:].strip()
        para = sec or _extract_paragraph(tail)
        if para is None:
            return f"{SOURCE_BASE}/achenwall/achenwall_2.html"
        file   = _achenwall_file(para)
        anchor = str(para) if (sec or has_sec(tail)) else f"p{para}"
        return f"{SOURCE_BASE}/achenwall/{file}#{anchor}"

    # ── No online text (B, R V, L Bl., Ms., Brief, etc.) ─────────────────────
    return None


# ── Helpers ────────────────────────────────────────────────────────────────────

def source_abbr(source_raw: str) -> str | None:
    """Extract the leading abbreviation from a source_raw string.
    Returns None for expanded strings like 'Loses Blatt' or 'Manuscript'
    since those don't map to a digitized source text.
    """
    s = source_raw.strip()
    # Reject already-expanded forms so they don't false-match "L" or "M"
    if s.startswith(("Loses Blatt", "Manuscript")):
        return None
    for abbr in ("R V", "L Bl", "Pr", "Th", "Ms", "L", "M", "J", "B"):
        if s.startswith(abbr):
            return abbr
    return None


def full_title(source_raw: str) -> str:
    """Return the full title string for the source, or empty string if unknown."""
    abbr = source_abbr(source_raw or "")
    return SOURCE_FULL_TITLES.get(abbr or "", "")
