#!/usr/bin/env python3
"""
kant_diagnose.py — verify the parser against live pages before a full scrape.

Usage
-----
    python kant_diagnose.py                        # tests a default set of pages
    python kant_diagnose.py --vol 16 --page 169
    python kant_diagnose.py --vol 16 --pages 3 169 320
    python kant_diagnose.py --local C:/schriften --vol 16 --page 169

What it checks
--------------
  1. Fetches / reads the page
  2. Shows all <b> tags and whether the regex matches them
  3. Shows the first non-empty table rows
  4. Runs parse_page() and shows the structured items it produces
  5. Runs a mini end-to-end check: does every header have number, dating, source?
"""

import argparse
import sys
from pathlib import Path

import requests
from bs4 import BeautifulSoup

BASE_URL   = "https://www.korpora.org/Kant"
USER_AGENT = "KantReflexionenBot/1.0 (research)"


# ── Fetch / read ───────────────────────────────────────────────────────────────

def get_html(local: str | None, vol: int, page: int, url: str | None) -> tuple[str, str]:
    """Return (html_text, source_description)."""
    if local:
        root    = Path(local)
        vol_dir = root / "www.korpora.org" / "Kant" / f"aa{vol:02d}"
        if not vol_dir.exists():
            vol_dir = root / "korpora.org" / "Kant" / f"aa{vol:02d}"
        path = vol_dir / f"{page:03d}.html"
        if not path.exists():
            sys.exit(f"File not found: {path}")
        for enc in ("iso-8859-1", "utf-8", "cp1252"):
            try:
                return path.read_text(encoding=enc, errors="strict"), f"{path} [{enc}]"
            except UnicodeDecodeError:
                continue
        return path.read_text(encoding="utf-8", errors="replace"), f"{path} [utf-8 lossy]"

    target = url or f"{BASE_URL}/aa{vol:02d}/{page:03d}.html"
    print(f"Fetching: {target}")
    resp = requests.get(target, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.encoding = "iso-8859-1"
    return resp.text, target


# ── Section printers ───────────────────────────────────────────────────────────

def show_bold_tags(soup, header_re):
    import re
    bolds = soup.find_all("b")
    print(f"\n── Bold tags ({len(bolds)} total) ──────────────────────────────────")
    for i, b in enumerate(bolds):
        raw = b.get_text(" ", strip=True)
        m   = header_re.match(raw.strip())
        if m:
            print(f"  [{i}] ✓ number={m.group('number')!r}  "
                  f"dating={m.group('dating')!r}  source={m.group('source')!r}")
        else:
            print(f"  [{i}] ✗ no match   repr: {repr(raw[:80])}")


def show_table_rows(soup, n=12):
    print(f"\n── First {n} non-empty table rows ───────────────────────────────────")
    count = 0
    for tr in soup.find_all("tr"):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        cells = [c for c in cells if c.strip()]
        if not cells:
            continue
        marker = " [HAS <b>]" if tr.find("b") else ""
        print(f"  row{marker}:")
        for c in cells[:5]:
            print(f"    {repr(c[:90])}")
        count += 1
        if count >= n:
            break


def show_parse_output(html, source):
    """Import and run the real parse_page() from the parser module."""
    try:
        from kant_reflexionen_parser import parse_page, parse_header, HEADER_RE
    except ImportError as e:
        print(f"\n  ✗ Could not import parser: {e}")
        print("    Make sure kant_reflexionen_parser.py is in the same directory.")
        return

    items = parse_page(html)
    headers = [i for i in items if i["type"] == "header"]
    lines   = [i for i in items if i["type"] == "line"]

    print(f"\n── parse_page() output: {len(items)} items "
          f"({len(headers)} headers, {len(lines)} lines) ───────────────")

    for item in items[:30]:
        if item["type"] == "header":
            d = item["dating"] or "(none)"
            s = item["source"] or "(none)"
            n = item["note"]   or ""
            note_str = f"  note={n!r}" if n else ""
            print(f"  HEADER  #{item['number']}  dating={d!r}  source={s!r}{note_str}")
        else:
            print(f"  line    {item['text'][:75]!r}")
    if len(items) > 30:
        print(f"  ... ({len(items) - 30} more)")

    # ── Quality checks ─────────────────────────────────────────────────────────
    print(f"\n── Quality checks ──────────────────────────────────────────────────")
    issues = 0

    no_dating = [h for h in headers if not h["dating"]]
    no_source = [h for h in headers if not h["source"]]

    if not headers:
        print(f"  ✗ No headers found on this page")
        issues += 1
    else:
        print(f"  ✓ {len(headers)} header(s) found")

    if no_dating:
        print(f"  ⚠  {len(no_dating)} header(s) missing dating: "
              f"{[h['number'] for h in no_dating[:5]]}")
    else:
        print(f"  ✓ All headers have dating")

    if no_source:
        print(f"  ⚠  {len(no_source)} header(s) missing source: "
              f"{[h['number'] for h in no_source[:5]]}")
    else:
        print(f"  ✓ All headers have source")

    if not issues and not no_dating and not no_source:
        print(f"\n  ✓ Page looks good — parser is working correctly")
    else:
        print(f"\n  ✗ Issues found — check output above before scraping")


def diagnose_page(local, vol, page, url=None, rows=12):
    html, source = get_html(local, vol, page, url)
    soup = BeautifulSoup(html, "lxml")

    print(f"\n{'='*70}")
    print(f"Page   : AA{vol:02d} / {page:03d}   source: {source}")

    # Declared charset
    for tag in soup.find_all("meta"):
        cs = tag.get("charset") or tag.get("content", "")
        if "charset" in str(cs).lower() or tag.get("charset"):
            print(f"Charset: {tag}")
            break

    try:
        from kant_reflexionen_parser import HEADER_RE
        show_bold_tags(soup, HEADER_RE)
    except ImportError:
        pass

    show_table_rows(soup, rows)
    show_parse_output(html, source)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Diagnose Kant parser against one or more pages",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--local", default=None,
                    help="HTTrack mirror root (e.g. C:/schriften); omit to fetch from web")
    ap.add_argument("--vol",   type=int, default=16,
                    help="Volume number (default: 16)")
    ap.add_argument("--page",  type=int, default=None,
                    help="Single page number to test")
    ap.add_argument("--pages", type=int, nargs="+", default=None,
                    help="Multiple page numbers to test")
    ap.add_argument("--url",   default=None,
                    help="Full URL to fetch (overrides --vol/--page)")
    ap.add_argument("--rows",  type=int, default=12,
                    help="Number of table rows to display (default: 12)")
    args = ap.parse_args()

    # Decide which pages to test
    if args.url:
        pages = [None]   # url mode: page number irrelevant
        diagnose_page(args.local, args.vol, 0, url=args.url, rows=args.rows)
        return

    if args.page is not None:
        pages = [args.page]
    elif args.pages:
        pages = args.pages
    else:
        # Default: a selection of known-interesting pages across AA16
        pages = [3, 5, 169, 320]
        print(f"No page specified — testing default pages: {pages}")

    for p in pages:
        diagnose_page(args.local, args.vol, p, rows=args.rows)


if __name__ == "__main__":
    main()
