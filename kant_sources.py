"""
kant_sources.py
===============
Resolves Adickes source abbreviations (L, M, Pr, Th, J …) to:
  - a human-readable full title
  - a direct URL into the digitized source text on korpora.org,
    with a §-level anchor where the section number is known

All digitized source texts live at https://korpora.org/kant/

Supported sources
-----------------
L    Georg Friedrich Meier, Auszug aus der Vernunftlehre, Halle 1752.
     Single HTML page; §§ addressed as #N anchors.
     URL: https://korpora.org/kant/meier/

M    Alexander Gottlieb Baumgarten, Metaphysica, Ed. IV, 1757.
     Split across 8 HTML files by section; §§ addressed as #N anchors.
     URL: https://korpora.org/kant/agb-metaphysica/<file>.html#N

Pr   Alexander Gottlieb Baumgarten, Initia Philosophiae Practicae, 1760.
     Single HTML page; §§ addressed as #N anchors.
     URL: https://korpora.org/kant/agb-initia/index.html#N

Th   Johan August Eberhard, Vorbereitung zur natürlichen Theologie, 1781.
     Single HTML page; §§ addressed as #N anchors.
     URL: https://korpora.org/kant/eberhard/eberhard.html#N

J    Gottfried Achenwall, Juris naturalis pars posterior, 1763.
     Two HTML files split at §85; §§ addressed as #N anchors.
     URL: https://korpora.org/kant/achenwall/achenwall_1.html#N  (§§ 1–84)
          https://korpora.org/kant/achenwall/achenwall_2.html#N  (§§ 85+)

Usage
-----
    from kant_sources import resolve_source_url, SOURCE_FULL_TITLES

    url   = resolve_source_url("M §. 7")        # → ...agb-metaphysica/II1Ba.html#7
    url   = resolve_source_url("L 1")            # → ...meier/#1
    url   = resolve_source_url("Th")             # → ...eberhard/eberhard.html  (no §)
    title = SOURCE_FULL_TITLES["M"]
"""

import re

# ── Full titles ────────────────────────────────────────────────────────────────

SOURCE_FULL_TITLES: dict[str, str] = {
    "L":   "Georg Friedrich Meier: Auszug aus der Vernunftlehre (Halle, 1752)",
    "M":   "Alexander Gottlieb Baumgarten: Metaphysica, Ed. IV (Halle, 1757)",
    "Pr":  "Alexander Gottlieb Baumgarten: Initia Philosophiae Practicae Primae (Halle, 1760)",
    "Th":  "Johan August Eberhard: Vorbereitung zur natürlichen Theologie (Halle, 1781)",
    "J":   "Gottfried Achenwall: Juris naturalis pars posterior, Ed. V (Göttingen, 1763)",
    "B":   "Immanuel Kant: Beobachtungen über das Gefühl des Schönen und Erhabenen "
           "(Handexemplar, 1764) — not digitized online",
    "R V": "Immanuel Kant: Kritik der reinen Vernunft (Handexemplar) — not digitized online",
}

# ── Base URLs ──────────────────────────────────────────────────────────────────

_KORPORA = "https://korpora.org/kant"

# Meier and Eberhard are single-page HTML files with no native §-anchors.
# We host anchor-injected versions on GitHub Pages (see inject_anchors.py).
# Set these to your GitHub Pages URLs once deployed; §-level deep links
# (e.g. meier.html#40) will then work automatically.
# Leave as None to fall back to the korpora.org page-level link.
MEIER_URL    = None   # e.g. "https://yourname.github.io/kant-sources/meier.html"
EBERHARD_URL = None   # e.g. "https://yourname.github.io/kant-sources/eberhard.html"

_BASE: dict[str, str] = {
    "Pr": f"{_KORPORA}/agb-initia/index.html",
}

def _meier_url(paragraph: int | None) -> str:
    base = MEIER_URL or f"{_KORPORA}/meier/"
    return f"{base}#{paragraph}" if paragraph else base

def _eberhard_url(paragraph: int | None) -> str:
    base = EBERHARD_URL or f"{_KORPORA}/eberhard/eberhard.html"
    return f"{base}#{paragraph}" if paragraph else base

# ── Baumgarten Metaphysica: § → HTML file mapping ─────────────────────────────
#
# Derived from the Synopsis (korpora.org/kant/agb-metaphysica/synopsis.html)
# and confirmed from the Index anchor URLs.
#
# Format: list of (max_paragraph, filename) in ascending order.
# resolve_metaphysica_file() walks these in order and returns the first entry
# whose max_paragraph >= requested §.

_METAPHYSICA_SECTIONS: list[tuple[int, str]] = [
    (3,   "I.html"),        # Prolegomena metaphysica §§ 1–3
    (6,   "II1A.html"),     # Ontologia: prolegomena §§ 4–6
    (264, "II1Ba.html"),    # Ontologia: praedicata interna §§ 7–264
    (350, "II1Bb.html"),    # Ontologia: praedicata externa §§ 265–350
    (480, "II2.html"),      # Cosmologia §§ 351–480
    (503, "II3A.html"),     # Psychologia: prolegomena §§ 481–503
    (739, "II3Ba.html"),    # Psychologia: empirica §§ 504–739
    (799, "II3Bb.html"),    # Psychologia: rationalis §§ 740–799
    (999, "II4.html"),      # Theologia naturalis §§ 800–end
]

