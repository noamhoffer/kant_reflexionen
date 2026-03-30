#!/usr/bin/env python3
"""
kant_browse.py — interactive CLI browser for the Kant Reflexionen database.

Usage
-----
    python kant_browse.py [--db kant_reflexionen.db]

Commands (at the prompt)
------------------------
    <number>            look up reflexion by number, e.g.  1562  or  158a
    n  / next           next reflexion in numeric order
    p  / prev           previous reflexion in numeric order
    s  <term>           search by source abbreviation, e.g.  s L 1  or  s M §. 7
    d  <from> [<to>]    filter by date range, e.g.  d 1769  or  d 1769 1772
    l  / list           show the current result list (after s or d)
    i  / info           database summary
    h  / help           show this help
    q  / quit           exit

Dependencies
------------
    pip install rich        (for coloured output — falls back to plain text if absent)
"""

import argparse
import re
import sqlite3
import sys
from pathlib import Path
from textwrap import fill
from kant_sources import full_title, resolve_source_url

# ── Optional rich import (graceful fallback) ───────────────────────────────────
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    from rich.prompt import Prompt
    RICH = True
    console = Console()
except ImportError:
    RICH = False
    console = None


# ── Source abbreviation lookup — delegates to kant_sources ───────────────────
def resolve_source(source_raw: str) -> str:
    """Return the full title of the source textbook, if known."""
    return full_title(source_raw or "")


# ── Dating phase table (same as parser) ───────────────────────────────────────
PHASE_YEARS = {
    "α1": (1753, 1754), "α2": (1754, 1755),
    "β1": (1752, 1756), "β2": (1758, 1759),
    "γ":  (1760, 1764), "δ":  (1762, 1763),
    "ε":  (1762, 1764), "ζ":  (1764, 1766),
    "η":  (1764, 1768), "θ":  (1766, 1768),
    "ι":  (1766, 1768), "κ":  (1769, 1769),
    "λ":  (1769, 1770), "μ":  (1770, 1771),
    "ν":  (1771, 1771), "ξ":  (1772, 1772),
    "ο":  (1769, 1772), "π":  (1772, 1775),
    "ρ":  (1773, 1775), "σ":  (1774, 1777),
    "τ":  (1775, 1776), "υ":  (1776, 1778),
    "φ":  (1776, 1778), "χ":  (1778, 1779),
    "ψ1": (1780, 1783), "ψ2": (1783, 1784),
    "ψ3": (1785, 1788), "ψ4": (1788, 1789),
    "ω1": (1790, 1791), "ω2": (1792, 1794),
    "ω3": (1794, 1795), "ω4": (1796, 1798),
    "ω5": (1798, 1804),
}


def phases_for_years(year_from: int, year_to: int) -> list[str]:
    """Return Adickes phase codes whose range overlaps [year_from, year_to]."""
    return [
        code for code, (pf, pt) in PHASE_YEARS.items()
        if pf <= year_to and pt >= year_from
    ]


# ── Database helpers ───────────────────────────────────────────────────────────

def open_db(path: str) -> sqlite3.Connection:
    p = Path(path)
    if not p.exists():
        die(f"Database not found: {path}")
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    _migrate(con)
    return con


def _migrate(con: sqlite3.Connection):
    """
    Apply any schema changes introduced after the initial scrape.
    Safe to run on every startup — each step is idempotent.
    """
    # Add source_url column if missing (added after first release)
    cols = {row[1] for row in con.execute("PRAGMA table_info(reflexionen)")}
    if "source_url" not in cols:
        con.execute("ALTER TABLE reflexionen ADD COLUMN source_url TEXT")
        rows = con.execute("SELECT number, source_raw FROM reflexionen").fetchall()
        for number, source_raw in rows:
            url = resolve_source_url(source_raw or "")
            if url:
                con.execute("UPDATE reflexionen SET source_url=? WHERE number=?",
                            (url, number))
        con.commit()
        print("  Migrated DB: added source_url column and backfilled.", flush=True)

    if "text_html" not in cols:
        con.execute("ALTER TABLE reflexionen ADD COLUMN text_html TEXT")
        con.commit()
        print("  Migrated DB: added text_html column (will populate on next scrape).",
              flush=True)


def fetch_one(con: sqlite3.Connection, number: str) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM reflexionen WHERE number = ?", (number,)
    ).fetchone()


