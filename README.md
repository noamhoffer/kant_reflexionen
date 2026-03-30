# Kant Reflexionen — Project Documentation

A research tool for browsing, searching, and visualising Kant's handwritten
notes (*Reflexionen*) from the *Akademie-Ausgabe* volumes AA 14–19, based on
the digitised texts at [korpora.org](https://www.korpora.org/Kant/).

---

## Project files

```
kant_reflexionen/
├── kant_reflexionen_parser.py  # scraper: builds the SQLite database
├── kant_sources.py             # resolves source abbreviations to URLs
├── kant_browse.py              # interactive CLI browser
├── kant_diagnose.py            # diagnostic tool for checking parser output
├── inject_anchors.py           # adds §-anchors to Meier/Eberhard HTML files
├── main.py                     # FastAPI web backend
├── requirements.txt            # Python dependencies
├── render.yaml                 # Render.com deployment config
└── static/
    └── index.html              # single-file web frontend
```

---

## 1. Prerequisites

### Python

Python 3.10 or later is required.

**Recommended: use WSL2 on Windows** (Ubuntu via the Microsoft Store).
Open a WSL terminal and install Python tools:

```bash
sudo apt update && sudo apt install python3-pip python3-venv -y
```

### Virtual environment

```bash
cd ~/kant_reflexionen
python3 -m venv .venv
source .venv/bin/activate        # Linux / WSL
# .venv\Scripts\activate         # Windows native Python
```

### Install dependencies

```bash
pip install -r requirements.txt
```

This installs: `beautifulsoup4`, `lxml`, `requests`, `rich`, `fastapi`, `uvicorn`.

---

## 2. Building the database

### Option A — From a local HTTrack mirror (recommended)

Mirror the Kant corpus with HTTrack, then run:

```bash
python kant_reflexionen_parser.py --local /path/to/schriften
```

HTTrack saves pages as `schriften/www.korpora.org/Kant/aa16/003.html` etc.
If your mirror root is named `schriften` and is in the same directory, you
can omit `--local` entirely — it is the default.

```bash
python kant_reflexionen_parser.py                        # all 6 volumes
python kant_reflexionen_parser.py --volumes 16 17        # specific volumes
python kant_reflexionen_parser.py --resume               # continue after interruption
python kant_reflexionen_parser.py --db myfile.db         # custom DB path
```

### Option B — Live HTTP (slower, network-dependent)

```bash
python kant_reflexionen_parser.py --local "" --delay 0.5
```

Pass an empty string for `--local` to force HTTP mode.
The `--delay` flag sets seconds between requests (default: 0.5).

### What the scraper produces

A SQLite database `kant_reflexionen.db` with this schema:

| Column | Example | Description |
|---|---|---|
| `number` | `1562`, `158a` | Adickes number (primary key) |
| `volume` | `16` | AA volume number |
| `page_start` / `page_end` | `3` / `4` | Page span in the AA edition |
| `dating_raw` | `α 2`, `β 1--ε 2` | Adickes phase code(s), as printed |
| `date_from` / `date_to` | `1754` / `1755` | Years derived from phase codes |
| `source_raw` | `L 1`, `M §. 7` | Source textbook + section |
| `note_raw` | `Zu L §. 40` | Physical location in Kant's copy |
| `text` | `Alles, was aus einem…` | Plain text (for full-text search) |
| `text_html` | `<i>attentio.</i>…` | Formatted HTML (deletions, italics, etc.) |
| `url_start` | `https://korpora.org/…` | Link to the AA page on korpora.org |
| `source_url` | `https://korpora.org/…#7` | Deep link into the source textbook |

### Dating phase codes

Adickes assigned each phase a Greek letter (α1 = ~1753–54, ω5 = 1798–1804).
`date_from`/`date_to` are the union of all phases in `dating_raw`.
Non-standard datings like `60-70er Jahre` are stored in `dating_raw`
but produce `NULL` for `date_from`/`date_to`.

---

## 3. Diagnosing parser problems

Before a full scrape, verify the parser works on a sample page:

```bash
python kant_diagnose.py                           # tests AA16 pages 3, 169, 320 from web
python kant_diagnose.py --vol 16 --page 169       # single page from web
python kant_diagnose.py --local schriften --vol 16 --page 169  # from local mirror
python kant_diagnose.py --pages 3 169 320 401     # multiple pages
```

Each page shows:
- Bold tags found and whether they match the header pattern
- First table rows
- `parse_page()` output with HEADER / line items
- Quality checks: ✓ or ✗ for headers, dating, source

---

## 4. CLI browser

Browse the database interactively in the terminal:

```bash
python kant_browse.py                         # uses kant_reflexionen.db
python kant_browse.py --db myfile.db          # custom DB path
```

### Commands at the prompt

| Command | Example | Action |
|---|---|---|
| `<number>` | `1562`, `158a` | Look up a reflexion |
| `n` / `p` | | Next / previous |
| `s <term>` | `s L 1`, `s M §` | Search by source |
| `d <from> [<to>]` | `d 1769`, `d 1769 1772` | Filter by date range |
| `l` | | Show current result list |
| `l +` / `l -` | | Page through results |
| `i` | | Database summary |
| `h` | | Help |
| `q` | | Quit |

Install `rich` for coloured output (already in `requirements.txt`).

---

## 5. Web application

### Run locally

```bash
uvicorn main:app --reload
```

Open **http://localhost:8000** for the web interface,
or **http://localhost:8000/docs** for the interactive API explorer.

### API endpoints

| Endpoint | Description |
|---|---|
| `GET /api/reflexion/{number}` | Full text + metadata for one reflexion |
| `GET /api/neighbours/{number}` | Previous / next reflexion numbers |
| `GET /api/search` | Search: `?q=`, `?source=`, `?date_from=`, `?date_to=`, `?volume=` |
| `GET /api/filter/dates` | `?year_from=1769&year_to=1772` |
| `GET /api/filter/source` | `?abbr=M` |
| `GET /api/stats` | Counts by volume and source |
| `GET /api/timeline` | Year-by-year counts for the chart |

### Frontend features

- **Timeline** — bar chart of reflexionen by year; click a bar to filter
- **Search panel** — free-text search, source dropdown, date range inputs
- **Results list** — paginated cards with number, dating, source, preview
- **Detail panel** — full text with formatting, metadata, source deep link,
  sequential prev/next navigation

**Text formatting conventions displayed:**
- *Italic* — Latin phrases / emphasis (`<i>`)
- ~~Strikethrough~~ — Kant's deletions
- `s p a c e d` — *Gesperrt* (German spaced emphasis)
- `↑word↑` — interlinear addition `( g word )`
- `‖word‖` — marginal addition `( s word )`

---

## 6. Source textbook cross-references

The `source_url` field links directly into the digitised source texts.
URLs are resolved by `kant_sources.py` from the `source_raw` field.

| Abbreviation | Textbook | Status |
|---|---|---|
| `L` | Meier, *Auszug aus der Vernunftlehre* (1752) | §-anchors via GitHub Pages |
| `M` | Baumgarten, *Metaphysica* (1757) | §-anchors native on korpora.org |
| `Pr` | Baumgarten, *Initia Philosophiae Practicae* (1760) | §-anchors native |
| `Th` | Eberhard, *Vorbereitung zur natürl. Theologie* (1781) | §-anchors via GitHub Pages |
| `J` | Achenwall, *Juris naturalis pars posterior* (1763) | two-page split |
| `B` | Kant, *Beobachtungen* (Handexemplar) | not digitised online |
| `R V` | Kant, *Kritik der reinen Vernunft* (Handexemplar) | not digitised online |

### Adding §-anchors to Meier and Eberhard

Meier and Eberhard are published as single long HTML pages with no native
section anchors. To enable deep links, host anchor-injected versions on
GitHub Pages:

```bash
# 1. Download originals
curl -o meier_orig.html    "https://korpora.org/kant/meier/"
curl -o eberhard_orig.html "http://www.korpora.org/kant/eberhard/eberhard.html"

# 2. Inject anchors
python inject_anchors.py meier_orig.html    meier.html
python inject_anchors.py eberhard_orig.html eberhard.html

# 3. Push meier.html and eberhard.html to a GitHub Pages repo
```

Then update `kant_sources.py` with your GitHub Pages URLs:

```python
MEIER_URL    = "https://yourname.github.io/kant-sources/meier.html"
EBERHARD_URL = "https://yourname.github.io/kant-sources/eberhard.html"
```

---

## 7. Deploying to Render.com (free hosting)

1. Push all project files to a GitHub repository
   (include `kant_reflexionen.db` or configure `DB_PATH` to a persistent disk path)
2. Go to [render.com](https://render.com) → New → Web Service
3. Connect your GitHub repo
4. Render will detect `render.yaml` and configure automatically
5. Set the environment variable `DB_PATH` if your DB is not at the repo root

The `render.yaml` configures:
- Build: `pip install -r requirements.txt`
- Start: `uvicorn main:app --host 0.0.0.0 --port $PORT`
- 1 GB persistent disk at `/data` for the SQLite file

On the free tier the service sleeps after 15 minutes of inactivity and
wakes in ~30 seconds on the next request — acceptable for a research tool.

---

## 8. Typical workflow

```bash
# First time setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Verify parser on a few pages before committing to full scrape
python kant_diagnose.py --vol 16 --pages 3 169 320

# Scrape (from local mirror — fastest)
python kant_reflexionen_parser.py

# Browse locally
python kant_browse.py

# Run the web app
uvicorn main:app --reload
# → open http://localhost:8000
```

---

## 9. Re-scraping after code changes

The parser is idempotent with `--resume`, but if the DB schema changes
(e.g. adding a new column) it is safer to start fresh:

```bash
rm kant_reflexionen.db
python kant_reflexionen_parser.py
```

The `kant_browse.py` CLI runs automatic migrations on startup to add
columns introduced after the initial scrape (currently `source_url`
and `text_html`), so existing databases do not need to be rebuilt just
for those.
