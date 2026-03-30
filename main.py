"""
main.py — FastAPI backend for the Kant Reflexionen web application.

Endpoints
---------
GET  /                          serve the frontend (index.html from /static)
GET  /api/reflexion/{number}    fetch a single reflexion by Adickes number
GET  /api/search                search across fields (query params below)
GET  /api/filter/dates          all reflexionen in a date range
GET  /api/filter/source         all reflexionen for a source abbreviation
GET  /api/stats                 summary counts used by the timeline visualisation
GET  /api/timeline              date-bucketed counts for timeline chart

Search query params (?field=value, all optional, combinable)
------------------------------------------------------------
  q          full-text search across the text body
  source     source abbreviation prefix, e.g. L, M, Pr
  date_from  earliest year (integer)
  date_to    latest year (integer)
  volume     AA volume number (integer)
  page       pagination: page number, 1-based (default 1)
  page_size  results per page (default 20, max 100)

Running locally
---------------
    pip install fastapi uvicorn
    uvicorn main:app --reload

Then open http://localhost:8000 in your browser.

Deploying to Render
-------------------
    Add a render.yaml (provided separately) pointing at this file.
    Set the DB_PATH environment variable to the path of your SQLite file.
"""

import os
import sqlite3
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from kant_sources import resolve_source_url, full_title


# ── Configuration ──────────────────────────────────────────────────────────────

DB_PATH     = os.environ.get("DB_PATH", "kant_reflexionen.db")
STATIC_DIR  = Path(__file__).parent / "static"


# ── App setup ──────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Kant Reflexionen API",
    description="API for browsing and visualising Kant's handwritten Nachlass notes.",
    version="1.0.0",
)

# Allow the frontend dev server (e.g. Vite on :5173) to call this API during
# development.  On Render the frontend is served from /static so CORS is not
# needed in production, but keeping it here causes no harm.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# Serve the compiled frontend from /static if it exists.
# During development the frontend runs on its own dev server.
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ── Database connection ────────────────────────────────────────────────────────