def fetch_neighbours(con: sqlite3.Connection, number: str) -> tuple[str | None, str | None]:
    """Return (prev_number, next_number) in the natural sort order of the DB."""
    # Use rowid order which corresponds to scrape order (≈ numeric order)
    row = con.execute("SELECT rowid FROM reflexionen WHERE number=?", (number,)).fetchone()
    if row is None:
        return None, None
    rid = row[0]
    prev_row = con.execute(
        "SELECT number FROM reflexionen WHERE rowid < ? ORDER BY rowid DESC LIMIT 1", (rid,)
    ).fetchone()
    next_row = con.execute(
        "SELECT number FROM reflexionen WHERE rowid > ? ORDER BY rowid ASC  LIMIT 1", (rid,)
    ).fetchone()
    return (prev_row[0] if prev_row else None,
            next_row[0] if next_row else None)


def search_source(con: sqlite3.Connection, term: str) -> list[sqlite3.Row]:
    """Return all reflexionen whose source_raw contains term (case-insensitive)."""
    return con.execute(
        "SELECT * FROM reflexionen WHERE source_raw LIKE ? ORDER BY rowid",
        (f"%{term}%",)
    ).fetchall()


def search_dates(con: sqlite3.Connection, year_from: int, year_to: int) -> list[sqlite3.Row]:
    """Return reflexionen whose date window overlaps [year_from, year_to]."""
    return con.execute(
        """SELECT * FROM reflexionen
           WHERE date_from IS NOT NULL
             AND date_from <= ? AND date_to >= ?
           ORDER BY date_from, rowid""",
        (year_to, year_from)
    ).fetchall()


def db_summary(con: sqlite3.Connection) -> dict:
    total = con.execute("SELECT COUNT(*) FROM reflexionen").fetchone()[0]
    dated = con.execute("SELECT COUNT(*) FROM reflexionen WHERE date_from IS NOT NULL").fetchone()[0]
    vols  = con.execute(
        "SELECT volume, COUNT(*) as c FROM reflexionen GROUP BY volume ORDER BY volume"
    ).fetchall()
    return {"total": total, "dated": dated, "volumes": vols}


# ── Rendering ──────────────────────────────────────────────────────────────────

def die(msg: str):
    if RICH:
        console.print(f"[bold red]Error:[/bold red] {msg}")
    else:
        print(f"Error: {msg}", file=sys.stderr)
    sys.exit(1)


def print_reflexion(row: sqlite3.Row, prev_num: str | None, next_num: str | None):
    """Display a single Reflexion, formatted."""
    source_full = resolve_source(row["source_raw"] or "")
    date_str = ""
    if row["date_from"] and row["date_to"]:
        date_str = f"{row['date_from']}–{row['date_to']}"
        if row["date_from"] == row["date_to"]:
            date_str = str(row["date_from"])

    nav = []
    if prev_num:
        nav.append(f"← {prev_num}")
    nav.append(f"AA {row['volume']}  pp. {row['page_start']}–{row['page_end']}")
    if next_num:
        nav.append(f"{next_num} →")
    nav_str = "   ".join(nav)

    if RICH:
        # Header panel
        header = Text()
        header.append(f"Reflexion {row['number']}", style="bold cyan")
        if row["dating_raw"]:
            header.append(f"   [{row['dating_raw']}]", style="yellow")
        if date_str:
            header.append(f"   {date_str}", style="green")

        meta = Text()
        if row["source_raw"]:
            meta.append(f"Source: ", style="bold")
            meta.append(row["source_raw"], style="magenta")
            if source_full:
                meta.append(f"  ({source_full})", style="dim")
            src_url = (
                row["source_url"]
                if "source_url" in row.keys() and row["source_url"]
                else resolve_source_url(row["source_raw"])
            )
            if src_url:
                meta.append(f"\nOnline text: ", style="bold")
                meta.append(src_url, style="cyan underline")
        if row["note_raw"]:
            meta.append(f"\nLocation: ", style="bold")
            meta.append(row["note_raw"], style="dim")
        meta.append(f"\n{nav_str}", style="dim")

        text_body = (row["text"] or "").strip()
        if not text_body:
            text_body = "[dim](no text recorded)[/dim]"

        console.print()
        console.print(Panel(
            f"{meta}\n\n{text_body}",
            title=header,
            border_style="cyan",
            padding=(0, 2),
        ))
        console.print()

    else:
        sep = "─" * 72
        print(f"\n{sep}")
        dating = f"  [{row['dating_raw']}]" if row["dating_raw"] else ""
        dates  = f"  {date_str}" if date_str else ""
        print(f"Reflexion {row['number']}{dating}{dates}")
        if row["source_raw"]:
            line = f"Source: {row['source_raw']}"
            if source_full:
                line += f"  ({source_full})"
            print(line)
            src_url = (
                row["source_url"]
                if "source_url" in row.keys() and row["source_url"]
                else resolve_source_url(row["source_raw"])
            )
            if src_url:
                print(f"Online text: {src_url}")
        if row["note_raw"]:
            print(f"Location: {row['note_raw']}")
        print(f"{nav_str}")
        print(sep)
        text = (row["text"] or "").strip()
        if text:
            for para in text.split("\n"):
                print(fill(para, width=72) if para.strip() else "")
        else:
            print("(no text recorded)")
        print(sep + "\n")


