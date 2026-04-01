#!/usr/bin/env python3
"""
kant_provenienzen.py
====================
Builds a lookup table mapping Adickes reflexion numbers to their source
provenance data (source_raw, note_raw, url_start, source_url, brief_url)
by parsing the korpora.org Provenienzen tables.

Sources included
----------------
  L   Meier, Vernunftlehre
  M   Baumgarten, Metaphysica
  Th  Eberhard, Theologia
  J   Achenwall, Juris naturalis
  Pr  Baumgarten, Initia
  B   Kant's Beobachtungen Handexemplar

Sources NOT included (cross-references, not Kant's personal copies)
  E I, E II, R-Sch, Hb, Ki, etc.

Briefe (AA 14–19 notes written on letters to Kant) are treated as a
separate source category. For each, source_url points to the letter in
AA 10 or AA 11 (the correspondence volumes), and brief_url to the
dedicated briefe.html page.

Usage
-----
    from kant_provenienzen import load_provenienzen

    # path is the directory containing L-notizen.html etc.
    prov = load_provenienzen("path/to/provenienzen/")

    # Lookup a reflexion:
    entry = prov.get("2070")
    # {'source_raw': 'L 18.', 'note_raw': 'Neben L §. 66-68',
    #  'url_start': 'https://korpora.org/kant/aa16/221.html#z02',
    #  'source_url': None, 'brief_url': None}
"""

import re
from pathlib import Path
from bs4 import BeautifulSoup


# ── File → source abbreviation mapping ────────────────────────────────────────

_SOURCE_FILES = {
    "L-notizen.html":  "L",
    "M-notizen.html":  "M",
    "Th-notizen.html": "Th",
    "J-notizen.html":  "J",
    "Pr-notizen.html": "Pr",
    "B-notizen.html":  "B",
}


