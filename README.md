# ManualsLib TV Manual Scraper

A Python-based scraper to download TV manuals from manualslib.com with a web dashboard for monitoring progress.

## Project Structure

```
manualslib-scraper/
├── pyproject.toml     # Project config and dependencies
├── config.yaml        # Brand list configuration
├── scraper.py         # Main Playwright scraper
├── database.py        # SQLite database layer
├── dashboard.py       # Flask web dashboard
├── templates/
│   └── index.html     # Dashboard UI
├── downloads/         # Downloaded PDFs (organized by brand)
└── manuals.db         # SQLite database (created on first run)
```

## Setup

This project uses [uv](https://docs.astral.sh/uv/) for Python version and dependency management.

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync dependencies (creates .venv automatically)
uv sync

# Install Playwright browsers
uv run playwright install chromium
```

## Usage

### Brand Discovery

Automatically discover all brands on manualslib that have TV manuals:

```bash
# Discover all brands with TV category (saves to database)
uv run python scraper.py --discover-brands

# Then scrape all discovered brands
uv run python scraper.py --use-discovered --scrape-only
```

### Running the Scraper

```bash
# Scrape all brands in config.yaml
uv run python scraper.py

# Scrape specific brands only
uv run python scraper.py --brands rca sharp panasonic

# Scrape all discovered brands (from --discover-brands)
uv run python scraper.py --use-discovered

# Scrape listings only (populate database, no downloads)
uv run python scraper.py --scrape-only

# Download pending manuals only (skip scraping)
uv run python scraper.py --download-only

# Clear database and start fresh
uv run python scraper.py --clear --scrape-only
```

### Running the Dashboard

```bash
uv run python dashboard.py
```

Then open http://localhost:5000 in your browser.

## Configuration

Edit `config.yaml` to add or remove brands:

```yaml
brands:
  - rca
  - sharp
  - panasonic
  - samsung
  - lg

download_dir: ./downloads
```

Brand names should match the URL slug on manualslib.com (e.g., `https://www.manualslib.com/brand/rca/tv.html`).

## Captcha Handling

ManualsLib uses reCAPTCHA to protect manual downloads. This scraper handles it by:

1. **Visible Browser**: Playwright runs in headed mode (you see the browser window)
2. **Detection**: When a captcha appears, the scraper detects it and pauses
3. **Manual Solving**: A message prints to the terminal - solve the captcha in the browser window
4. **Auto-Continue**: Once solved, the scraper automatically detects this and continues
5. **Timeout**: If not solved within 5 minutes, the manual is skipped

```
============================================================
CAPTCHA DETECTED - Please solve it in the browser window
============================================================
```

## Dashboard Features

- **Summary Stats**: Total manuals, downloaded count, archived count, pending count
- **Progress by Brand**: Visual progress bars showing completion
- **Manual Table**: Filterable list of all manuals
- **Filters**: Filter by brand and download status
- **Actions**: Links to view on manualslib, download locally, or view on archive.org
- **Auto-Refresh**: Updates every 30 seconds

## Database Schema

SQLite database (`manuals.db`) with two tables:

### brands table
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| name | TEXT | Brand display name |
| slug | TEXT | URL slug (e.g., "rca") |
| brand_url | TEXT | URL to brand page |
| categories | TEXT | Comma-separated categories |
| scraped | INTEGER | 0 = pending, 1 = scraped |

### manuals table
| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| brand | TEXT | Brand slug |
| model | TEXT | Model name/number |
| model_url | TEXT | URL to model page |
| model_id | TEXT | ManualsLib model ID |
| doc_type | TEXT | Document type (e.g., "User Manual") |
| doc_description | TEXT | Document description |
| manual_url | TEXT | URL to manual page |
| manualslib_id | TEXT | ManualsLib document ID |
| downloaded | INTEGER | 0 = pending, 1 = downloaded |
| archived | INTEGER | 0 = not archived, 1 = on archive.org |
| file_path | TEXT | Local path to downloaded PDF |
| archive_url | TEXT | URL on archive.org |

## Archive.org Integration

Before downloading, the scraper checks if the manual already exists on archive.org at:
`https://archive.org/details/manualslib-id-{manualslib_id}`

If archived, it skips the download and records the archive URL.

## Downloaded Files

PDFs are saved to `downloads/{brand}/{model}_{doc_type}.pdf`

Example:
```
downloads/
├── rca/
│   ├── RLDED5078A_User Manual.pdf
│   └── LED32A30RQ_User Manual.pdf
├── sharp/
│   └── LC-50LB371U_Operation Manual.pdf
└── panasonic/
    └── TC-P50X5_Owner_s Manual.pdf
```

## Resume Capability

The scraper tracks progress in the database:
- Already-scraped manuals won't be re-added
- Already-downloaded manuals won't be re-downloaded
- Archived manuals are skipped
- Use `--download-only` to resume downloading after interruption

## Rate Limiting

The scraper includes random delays between requests (2-5 seconds) to avoid overwhelming the server.