def print_list(rows: list[sqlite3.Row], title: str, current_page: int = 0,
               page_size: int = 20):
    """Print a paginated list of reflexion summaries."""
    total = len(rows)
    start = current_page * page_size
    end   = min(start + page_size, total)
    page_rows = rows[start:end]

    if RICH:
        t = Table(title=f"{title}  ({total} results, showing {start+1}–{end})",
                  box=box.SIMPLE_HEAVY, show_lines=False,
                  header_style="bold cyan")
        t.add_column("No.",      style="cyan",    width=8)
        t.add_column("Dating",   style="yellow",  width=14)
        t.add_column("Date",     style="green",   width=11)
        t.add_column("Source",   style="magenta", width=16)
        t.add_column("Text (start)",              width=50)
        for r in page_rows:
            date_str = ""
            if r["date_from"] and r["date_to"]:
                date_str = f"{r['date_from']}–{r['date_to']}"
            snippet = (r["text"] or "").replace("\n", " ").strip()[:60]
            t.add_row(
                str(r["number"]),
                r["dating_raw"] or "",
                date_str,
                r["source_raw"] or "",
                snippet,
            )
        console.print(t)
        if total > page_size:
            console.print(
                f"[dim]Page {current_page+1}/{-(-total//page_size)}"
                f" — type [bold]l +[/bold] or [bold]l -[/bold] to page[/dim]"
            )
    else:
        print(f"\n{title}  ({total} results, showing {start+1}–{end})")
        print(f"{'No.':<10} {'Dating':<16} {'Date':<12} {'Source':<18} Text")
        print("─" * 80)
        for r in page_rows:
            date_str = ""
            if r["date_from"] and r["date_to"]:
                date_str = f"{r['date_from']}–{r['date_to']}"
            snippet = (r["text"] or "").replace("\n", " ").strip()[:40]
            print(f"{str(r['number']):<10} {(r['dating_raw'] or ''):<16}"
                  f" {date_str:<12} {(r['source_raw'] or ''):<18} {snippet}")
        if total > page_size:
            print(f"Page {current_page+1}/{-(-total//page_size)}"
                  f" — type 'l +' or 'l -' to page")
        print()


def print_help():
    help_text = """
Commands
────────
  <number>             look up reflexion, e.g.  1562   or  158a
  n  /  next           next reflexion
  p  /  prev           previous reflexion
  s  <term>            search by source, e.g.   s L 1   or   s M §
  d  <from> [<to>]     filter by date,   e.g.   d 1769   or   d 1769 1772
  l  /  list           show current result list
  l +  /  l -          next / previous page of results
  i  /  info           database summary
  h  /  help           this help
  q  /  quit           exit
"""
    if RICH:
        console.print(Panel(help_text.strip(), title="Help", border_style="dim", padding=(0,2)))
    else:
        print(help_text)


def print_info(con: sqlite3.Connection):
    s = db_summary(con)
    if RICH:
        t = Table(title="Database summary", box=box.SIMPLE_HEAVY,
                  header_style="bold cyan", show_lines=False)
        t.add_column("Volume", style="cyan",  justify="right")
        t.add_column("Count",  style="white", justify="right")
        for r in s["volumes"]:
            t.add_row(f"AA {r['volume']}", str(r["c"]))
        t.add_section()
        t.add_row("[bold]Total[/bold]", f"[bold]{s['total']}[/bold]")
        console.print()
        console.print(t)
        console.print(
            f"  [dim]{s['dated']} of {s['total']} reflexionen have date estimates[/dim]\n"
        )
    else:
        print("\nDatabase summary")
        print(f"{'Volume':<10} Count")
        print("─" * 20)
        for r in s["volumes"]:
            print(f"AA {r['volume']:<7} {r['c']}")
        print(f"{'Total':<10} {s['total']}")
        print(f"\n{s['dated']} of {s['total']} reflexionen have date estimates\n")


# ── REPL ───────────────────────────────────────────────────────────────────────