def _read(path: Path) -> str:
    for enc in ("utf-8", "iso-8859-1", "windows-1252"):
        try:
            return path.read_text(encoding=enc, errors="strict")
        except (UnicodeDecodeError, ValueError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _normalise_url(url: str) -> str:
    """Ensure korpora.org URLs use https."""
    return url.replace("http://www.korpora.org", "https://korpora.org") \
               .replace("http://korpora.org",     "https://korpora.org")


def _parse_notizen(path: Path) -> list[dict]:
    """
    Parse one *-notizen.html table.
    Each row yields:
      number    Adickes number string (e.g. "1562", "158a")
      source_raw  column 2 text  (e.g. "L 18.",  "M 196.")
      note_raw    column 3 text  (e.g. "Neben L §. 66-68")
      url_start   href on the number link  (korpora.org page + line anchor)
    """
    html = _read(path)
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return []

    entries = []
    for row in table.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 4:
            continue

        num_text = tds[1].get_text(strip=True)
        if not re.match(r"^\d+[a-z]?$", num_text):
            continue

        source_raw = tds[2].get_text(" ", strip=True).strip().rstrip(".")
        note_raw   = tds[3].get_text(" ", strip=True).strip()

        link = tds[1].find("a")
        url  = _normalise_url(link.get("href", "")) if link else ""

        entries.append({
            "number":     num_text,
            "source_raw": source_raw,
            "note_raw":   note_raw,
            "url_start":  url,
        })
    return entries


def _parse_briefe(path: Path) -> list[dict]:
    """
    Parse briefe.html.
    Each main entry row looks like:
      col 1: "1343. Bemerkungen Kants auf dem Brief von J. G. Lindner..."
      col 2: links to AA reflexion page, AA10/11 page, briefe page

    Some descriptions begin with a dating string (Greek letters + nbsp)
    before the actual letter description — we strip the dating prefix.

    Returns entries with:
      number      Adickes number
      source_raw  cleaned description (the letter info without dating prefix)
      url_start   link to AA page where the note appears
      source_url  link to AA10/11 (correspondence volumes)
      brief_url   link to korpora.org/kant/briefe/N.html
    """
    html = _read(path)
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if not table:
        return []

    entries = []
    for row in table.find_all("tr"):
        tds = row.find_all("td")
        if len(tds) < 2:
            continue

        text = tds[1].get_text(" ", strip=True)
        m = re.match(r"^(\d+[a-z]?)\.\s+(.+)", text)
        if not m:
            continue

        number = m.group(1)
        desc   = m.group(2).strip()

        # Strip leading dating string (Greek-letter phase code + nbsp separators)
        # e.g. "ρ¹.   Bemerkungen Kants..." → "Bemerkungen Kants..."
        desc = re.sub(
            r"^[αβγδεζηθικλμνξοπρστυφχψω][^\xa0]*\xa0{2,}",
            "", desc
        ).strip()

        links_td = tds[2] if len(tds) > 2 else None
        url_start = source_url = brief_url = ""

        if links_td:
            for a in links_td.find_all("a"):
                href = _normalise_url(a.get("href", ""))
                txt  = a.get_text(strip=True)
                if re.search(r"/aa1[01]/", href):        # AA10 or AA11
                    source_url = href
                elif re.search(r"/briefe/", href):
                    brief_url  = href
                elif re.search(r"/aa\d+/", href):        # The reflexion's AA page
                    url_start  = href

        entries.append({
            "number":     number,
            "source_raw": desc,
            "note_raw":   "",
            "url_start":  url_start,
            "source_url": source_url,
            "brief_url":  brief_url,
        })
    return entries


def load_provenienzen(directory: str | Path) -> dict[str, dict]:
    """
    Parse all provenienzen tables and return a dict mapping
    reflexion number → provenance entry.

    Entry keys:
      source_raw  str   physical location in Kant's copy  (e.g. "L 18")
      note_raw    str   more specific location note       (e.g. "Neben L §. 66-68")
      url_start   str   korpora.org URL of the AA page
      source_url  str | None  URL into the source text (AA10/11 for Briefe)
      brief_url   str | None  URL to briefe.html entry (Briefe only)
      abbr        str   source abbreviation: L / M / Th / J / Pr / B / Brief
    """
    d = Path(directory)
    result: dict[str, dict] = {}

    # ── Standard notizen files ────────────────────────────────────────────────
    for filename, abbr in _SOURCE_FILES.items():
        path = d / filename
        if not path.exists():
            continue
        for entry in _parse_notizen(path):
            num = entry["number"]
            row = {
                "source_raw": entry["source_raw"],
                "note_raw":   entry["note_raw"],
                "url_start":  entry["url_start"],
                "source_url": None,
                "brief_url":  None,
                "abbr":       abbr,
            }
            if num in result:
                # Reflexion appears in two source files (rare: e.g. #784 in M twice)
                # Append both source_raw values
                existing = result[num]
                if entry["source_raw"] and entry["source_raw"] not in existing["source_raw"]:
                    existing["source_raw"] = (
                        existing["source_raw"] + "; " + entry["source_raw"]
                    ).strip("; ")
            else:
                result[num] = row

    # ── Briefe ────────────────────────────────────────────────────────────────
    briefe_path = d / "briefe.html"
    if briefe_path.exists():
        for entry in _parse_briefe(briefe_path):
            num = entry["number"]
            if num in result:
                # Already has a notizen entry — add the brief links to it
                result[num]["source_url"] = entry["source_url"] or result[num]["source_url"]
                result[num]["brief_url"]  = entry["brief_url"]
                result[num]["is_brief"]   = True
            else:
                result[num] = {
                    "source_raw": entry["source_raw"],
                    "note_raw":   entry["note_raw"],
                    "url_start":  entry["url_start"],
                    "source_url": entry["source_url"],
                    "brief_url":  entry["brief_url"],
                    "abbr":       "Brief",
                }

    return result


def build_provenienzen_report(directory: str | Path) -> str:
    """Return a quick summary of what was loaded."""
    prov = load_provenienzen(directory)
    from collections import Counter
    counts = Counter(v["abbr"] for v in prov.values())
    lines = [f"Loaded {len(prov)} provenienzen entries:"]
    for abbr in ["L", "M", "Th", "J", "Pr", "B", "Brief"]:
        if abbr in counts:
            lines.append(f"  {abbr:<6} {counts[abbr]:>5}")
    briefe_with_notes = sum(
        1 for v in prov.values() if v.get("brief_url")
    )
    lines.append(f"  {briefe_with_notes} entries have brief links")
    return "\n".join(lines)
