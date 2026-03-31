#!/usr/bin/env python3
"""
inject_anchors.py — add named anchors to Meier, Eberhard and Baumgarten HTML files
so that both §-level and page-level deep links work.

Two anchor types are injected
------------------------------
  #N   — section anchor: placed before each "§. N" heading  (e.g. #40)
  #pN  — page anchor:    placed before each "[N]" page marker (e.g. #p11)

The Baumgarten Metaphysica files already have § anchors; for those only
page anchors are added (use --pages-only).

Usage
-----
    # Meier (two files):
    python inject_anchors.py meier/vernunftlehre_1.html out/meier/vernunftlehre_1.html
    python inject_anchors.py meier/vernunftlehre_2.html out/meier/vernunftlehre_2.html

    # Eberhard (single file):
    python inject_anchors.py --eberhard eberhard_orig.html out/eberhard.html

    # Baumgarten Metaphysica — page anchors only (§ anchors already present):
    python inject_anchors.py --dir agb-metaphysica/ out/agb-metaphysica/ --pages-only

    Then push the output directories to your GitHub Pages repo.

Anchor formats
--------------
  #N   section anchor — <a id="N"></a> injected before <h3>§. N</h3>
  #pN  page anchor    — <a id="pN"></a> injected before <font color="696969">[N]</font>

In kant_sources.py, source_url resolves as:
  - If source_raw contains a § number → use #N (section anchor)
  - Otherwise (page number only)      → use #pN (page anchor)
"""

import argparse
import re
import sys
from pathlib import Path


# ── Patterns ───────────────────────────────────────────────────────────────────

# Page markers: <font color="696969">[N]</font>
PAGE_RE = re.compile(
    r'(<font\b[^>]*color\s*=\s*["\']?696969["\']?[^>]*>)'
    r'\[(\d+)\]'
    r'(</font>)',
    re.IGNORECASE,
)

# Section headings in Meier/Eberhard: <h3 ...> §. N </h3>
SECTION_H3_RE = re.compile(
    r'(<h3\b[^>]*>)'
    r'[^<]*§\.?\s*(\d+)[^<]*'
    r'</h3>',
    re.IGNORECASE | re.DOTALL,
)

# Section headings in Eberhard: <h3 ...>N</h3>
EBERHARD_SECTION_RE = re.compile(
    r'(<h3\b[^>]*>)\s*(\d+)\s*</h3>',
    re.IGNORECASE,
)


# ── Core injection functions ───────────────────────────────────────────────────

def inject_page_anchors(html: str, verbose: bool = False) -> tuple[str, int]:
    """Insert <a id="pN"></a> before each [N] page marker. Idempotent."""
    existing = set(re.findall(r'<a\s+id="p(\d+)"', html))
    count = 0
    output = []
    pos = 0

    for m in PAGE_RE.finditer(html):
        page_num = m.group(2)
        if page_num in existing:
            output.append(html[pos:m.end()])
            pos = m.end()
            continue
        output.append(html[pos:m.start()])
        output.append(f'<a id="p{page_num}"></a>')
        output.append(m.group(0))
        pos = m.end()
        existing.add(page_num)
        count += 1
        if verbose:
            print(f"  page p{page_num}")

    output.append(html[pos:])
    return "".join(output), count


def inject_section_anchors(html: str, style: str = 'meier', verbose: bool = False) -> tuple[str, int]:
    """Insert <a id="N"></a> before each section heading. Idempotent."""
    if style == 'eberhard':
        section_re = EBERHARD_SECTION_RE
    else:  # meier is default
        section_re = SECTION_H3_RE

    existing = set(re.findall(r'<a\s+id="(\d+)"', html))
    count = 0
    output = []
    pos = 0

    for m in section_re.finditer(html):
        sec_num = m.group(2)
        if sec_num in existing:
            output.append(html[pos:m.end()])
            pos = m.end()
            continue
        output.append(html[pos:m.start()])
        output.append(f'<a id="{sec_num}"></a>')
        output.append(m.group(0))
        pos = m.end()
        existing.add(sec_num)
        count += 1
        if verbose:
            print(f"  § {sec_num}")

    output.append(html[pos:])
    return "".join(output), count