def repl(con: sqlite3.Connection):
    current_number: str | None = None   # last viewed reflexion
    result_list:    list       = []     # last search/filter results
    result_page:    int        = 0
    result_title:   str        = ""

    if RICH:
        console.print(Panel(
            "[bold cyan]Kant Reflexionen Browser[/bold cyan]\n"
            "[dim]Type a reflexion number, or [bold]h[/bold] for help[/dim]",
            border_style="cyan", padding=(0, 2)
        ))
    else:
        print("Kant Reflexionen Browser")
        print("Type a reflexion number, or 'h' for help\n")

    while True:
        try:
            if RICH:
                raw = Prompt.ask("[bold cyan]>[/bold cyan]").strip()
            else:
                raw = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not raw:
            continue

        cmd = raw.lower()
        tokens = raw.split()

        # ── quit ──────────────────────────────────────────────────────────────
        if cmd in ("q", "quit", "exit"):
            break

        # ── help ──────────────────────────────────────────────────────────────
        elif cmd in ("h", "help"):
            print_help()

        # ── info ──────────────────────────────────────────────────────────────
        elif cmd in ("i", "info"):
            print_info(con)

        # ── next / prev ───────────────────────────────────────────────────────
        elif cmd in ("n", "next", "p", "prev"):
            if current_number is None:
                _warn("No reflexion loaded yet. Look one up first.")
                continue
            _, next_n = fetch_neighbours(con, current_number)
            prev_n, _ = fetch_neighbours(con, current_number)
            target = next_n if cmd in ("n", "next") else prev_n
            if target is None:
                _warn("No further reflexion in that direction.")
                continue
            row = fetch_one(con, target)
            if row:
                prev2, next2 = fetch_neighbours(con, target)
                print_reflexion(row, prev2, next2)
                current_number = target

        # ── list / paging ─────────────────────────────────────────────────────
        elif tokens[0].lower() in ("l", "list"):
            if not result_list:
                _warn("No search results yet. Use 's' or 'd' first.")
                continue
            if len(tokens) > 1 and tokens[1] == "+":
                result_page = min(result_page + 1, len(result_list) // 20)
            elif len(tokens) > 1 and tokens[1] == "-":
                result_page = max(result_page - 1, 0)
            print_list(result_list, result_title, result_page)

        # ── source search: s <term> ───────────────────────────────────────────
        elif tokens[0].lower() == "s" and len(tokens) > 1:
            term = " ".join(tokens[1:])
            rows = search_source(con, term)
            if not rows:
                _warn(f"No reflexionen found with source matching '{term}'.")
            else:
                result_list  = rows
                result_page  = 0
                result_title = f"Source search: '{term}'"
                print_list(result_list, result_title)

        # ── date filter: d <from> [<to>] ─────────────────────────────────────
        elif tokens[0].lower() == "d" and len(tokens) >= 2:
            try:
                year_from = int(tokens[1])
                year_to   = int(tokens[2]) if len(tokens) >= 3 else year_from
            except ValueError:
                _warn("Usage: d <year_from> [<year_to>]  e.g.  d 1769  or  d 1769 1772")
                continue
            if year_from > year_to:
                year_from, year_to = year_to, year_from
            rows = search_dates(con, year_from, year_to)
            if not rows:
                _warn(f"No reflexionen with date estimates overlapping {year_from}–{year_to}.")
            else:
                result_list  = rows
                result_page  = 0
                result_title = f"Date filter: {year_from}–{year_to}"
                print_list(result_list, result_title)

        # ── reflexion number lookup ───────────────────────────────────────────
        elif re.match(r"^\d+[a-z]?$", raw):
            row = fetch_one(con, raw)
            if row is None:
                _warn(f"Reflexion {raw} not found in database.")
            else:
                prev_n, next_n = fetch_neighbours(con, raw)
                print_reflexion(row, prev_n, next_n)
                current_number = raw

        else:
            _warn(f"Unknown command: '{raw}'.  Type 'h' for help.")


def _warn(msg: str):
    if RICH:
        console.print(f"[yellow]{msg}[/yellow]")
    else:
        print(f"  {msg}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(
        description="Interactive CLI browser for the Kant Reflexionen database"
    )
    ap.add_argument(
        "--db", default="kant_reflexionen.db",
        help="Path to the SQLite database (default: kant_reflexionen.db)",
    )
    args = ap.parse_args()

    if not RICH:
        print("Note: install 'rich' for coloured output:  pip install rich\n")

    con = open_db(args.db)
    print_info(con)
    repl(con)
    con.close()


if __name__ == "__main__":
    main()