def get_db() -> sqlite3.Connection:
    if not Path(DB_PATH).exists():
        raise HTTPException(
            status_code=503,
            detail=f"Database not found at {DB_PATH}. Run the scraper first.",
        )
    con = sqlite3.connect(DB_PATH, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    return con


# ── Response models ────────────────────────────────────────────────────────────

class ReflexionSummary(BaseModel):
    number:     str
    volume:     Optional[int]
    page_start: Optional[int]
    page_end:   Optional[int]
    dating_raw: Optional[str]
    date_from:  Optional[int]
    date_to:    Optional[int]
    source_raw: Optional[str]
    source_title: Optional[str]   # resolved full title
    note_raw:   Optional[str]
    text_preview: Optional[str]   # first 200 chars of text


class ReflexionDetail(ReflexionSummary):
    text:       Optional[str]
    text_html:  Optional[str]
    url_start:  Optional[str]
    source_url: Optional[str]


class SearchResponse(BaseModel):
    total:    int
    page:     int
    page_size: int
    pages:    int
    results:  list[ReflexionSummary]


class TimelineBucket(BaseModel):
    year:      int
    count:     float   # weighted density (each reflexion contributes 1/range_width)
    count_exact: int   # reflexionen with date_from == date_to == year (certain datings)


class StatsResponse(BaseModel):
    total:          int
    dated:          int
    by_volume:      dict[int, int]
    by_source:      dict[str, int]
    earliest_year:  Optional[int]
    latest_year:    Optional[int]


# ── Helpers ────────────────────────────────────────────────────────────────────

def _row_to_summary(row: sqlite3.Row) -> ReflexionSummary:
    text = row["text"] or ""
    return ReflexionSummary(
        number      = row["number"],
        volume      = row["volume"],
        page_start  = row["page_start"],
        page_end    = row["page_end"],
        dating_raw  = row["dating_raw"],
        date_from   = row["date_from"],
        date_to     = row["date_to"],
        source_raw  = row["source_raw"],
        source_title= full_title(row["source_raw"] or ""),
        note_raw    = row["note_raw"],
        text_preview= text[:200] + ("…" if len(text) > 200 else ""),
    )


def _row_to_detail(row: sqlite3.Row) -> ReflexionDetail:
    src_url = row["source_url"] if "source_url" in row.keys() else None
    if src_url is None:
        src_url = resolve_source_url(row["source_raw"] or "")
    cols = [d[0] for d in row.description] if hasattr(row, "description") else row.keys()
    html_text = row["text_html"] if "text_html" in cols else None
    return ReflexionDetail(
        number      = row["number"],
        volume      = row["volume"],
        page_start  = row["page_start"],
        page_end    = row["page_end"],
        dating_raw  = row["dating_raw"],
        date_from   = row["date_from"],
        date_to     = row["date_to"],
        source_raw  = row["source_raw"],
        source_title= full_title(row["source_raw"] or ""),
        note_raw    = row["note_raw"],
        text_preview= (row["text"] or "")[:200],
        text        = row["text"],
        text_html   = html_text,
        url_start   = row["url_start"],
        source_url  = src_url,
    )


def _paginate(page: int, page_size: int) -> tuple[int, int]:
    """Return (LIMIT, OFFSET) for a given 1-based page number."""
    page      = max(1, page)
    page_size = min(max(1, page_size), 100)
    return page_size, (page - 1) * page_size


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
def root():
    """Serve the frontend SPA, or a placeholder if not yet built."""
    index = STATIC_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {
        "message": "Kant Reflexionen API",
        "docs":    "/docs",
        "note":    "Place your compiled frontend in the /static directory.",
    }


@app.get("/api/reflexion/{number}", response_model=ReflexionDetail,
         summary="Fetch a single reflexion by Adickes number")
def get_reflexion(number: str):
    """
    Returns the full text and all metadata for one reflexion.

    - **number**: Adickes number, e.g. `1562` or `158a`
    """
    con = get_db()
    row = con.execute(
        "SELECT * FROM reflexionen WHERE number = ?", (number,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Reflexion {number} not found.")
    return _row_to_detail(row)


@app.get("/api/search", response_model=SearchResponse,
         summary="Search reflexionen by text, source, date range, or volume")
def search(
    q:         Optional[str] = Query(None,  description="Full-text search in text body"),
    source:    Optional[str] = Query(None,  description="Source abbreviation prefix, e.g. 'L', 'M'"),
    date_from: Optional[int] = Query(None,  description="Earliest year"),
    date_to:   Optional[int] = Query(None,  description="Latest year"),
    volume:    list[int]     = Query([],    description="AA volume number(s); repeat for multiple"),
    page:      int           = Query(1,     description="Page number (1-based)", ge=1),
    page_size: int           = Query(20,    description="Results per page (max 100)", ge=1, le=100),
):
    """
    Flexible search endpoint. All parameters are optional and combinable.

    Date filtering uses overlap logic: a reflexion whose date window
    [date_from, date_to] overlaps the requested range is included.
    """
    con    = get_db()
    wheres = []
    params = []

    if q:
        wheres.append("text LIKE ?")
        params.append(f"%{q}%")

    if source:
        wheres.append("source_raw LIKE ?")
        params.append(f"{source}%")

    if date_from is not None:
        wheres.append("date_to >= ?")
        params.append(date_from)

    if date_to is not None:
        wheres.append("date_from <= ?")
        params.append(date_to)

    if volume:
        placeholders = ",".join("?" * len(volume))
        wheres.append(f"volume IN ({placeholders})")
        params.extend(volume)

    where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""

    total = con.execute(
        f"SELECT COUNT(*) FROM reflexionen {where_clause}", params
    ).fetchone()[0]

    limit, offset = _paginate(page, page_size)
    rows = con.execute(
        f"""SELECT * FROM reflexionen {where_clause}
            ORDER BY date_from, rowid
            LIMIT ? OFFSET ?""",
        params + [limit, offset],
    ).fetchall()

    return SearchResponse(
        total     = total,
        page      = page,
        page_size = page_size,
        pages     = max(1, -(-total // page_size)),  # ceiling division
        results   = [_row_to_summary(r) for r in rows],
    )


@app.get("/api/filter/dates", response_model=SearchResponse,
         summary="All reflexionen whose date window overlaps [year_from, year_to]")
def filter_by_dates(
    year_from: int = Query(..., description="Start of date range"),
    year_to:   int = Query(..., description="End of date range"),
    page:      int = Query(1,   ge=1),
    page_size: int = Query(20,  ge=1, le=100),
):
    return search(
        date_from=year_from, date_to=year_to,
        page=page, page_size=page_size,
    )


@app.get("/api/filter/source", response_model=SearchResponse,
         summary="All reflexionen for a given source abbreviation")
def filter_by_source(
    abbr:      str = Query(..., description="Source abbreviation, e.g. 'L', 'M', 'Pr'"),
    page:      int = Query(1,  ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    return search(source=abbr, page=page, page_size=page_size)


@app.get("/api/neighbours/{number}",
         summary="Previous and next reflexion numbers for sequential browsing")
def get_neighbours(number: str):
    """Returns {prev, next} reflexion numbers in DB order (≈ AA order)."""
    con = get_db()
    row = con.execute(
        "SELECT rowid FROM reflexionen WHERE number = ?", (number,)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Reflexion {number} not found.")
    rid  = row[0]
    prev = con.execute(
        "SELECT number FROM reflexionen WHERE rowid < ? ORDER BY rowid DESC LIMIT 1",
        (rid,)
    ).fetchone()
    nxt  = con.execute(
        "SELECT number FROM reflexionen WHERE rowid > ? ORDER BY rowid ASC LIMIT 1",
        (rid,)
    ).fetchone()
    return {
        "current": number,
        "prev":    prev[0] if prev else None,
        "next":    nxt[0]  if nxt  else None,
    }


@app.get("/api/stats", response_model=StatsResponse,
         summary="Summary counts for the database")
def get_stats():
    """Used by the overview/dashboard page."""
    con = get_db()

    total = con.execute("SELECT COUNT(*) FROM reflexionen").fetchone()[0]
    dated = con.execute(
        "SELECT COUNT(*) FROM reflexionen WHERE date_from IS NOT NULL"
    ).fetchone()[0]

    by_vol = {
        row[0]: row[1]
        for row in con.execute(
            "SELECT volume, COUNT(*) FROM reflexionen GROUP BY volume ORDER BY volume"
        ).fetchall()
    }

    by_src_rows = con.execute(
        """SELECT
               CASE
                   WHEN source_raw LIKE 'L Bl%' THEN 'L Bl.'
                   WHEN source_raw LIKE 'L%'    THEN 'L'
                   WHEN source_raw LIKE 'Ms%'   THEN 'Ms.'
                   WHEN source_raw LIKE 'M%'    THEN 'M'
                   WHEN source_raw LIKE 'Pr%'   THEN 'Pr'
                   WHEN source_raw LIKE 'Th%'   THEN 'Th'
                   WHEN source_raw LIKE 'J%'    THEN 'J'
                   WHEN source_raw LIKE 'B%'    THEN 'B'
                   WHEN source_raw LIKE 'R V%'  THEN 'R V'
                   ELSE COALESCE(source_raw, '(none)')
               END as src,
               COUNT(*) as c
           FROM reflexionen
           GROUP BY src
           ORDER BY c DESC"""
    ).fetchall()
    by_src = {row[0]: row[1] for row in by_src_rows}

    yr = con.execute(
        "SELECT MIN(date_from), MAX(date_to) FROM reflexionen WHERE date_from IS NOT NULL"
    ).fetchone()

    return StatsResponse(
        total         = total,
        dated         = dated,
        by_volume     = by_vol,
        by_source     = by_src,
        earliest_year = yr[0],
        latest_year   = yr[1],
    )


@app.get("/api/timeline", response_model=list[TimelineBucket],
         summary="Year-by-year density for the timeline visualisation")
def get_timeline(
    source: Optional[str] = Query(None, description="Filter by source abbreviation"),
    volume: Optional[int] = Query(None, description="Filter by AA volume"),
):
    """
    Returns one bucket per year with two values:

    - **count**: weighted density — each reflexion contributes 1/range_width
      to every year in its [date_from, date_to] range.  A reflexion dated
      α2 (1754–1755, width=2) contributes 0.5 to each of those years.
      A point-dated reflexion (width=1) contributes 1.0 to its year.
      This gives an honest representation of dating uncertainty.

    - **count_exact**: number of reflexionen with date_from == date_to == year
      (certain single-year datings only).
    """
    con    = get_db()
    wheres = ["date_from IS NOT NULL", "date_to IS NOT NULL"]
    params: list = []

    if source:
        wheres.append("source_raw LIKE ?")
        params.append(f"{source}%")
    if volume is not None:
        wheres.append("volume = ?")
        params.append(volume)

    where_clause = "WHERE " + " AND ".join(wheres)

    rows = con.execute(
        f"SELECT date_from, date_to FROM reflexionen {where_clause}",
        params,
    ).fetchall()

    if not rows:
        return []

    min_year = min(r[0] for r in rows)
    max_year = max(r[1] for r in rows)

    density: dict[int, float] = {y: 0.0 for y in range(min_year, max_year + 1)}
    exact:   dict[int, int]   = {y: 0   for y in range(min_year, max_year + 1)}

    for date_from, date_to in rows:
        width = date_to - date_from + 1
        weight = 1.0 / width
        for year in range(date_from, date_to + 1):
            if year in density:
                density[year] += weight
        if date_from == date_to:
            exact[date_from] += 1

    return [
        TimelineBucket(year=y, count=round(density[y], 3), count_exact=exact[y])
        for y in range(min_year, max_year + 1)
    ]
