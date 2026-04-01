#!/usr/bin/env python3
"""
inject_anchors.py — inject §-level (#N) and page-level (#pN) anchors
into korpora.org Kant source text HTML files.

Each source file has a slightly different HTML structure. Rather than
using command-line flags, this script has a hardcoded table that maps
each filename to the correct parsing logic.

Usage
-----
    python inject_anchors.py meier/vernunftlehre_1.html   out/meier/vernunftlehre_1.html
    python inject_anchors.py agb-metaphysica/II1Ba.html   out/agb-metaphysica/II1Ba.html
    python inject_anchors.py achenwall/achenwall_2.html   out/achenwall/achenwall_2.html

    # Or process a whole directory:
    python inject_anchors.py --dir meier/              out/meier/
    python inject_anchors.py --dir agb-metaphysica/    out/agb-metaphysica/
    python inject_anchors.py --dir achenwall/          out/achenwall/

Anchor formats
--------------
  #N   — section anchor  <a id="N"></a>  before the § heading
  #pN  — page anchor     <a id="pN"></a> before the page marker

File table (hardcoded logic per filename)
------------------------------------------
  meier/vernunftlehre_1.html   §: <h3>§. N</h3>     page: <font 696969>[N]</font>
  meier/vernunftlehre_2.html   same
  eberhard/eberhard.html       §: <h3>N</h3>         page: <font 696969>[N]</font>
  agb-metaphysica/*.html       §: already present    page: <font 696969>[N]</font>
  agb-initia/index.html        §: <p center>&#167;.N page: <font 696969>[N]</font>
  achenwall/achenwall_2.html   §: <center>§. N</center>  page: <font 696969>[N]</font>
  achenwall/achenwall_3.html   same
  achenwall/achenwall_1.html   table of contents — skip
  achenwall/index.html         table of contents — skip

In kant_sources.py, source_url logic:
  source_raw contains §  → #N  (section anchor)
  source_raw bare number → #pN (page anchor)
"""

import argparse
import re
import sys
from pathlib import Path


# ── Per-file configuration table ──────────────────────────────────────────────
#
# Maps filename stem (or stem pattern) to a config dict:
#   section_re  : compiled regex matching the § heading to anchor, or None
#   pages_only  : True = skip section anchors (already present)
#   skip        : True = do not process this file at all

# § appears as literal §, &#167;, or &sect; depending on how the file was saved
_SEC = r'(?:§|&#167;|&sect;)'


def _meier_section_re():
    # <h3 align="center"> §. N. </h3>
    # Returns (regex, sec_group) — sec_group is the capture group index for the § number
    return re.compile(
        rf'(<h3\b[^>]*>)\s*{_SEC}\.?\s*(\d+)[^<]*</h3>',
        re.IGNORECASE | re.DOTALL,
    ), 2

def _eberhard_section_re():
    # <h3>N</h3>  — bare number only, no § sign
    return re.compile(r'(<h3\b[^>]*>)\s*(\d+)\s*</h3>', re.IGNORECASE), 2

def _initia_section_re():
    # <p align="center"> §. N </p>   (§ may appear as &#167; or &sect; or literal)
    return re.compile(
        rf'(<p\b[^>]*align\s*=\s*["\']?center["\']?[^>]*>)\s*{_SEC}\.?\s*(\d+)[^<]*</p>',
        re.IGNORECASE,
    ), 2

def _achenwall_section_re():
    # <center>§. N.</center>  (§ may appear as &#167; or &sect; or literal)
    return re.compile(
        rf'<center>\s*{_SEC}\.?\s*(\d+)\.?\s*</center>',
        re.IGNORECASE,
    ), 1

# Filename → config
# Keys are the filename stem (case-insensitive); '*' means "all others in dir"
# Each entry: section_re is (compiled_regex, sec_group_number) or None
# sec_group_number: which capture group holds the § number (1 for Achenwall, 2 for others)
FILE_TABLE = {
    # Meier
    "vernunftlehre_1":  {"section_re": _meier_section_re(),    "pages_only": False, "skip": False},
    "vernunftlehre_2":  {"section_re": _meier_section_re(),    "pages_only": False, "skip": False},
    # Eberhard
    "eberhard":         {"section_re": _eberhard_section_re(), "pages_only": False, "skip": False},
    # Baumgarten Metaphysica — § anchors already present, add pages only
    "i":                {"section_re": None, "pages_only": True, "skip": False},
    "ii1a":             {"section_re": None, "pages_only": True, "skip": False},
    "ii1ba":            {"section_re": None, "pages_only": True, "skip": False},
    "ii1bb":            {"section_re": None, "pages_only": True, "skip": False},
    "ii2":              {"section_re": None, "pages_only": True, "skip": False},
    "ii3a":             {"section_re": None, "pages_only": True, "skip": False},
    "ii3ba":            {"section_re": None, "pages_only": True, "skip": False},
    "ii3bb":            {"section_re": None, "pages_only": True, "skip": False},
    "ii4":              {"section_re": None, "pages_only": True, "skip": False},
    # Baumgarten Initia
    "index":            {"section_re": _initia_section_re(),   "pages_only": False, "skip": False},
    # Achenwall — only files 2 and 3 have the actual § sections Kant annotated
    "achenwall_2":      {"section_re": _achenwall_section_re(), "pages_only": False, "skip": False},
    "achenwall_3":      {"section_re": _achenwall_section_re(), "pages_only": False, "skip": False},
    # Table of contents / auxiliary files — skip
    "achenwall_1":      {"section_re": None, "pages_only": False, "skip": True},
    "achenwall_index":  {"section_re": None, "pages_only": False, "skip": True},
    "synopsis":         {"section_re": None, "pages_only": False, "skip": True},
    "b-index":          {"section_re": None, "pages_only": False, "skip": True},
    "auditori-benevolo":{"section_re": None, "pages_only": False, "skip": True},
    "praefatio-editionis-ii":      {"section_re": None, "pages_only": False, "skip": True},
    "praefatio-editionis-tertiae": {"section_re": None, "pages_only": False, "skip": True},
}

