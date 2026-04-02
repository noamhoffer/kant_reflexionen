# Kant Reflexionen

A research tool for browsing, searching and visualising Kant's handwritten
notes (*Reflexionen*) from the *Akademie-Ausgabe* volumes AA 14–19, based on
the digitised texts at [korpora.org](https://www.korpora.org/Kant/).

Live: **https://kant-reflexionen.onrender.com**

---

## Project files

```
kant_reflexionen/
├── kant_reflexionen_parser.py   # scraper: builds the SQLite database
├── kant_provenienzen.py         # parses Adickes provenance tables
├── kant_sources.py              # resolves source abbreviations → deep URLs
├── kant_browse.py               # interactive CLI browser
├── inject_anchors.py            # adds §/page anchors to source-text HTML files
├── main.py                      # FastAPI backend
├── requirements.txt
├── render.yaml                  # Render.com deployment config
├── kant_reflexionen.db          # SQLite database (committed, ~13 MB)
├── provenienzen/                # Adickes provenance tables (HTML)
│   ├── L-notizen.html
│   ├── M-notizen.html
│   ├── Th-notizen.html
│   ├── J-notizen.html
│   ├── Pr-notizen.html
│   ├── B-notizen.html
│   └── briefe.html
└── static/
    └── index.html               # single-file web frontend
```

---

## 1. Prerequisites

Python 3.10+ required.

```bash
python3 -m venv .venv
source .venv/bin/activate       # Linux / macOS
# .venv\Scripts\activate        # Windows

pip install -r requirements.txt
```

---

## 2. Building the database

### Option A — From a local HTTrack mirror (recommended)

Mirror the Kant corpus with HTTrack, then run:

```bash
python kant_reflexionen_parser.py --local /path/to/schriften
```

The mirror saves pages as `schriften/www.korpora.org/Kant/aa16/003.html` etc.
If the mirror is in a folder named `schriften` in the same directory,
`--local` can be omitted — it is the default.

The `provenienzen/` directory is also read automatically (default path:
`provenienzen/` next to the script). Override with `--provenienzen DIR`.

```bash
python kant_reflexionen_parser.py                          # all 6 volumes
python kant_reflexionen_parser.py --volumes 16 17          # specific volumes
python kant_reflexionen_parser.py --resume                 # continue after interruption
python kant_reflexionen_parser.py --db myfile.db           # custom DB path
python kant_reflexionen_parser.py --provenienzen /my/prov  # custom provenance dir
```

### Option B — Live HTTP

```bash
python kant_reflexionen_parser.py --local "" --delay 0.5
```

---

## 3. Database schema

| Column | Example | Description |
|---|---|---|
| `number` | `1562`, `158a` | Adickes number (primary key) |
| `volume` | `16` | AA volume number |
| `page_start` / `page_end` | `3` / `59` | Page span (multi-page reflexionen supported) |
| `dating_raw` | `ω¹ (1790)`, `ρ? ς?` | Adickes phase code(s), as printed |
| `date_from` / `date_to` | `1790` / `1791` | Years derived from phase codes |
| `source_raw` | `Loses Blatt A 7`, `L 18` | Expanded source location |
| `note_raw` | `Neben L §. 66-68` | Specific location within Kant's copy |
| `text` | plain text | For full-text search |
| `text_html` | `<i>attentio.</i>…` | Formatted HTML (deletions, italics, etc.) |
| `url_start` | `https://korpora.org/…` | AA page on korpora.org |
| `source_url` | `https://noamhoffer.github.io/…#66` | Deep link into source textbook |
| `brief_url` | `https://korpora.org/kant/briefe/…` | Link to letter (Briefe only) |

---

## 4. Provenance tables

Source and location data (`source_raw`, `note_raw`) come entirely from the
Adickes *Provenienzen* tables, not from HTML parsing. The tables are in the
`provenienzen/` directory and are parsed by `kant_provenienzen.py`.

| File | Source |
|---|---|
| `L-notizen.html` | Meier, *Vernunftlehre* |
| `M-notizen.html` | Baumgarten, *Metaphysica* |
| `Th-notizen.html` | Eberhard, *Theologie* |
| `J-notizen.html` | Achenwall, *Juris naturalis* |
| `Pr-notizen.html` | Baumgarten, *Initia* |
| `B-notizen.html` | Kant, *Beobachtungen* Handexemplar |
| `briefe.html` | Notes written on letters to Kant |

8,092 reflexionen are covered. Those not in the tables (variant `a`-suffix
numbers, loose manuscript sources) have `NULL` for `source_raw` / `note_raw`.

Source abbreviations are automatically expanded:
`L Bl. A 7` → `Loses Blatt A 7`, `Ms.` → `Manuscript`, etc.

---

## 5. Dating

The parser handles the full range of Adickes dating conventions:

| `dating_raw` | `date_from` | `date_to` | Notes |
|---|---|---|---|
| `ω¹ (1790)` | 1790 | 1790 | Exact year in parentheses |
| `ω² (1793—4)` | 1793 | 1794 | Year range in parentheses |
| `ψ` + letter dated 7. Febr. 1784 | 1784 | 1784 | Letter date from `note_raw` |
| `ρ? ς?` | 1773 | 1777 | Multiple phases → union of ranges |
| `ω³⁻⁴` | 1794 | 1798 | Superscript phase range |
| `ψ—ω` | 1780 | 1804 | Dashed phase range |
| `1788—91` | 1788 | 1791 | Bare year range |
| `60-70er Jahre` | 1760 | 1779 | Decade strings |

99.5% of reflexionen have a resolved `date_from`/`date_to`. The remaining 39
with `NULL` are genuinely undatable (loose leaf identifiers, *Vacat*, etc.).

---

## 6. Source textbook deep links

`kant_sources.py` resolves `source_raw` + `note_raw` to a URL into the hosted
source texts. All source files are hosted at
`https://noamhoffer.github.io/kant-sources/` with anchor-injected HTML
(anchors added by `inject_anchors.py`).

Two anchor types per file:
- `#N` — section anchor (§ number)
- `#pN` — page anchor (page in Kant's copy)

When `note_raw` contains a § reference (e.g. `Neben L §. 66-68`), the URL
points to that section (`#66`). Otherwise it points to the page (`#p18`).

| Abbr | Textbook | Files |
|---|---|---|
| `L` | Meier, *Vernunftlehre* (1752) | `meier/vernunftlehre_1.html` (§§ 1–284), `vernunftlehre_2.html` (§§ 285–563) |
| `M` | Baumgarten, *Metaphysica* (1757) | `agb-metaphysica/I.html`, `II1Ba.html`, … `II4.html` |
| `Pr` | Baumgarten, *Initia* (1760) | `agb-initia/index.html` |
| `Th` | Eberhard, *Theologie* (1781) | `eberhard/eberhard.html` |
| `J` | Achenwall, *Juris naturalis* (1763) | `achenwall/achenwall_2.html` (§§ 85–208), `achenwall_3.html` (§§ 209–288) |
| `B` | Kant, *Beobachtungen* | not digitised |
| `R V` | Kant, *KrV* Handexemplar | not digitised |

### Adding anchors to source text files

```bash
# Meier (two files)
python inject_anchors.py meier/vernunftlehre_1.html  out/meier/vernunftlehre_1.html
python inject_anchors.py meier/vernunftlehre_2.html  out/meier/vernunftlehre_2.html

# Eberhard (bare-number headings <h3>N</h3>)
python inject_anchors.py --eberhard eberhard/eberhard.html  out/eberhard/eberhard.html

# Baumgarten Metaphysica (§ anchors already present, page anchors only)
python inject_anchors.py --dir agb-metaphysica/  out/agb-metaphysica/  --pages-only

# Baumgarten Initia
python inject_anchors.py agb-initia/index.html  out/agb-initia/index.html

# Achenwall (files 2 and 3 only; file 1 and index are ToC)
python inject_anchors.py --dir achenwall/  out/achenwall/
```

Each file is identified automatically by filename — no flags needed except
`--pages-only` for Metaphysica and `--eberhard` for Eberhard.

---

## 7. Web application

### Run locally

```bash
uvicorn main:app --reload
```

Open **http://localhost:8000** for the web interface,
or **http://localhost:8000/docs** for the API explorer.

### API endpoints

| Endpoint | Parameters | Description |
|---|---|---|
| `GET /api/stats` | — | Counts by volume and source |
| `GET /api/timeline` | `source=`, `volume=` | Year-by-year density for the chart |
| `GET /api/search` | `q=`, `source=`, `date_from=`, `date_to=`, `volume=`, `page=` | Search + filter |
| `GET /api/reflexion/{number}` | — | Full text + metadata |
| `GET /api/neighbours/{number}` | — | Prev / next numbers |

Default ordering is by AA sequence (volume, page). When a date filter is
active, results are ordered chronologically with undated entries last.

### Frontend features

- **Go to reflexion №** — always visible at top; jump directly by Adickes number
- **Search & filter** — collapsible panel with free-text search, topic checkboxes
  (Math / Anthropology / Logic / Metaphysics / Ethics), source dropdown, date range
- **Timeline** — dual-dataset Chart.js chart: density curve + exact-year bars;
  click a bar to filter by that year
- **Results list** — paginated cards showing number, dating, source, text preview
- **Detail panel** — old-paper background; full formatted text, metadata, source
  deep link, letter link (for Briefe), prev/next navigation

**Text formatting displayed:**

| Symbol | Meaning |
|---|---|
| *italic* | Latin / emphasis |
| ~~strikethrough~~ | Kant's deletions |
| `s p a c e d` | *Gesperrt* (spaced emphasis) |
| `↑word↑` | Interlinear addition |
| `‖word‖` | Marginal addition |

---

## 8. Deploying to Render.com

The database (~13 MB) is committed to the repository, so no separate upload
is needed.

1. Push everything to GitHub:
   ```bash
   git add .
   git commit -m "deploy"
   git push
   ```

2. Go to [render.com](https://render.com) → **New → Web Service**

3. Connect the `noamhoffer/kant_reflexionen` repository

4. Settings:
   - **Build command**: `pip install -r requirements.txt`
   - **Start command**: `uvicorn main:app --host 0.0.0.0 --port $PORT`
   - **Instance type**: Free

5. Click **Deploy** — the app is live within ~2 minutes.

Every subsequent `git push` triggers an automatic redeploy.

The free tier sleeps after 15 minutes of inactivity and wakes in ~30 seconds
on the first request.

---

## 9. Typical workflow

```bash
# Initial setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Build / rebuild the database from a local mirror
python kant_reflexionen_parser.py

# Run the web app locally
uvicorn main:app --reload
# → http://localhost:8000

# After code changes, rebuild and redeploy
python kant_reflexionen_parser.py
git add kant_reflexionen.db
git commit -m "updated db"
git push
```

---

## 10. Re-scraping after schema changes

The parser is idempotent with `--resume`, but after schema changes start fresh:

```bash
rm kant_reflexionen.db
python kant_reflexionen_parser.py
```

`kant_browse.py` runs automatic migrations on startup to add columns
introduced after an initial scrape (`text_html`, `source_url`, `brief_url`).
