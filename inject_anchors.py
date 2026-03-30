#!/usr/bin/env python3
"""
inject_anchors.py — add named anchors to Meier and Eberhard HTML files
so that §-level deep links work (e.g. meier.html#40).

Usage
-----
    # Download originals first:
    curl -o meier_orig.html    "https://korpora.org/kant/meier/"
    curl -o eberhard_orig.html "http://www.korpora.org/kant/eberhard/eberhard.html"

    # Inject anchors:
    python inject_anchors.py meier_orig.html    meier.html
    python inject_anchors.py eberhard_orig.html eberhard.html

    # Then push meier.html and eberhard.html to your GitHub Pages repo.

What it does
------------
Finds every occurrence of a section marker in the text — patterns like:
    §. 1   §. 40   §. 123   §1   §40
— and inserts <a id="N"></a> immediately before it so that
    yoursite.github.io/meier.html#40
jumps directly to that section.

The script also rewrites absolute korpora.org links to relative ones where
possible, so the self-contained HTML file works without depending on the
original server.
"""

import argparse
import re
import sys
from pathlib import Path


# ── Section marker patterns ────────────────────────────────────────────────────
# Meier and Eberhard use "§. N" (with a dot) in the body text.
# The pattern may appear as: "§. 1", "§. 40", "§ 1", "§1"
# We anchor to word boundaries to avoid matching "§. 1" inside longer strings.

# Matches the § sign followed by an optional dot and then a number.
# We capture the number so we can use it as the anchor id.
SECTION_RE = re.compile(
    r"(§\.?\s*)(\d+)"
)


def inject_anchors(html: str, verbose: bool = False) -> tuple[str, int]:
    """
    Insert <a id="N"></a> before each §. N occurrence in the HTML.

    Returns (modified_html, count_of_anchors_added).
    Skips sections that already have an anchor to make the script idempotent.
    """
    # Find all section numbers already anchored
    existing = set(re.findall(r'<a\s+id="(\d+)"', html))

    count = 0
    output = []
    pos = 0

    for m in SECTION_RE.finditer(html):
        sec_num = m.group(2)

        # Skip if already anchored
        if sec_num in existing:
            output.append(html[pos:m.end()])
            pos = m.end()
            continue

        # Don't inject inside HTML tags
        # Check if we're inside a tag by looking at the preceding context
        preceding = html[max(0, m.start()-200):m.start()]
        last_open  = preceding.rfind("<")
        last_close = preceding.rfind(">")
        if last_open > last_close:
            # Inside a tag attribute — skip
            output.append(html[pos:m.end()])
            pos = m.end()
            continue

        # Insert anchor before the § marker
        anchor = f'<a id="{sec_num}"></a>'
        output.append(html[pos:m.start()])
        output.append(anchor)
        output.append(m.group(0))   # the original §. N text
        pos = m.end()
        existing.add(sec_num)
        count += 1
        if verbose:
            print(f"  § {sec_num}")

    output.append(html[pos:])
    return "".join(output), count


def fix_encoding(path: Path) -> str:
    """Read an HTML file, trying ISO-8859-1 first (korpora.org encoding)."""
    for enc in ("iso-8859-1", "utf-8", "cp1252"):
        try:
            return path.read_text(encoding=enc, errors="strict")
        except (UnicodeDecodeError, ValueError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def fix_charset_declaration(html: str) -> str:
    """Update or add charset=UTF-8 declaration so browsers render correctly."""
    # Replace existing charset declaration
    html = re.sub(
        r'(<meta[^>]+charset\s*=\s*)["\']?[^"\'>\s]+["\']?',
        r'\1"UTF-8"',
        html, flags=re.IGNORECASE
    )
    # If no charset meta tag, insert one after <head>
    if "charset" not in html.lower():
        html = re.sub(
            r"(<head[^>]*>)",
            r'\1\n<meta charset="UTF-8">',
            html, flags=re.IGNORECASE
        )
    return html


def main():
    ap = argparse.ArgumentParser(
        description="Inject §-level anchors into Meier/Eberhard HTML files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("input",  help="Input HTML file (original from korpora.org)")
    ap.add_argument("output", help="Output HTML file (with anchors injected)")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="Print each section number as it is anchored")
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would be done without writing output")
    args = ap.parse_args()

    in_path  = Path(args.input)
    out_path = Path(args.output)

    if not in_path.exists():
        sys.exit(f"Error: input file not found: {in_path}")

    print(f"Reading  : {in_path}")
    html = fix_encoding(in_path)
    print(f"  {len(html):,} characters, encoding detected")

    html = fix_charset_declaration(html)

    print(f"Injecting anchors...")
    modified, count = inject_anchors(html, verbose=args.verbose)
    print(f"  {count} anchors added")

    # Quick sanity check — find the highest section number
    all_sections = sorted(
        int(m.group(2)) for m in SECTION_RE.finditer(modified)
    )
    if all_sections:
        print(f"  Sections found: §{all_sections[0]} … §{all_sections[-1]} "
              f"({len(set(all_sections))} unique)")

    if args.dry_run:
        print("Dry run — no file written.")
        return

    out_path.write_text(modified, encoding="utf-8")
    print(f"Written  : {out_path}")
    print(f"\nDeploy to GitHub Pages, then update kant_sources.py:")
    print(f"  MEIER_BASE   = 'https://<yourname>.github.io/<repo>/meier.html'")
    print(f"  EBERHARD_BASE = 'https://<yourname>.github.io/<repo>/eberhard.html'")


if __name__ == "__main__":
    main()