_METAPHYSICA_BASE = f"{_KORPORA}/agb-metaphysica"


def _metaphysica_file(paragraph: int) -> str:
    """Return the HTML filename for a given Metaphysica § number."""
    for max_p, filename in _METAPHYSICA_SECTIONS:
        if paragraph <= max_p:
            return filename
    return "II4.html"  # fallback: last section


# ── Achenwall: two-file split ──────────────────────────────────────────────────
#
# achenwall_1.html covers the earlier paragraphs (Ius Familiae, beginning of
# Ius Publicum).  The split occurs around §85 based on the section heading
# "IURIS NATURALIS Liber III" opening achenwall_2.html at §85.

_ACHENWALL_SPLIT = 85   # §§ < 85 → file 1; §§ ≥ 85 → file 2

def _achenwall_url(paragraph: int | None) -> str:
    base = f"{_KORPORA}/achenwall"
    if paragraph is None:
        return f"{base}/achenwall_1.html"
    file = "achenwall_1.html" if paragraph < _ACHENWALL_SPLIT else "achenwall_2.html"
    return f"{base}/{file}#{paragraph}"


# ── Paragraph extraction ───────────────────────────────────────────────────────
#
# source_raw examples we must handle:
#   "L 1"           §1 of Meier
#   "L §. 1"        same, explicit §
#   "L §. 1--3"     range: link to first §
#   "M §. 7"        §7 of Metaphysica
#   "M §. 350"      §350
#   "Pr §. 1"       §1 of Initia
#   "Th §. 12"      §12 of Theologia
#   "J §. 85"       §85 of Achenwall
#   "L Bl."         loose leaf, no § — return base URL only
#   "Ms."           manuscript, no URL
#   "M"             no § given — return base URL only

_PARA_RE = re.compile(
    r"§\.?\s*(\d+)"      # explicit § sign followed by number
    r"|"
    r"\b(\d+)\b"         # bare number (Meier-style: "L 1")
)


def _extract_paragraph(after_abbr: str) -> int | None:
    """
    Extract the first paragraph/section number from the part of source_raw
    that follows the abbreviation.  Returns None if none found.
    """
    m = _PARA_RE.search(after_abbr)
    if m:
        return int(m.group(1) or m.group(2))
    return None


# ── Main resolver ──────────────────────────────────────────────────────────────

def resolve_source_url(source_raw: str, note_raw: str = "") -> str | None:
    """
    Return a §-level URL into the digitized source text, or None.

    The §-number is extracted preferentially from note_raw, because source_raw
    often contains a *physical page* in Kant's copy (e.g. "L 18" = page 18),
    while note_raw contains the *section reference* (e.g. "Neben L §. 66-68").

    Parameters
    ----------
    source_raw : str   e.g. "L 18",  "M §. 7",  "Pr §. 12"
    note_raw   : str   e.g. "Neben L §. 66-68",  "Zu M §. 398",  "" (absent)
    """
    if not source_raw:
        return None

    raw = source_raw.strip()

    # §-number from note_raw takes priority over the number in source_raw
    sec = _extract_paragraph(note_raw) if note_raw else None

    # ── Meier (L) ──────────────────────────────────────────────────────────────
    if raw.startswith("L") and not raw.startswith("L Bl"):
        para = sec or _extract_paragraph(raw[1:].strip())
        return _meier_url(para)

    # ── Baumgarten Metaphysica (M) ─────────────────────────────────────────────
    if raw.startswith("M") and not raw.startswith("Ms"):
        para = sec or _extract_paragraph(raw[1:].strip())
        if para is None:
            return f"{_METAPHYSICA_BASE}/I.html"
        return f"{_METAPHYSICA_BASE}/{_metaphysica_file(para)}#{para}"

    # ── Baumgarten Initia (Pr) ────────────────────────────────────────────────
    if raw.startswith("Pr"):
        para = sec or _extract_paragraph(raw[2:].strip())
        base = _BASE["Pr"]
        return f"{base}#{para}" if para else base

    # ── Eberhard Theologia (Th) ───────────────────────────────────────────────
    if raw.startswith("Th"):
        para = sec or _extract_paragraph(raw[2:].strip())
        return _eberhard_url(para)

    # ── Achenwall (J) ─────────────────────────────────────────────────────────
    if raw.startswith("J") and not raw.startswith("J."):
        para = sec or _extract_paragraph(raw[1:].strip())
        return _achenwall_url(para)

    # ── Sources not available online ──────────────────────────────────────────
    # B (Beobachtungen Handexemplar), R V (KrV Handexemplar), Ms., L Bl., etc.
    return None


def source_abbr(source_raw: str) -> str | None:
    """Extract the leading abbreviation from a source_raw string."""
    for abbr in ("R V", "L Bl", "Pr", "Th", "Ms", "L", "M", "J", "B"):
        if source_raw.startswith(abbr):
            return abbr
    return None


def full_title(source_raw: str) -> str:
    """Return the full title string for the source, or empty string if unknown."""
    abbr = source_abbr(source_raw or "")
    return SOURCE_FULL_TITLES.get(abbr or "", "")