# ── File helpers ───────────────────────────────────────────────────────────────

def read_html(path: Path) -> str:
    for enc in ("iso-8859-1", "utf-8", "cp1252"):
        try:
            return path.read_text(encoding=enc, errors="strict")
        except (UnicodeDecodeError, ValueError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def fix_charset_declaration(html: str) -> str:
    html = re.sub(
        r'(<meta[^>]+charset\s*=\s*)["\']?[^"\'>\s]+["\']?',
        r'\1"UTF-8"', html, flags=re.IGNORECASE,
    )
    if "charset" not in html.lower():
        html = re.sub(r"(<head[^>]*>)", r'\1\n<meta charset="UTF-8">',
                      html, flags=re.IGNORECASE)
    return html


def process_file(in_path: Path, out_path: Path,
                 pages_only: bool, eberhard: bool, verbose: bool, dry_run: bool):
    print(f"\nReading  : {in_path}")
    html = read_html(in_path)
    html = fix_charset_declaration(html)

    html, page_count = inject_page_anchors(html, verbose=verbose)
    print(f"  page anchors added: {page_count}")

    sec_count = 0
    if not pages_only:
        style = 'eberhard' if eberhard else 'meier'
        html, sec_count = inject_section_anchors(html, style=style, verbose=verbose)
        print(f"  section anchors added: {sec_count}")

    # Sanity summary
    all_pages    = sorted(int(n) for n in re.findall(r'<a\s+id="p(\d+)"', html))
    all_sections = sorted(int(n) for n in re.findall(r'<a\s+id="(\d+)"', html))
    if all_pages:
        print(f"  pages:    p{all_pages[0]} … p{all_pages[-1]}  ({len(all_pages)} total)")
    if all_sections:
        print(f"  sections: §{all_sections[0]} … §{all_sections[-1]}  ({len(all_sections)} total)")

    if dry_run:
        print("  dry run — not written")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"Written  : {out_path}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Inject §-level (#N) and page-level (#pN) anchors into "
                    "korpora.org Kant source text HTML files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("input",  nargs="?",
                    help="Input HTML file, or input directory (with --dir)")
    ap.add_argument("output", nargs="?",
                    help="Output HTML file or directory")
    ap.add_argument("--dir", action="store_true",
                    help="Process all *.html files in the input directory")
    ap.add_argument("--pages-only", action="store_true",
                    help="Only inject page anchors (#pN). "
                         "Use for Baumgarten Metaphysica (§ anchors already present).")
    ap.add_argument("--eberhard", action="store_true",
                    help="Use section style for Eberhard's Theologie (h3 with number only)")
    ap.add_argument("--verbose", "-v", action="store_true")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be done without writing files")
    args = ap.parse_args()

    if not args.input:
        ap.error("Provide an input file or directory")

    if args.dir:
        in_dir  = Path(args.input)
        out_dir = Path(args.output) if args.output \
                  else in_dir.parent / (in_dir.name + "_anchored")
        if not in_dir.is_dir():
            sys.exit(f"Error: not a directory: {in_dir}")
        files = sorted(in_dir.glob("*.html"))
        if not files:
            sys.exit(f"Error: no *.html files in {in_dir}")
        print(f"Processing {len(files)} files: {in_dir} → {out_dir}")
        for f in files:
            process_file(f, out_dir / f.name,
                         pages_only=args.pages_only,
                         eberhard=args.eberhard,
                         verbose=args.verbose,
                         dry_run=args.dry_run)
    else:
        if not args.output:
            ap.error("Provide both input and output file paths")
        process_file(Path(args.input), Path(args.output),
                     pages_only=args.pages_only,
                     eberhard=args.eberhard,
                     verbose=args.verbose,
                     dry_run=args.dry_run)

    print("\nDone.")


if __name__ == "__main__":
    main()