def get_config(path: Path) -> dict:
    """Look up the processing config for a given file path."""
    stem = path.stem.lower()
    # Special case: achenwall/index.html shares stem "index" with initia
    # disambiguate by parent directory name
    if stem == "index" and "achenwall" in str(path).lower():
        return FILE_TABLE.get("achenwall_index", {"skip": True})
    return FILE_TABLE.get(stem, {"section_re": None, "pages_only": True, "skip": False})


# ── Page marker pattern (same for all files) ───────────────────────────────────
# <font color="696969">[N]</font>

PAGE_RE = re.compile(
    r'(<font\b[^>]*color\s*=\s*["\']?696969["\']?[^>]*>)'
    r'\[(\d+)\]'
    r'(</font>)',
    re.IGNORECASE,
)


# ── Core injection functions ───────────────────────────────────────────────────

def inject_page_anchors(html: str, verbose: bool = False) -> tuple[str, int]:
    """Insert <a id="pN"></a> immediately before each [N] page marker. Idempotent."""
    existing = set(re.findall(r'<a\s+id="p(\d+)"', html))
    out, pos, count = [], 0, 0
    for m in PAGE_RE.finditer(html):
        page = m.group(2)
        if page in existing:
            out.append(html[pos:m.end()]); pos = m.end(); continue
        out.append(html[pos:m.start()])
        out.append(f'<a id="p{page}"></a>')
        out.append(m.group(0))
        pos = m.end()
        existing.add(page); count += 1
        if verbose: print(f"    page p{page}")
    out.append(html[pos:])
    return "".join(out), count


def inject_section_anchors(html: str, section_re_tuple, verbose: bool = False) -> tuple[str, int]:
    """
    Insert <a id="N"></a> before each section heading.
    section_re_tuple: (compiled_regex, sec_group) from FILE_TABLE.
    Idempotent.
    """
    section_re, sec_group = section_re_tuple
    existing = set(re.findall(r'<a\s+id="(\d+)"', html))
    out, pos, count = [], 0, 0
    for m in section_re.finditer(html):
        sec = m.group(sec_group)
        if sec in existing:
            out.append(html[pos:m.end()]); pos = m.end(); continue
        out.append(html[pos:m.start()])
        out.append(f'<a id="{sec}"></a>')
        out.append(m.group(0))
        pos = m.end()
        existing.add(sec); count += 1
        if verbose: print(f"    § {sec}")
    out.append(html[pos:])
    return "".join(out), count


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


def process_file(in_path: Path, out_path: Path, verbose: bool, dry_run: bool):
    cfg = get_config(in_path)

    if cfg.get("skip"):
        print(f"  Skipping : {in_path.name}  (table of contents / auxiliary)")
        return

    print(f"\n  Reading  : {in_path}")
    html = read_html(in_path)
    html = fix_charset_declaration(html)

    # Page anchors
    html, pc = inject_page_anchors(html, verbose=verbose)
    print(f"    page anchors added : {pc}")

    # Section anchors
    sc = 0
    if not cfg["pages_only"] and cfg.get("section_re"):
        html, sc = inject_section_anchors(html, cfg["section_re"], verbose=verbose)
        print(f"    section anchors added: {sc}")
    elif cfg["pages_only"]:
        print(f"    section anchors: skipped (already present)")

    # Sanity summary
    all_pages = sorted(int(n) for n in re.findall(r'<a\s+id="p(\d+)"', html))
    all_secs  = sorted(int(n) for n in re.findall(r'<a\s+id="(\d+)"', html))
    if all_pages:
        print(f"    pages:    p{all_pages[0]}…p{all_pages[-1]}  ({len(all_pages)} total)")
    if all_secs:
        print(f"    sections: §{all_secs[0]}…§{all_secs[-1]}  ({len(all_secs)} total)")

    if dry_run:
        print(f"    dry run — not written")
        return

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"    Written  : {out_path}")


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Inject §-level (#N) and page-level (#pN) anchors into "
                    "korpora.org Kant source text HTML files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    ap.add_argument("input",  help="Input HTML file or directory (with --dir)")
    ap.add_argument("output", help="Output HTML file or directory")
    ap.add_argument("--dir",      action="store_true",
                    help="Process all *.html files in input directory")
    ap.add_argument("--verbose",  "-v", action="store_true",
                    help="Print each anchor as it is injected")
    ap.add_argument("--dry-run",  action="store_true",
                    help="Show what would be done without writing files")
    args = ap.parse_args()

    if args.dir:
        in_dir  = Path(args.input)
        out_dir = Path(args.output)
        if not in_dir.is_dir():
            sys.exit(f"Error: not a directory: {in_dir}")
        files = sorted(in_dir.glob("*.html"))
        if not files:
            sys.exit(f"Error: no *.html files in {in_dir}")
        print(f"Processing {len(files)} files: {in_dir} → {out_dir}")
        for f in files:
            process_file(f, out_dir / f.name,
                         verbose=args.verbose, dry_run=args.dry_run)
    else:
        process_file(Path(args.input), Path(args.output),
                     verbose=args.verbose, dry_run=args.dry_run)

    print("\nDone.")


if __name__ == "__main__":
    main()
