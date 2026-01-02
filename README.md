# TV Manual Scraper

A Python-based scraper to download TV manuals from multiple sources (ManualsLib, Manualzz) with a web dashboard for monitoring progress.

## Supported Sources

- **ManualsLib** (manualslib.com) - Brand discovery and TV manual scraping
- **Manualzz** (manualzz.com) - CRT TV and monitor manual scraping

## Project Structure

```
manualslib-scraper/
├── pyproject.toml        # Project config and dependencies
├── config.yaml           # Brand list and URL configuration
├── Procfile              # Process definitions for honcho
├── scraper.py            # ManualsLib Playwright scraper
├── manualzz_scraper.py   # Manualzz Playwright scraper
├── archive_checker.py    # Background archive.org checker
├── captcha_solver.py     # 2captcha integration for auto-solving
├── browser_helper.py     # Browser launch helper with extension support
├── database.py           # SQLite database layer
├── dashboard.py          # Flask web dashboard
├── templates/
│   └── index.html        # Dashboard UI
├── extensions/           # Browser extensions (optional)
│   └── ublock_origin/    # uBlock Origin for ad blocking
├── downloads/            # Downloaded PDFs (organized by source/brand)
└── manuals.db            # SQLite database (created on first run)
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

### Running the ManualsLib Scraper

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

# Clear manualslib records and start fresh
uv run python scraper.py --clear --scrape-only

# Clear discovered brands
uv run python scraper.py --clear-brands

# Clear everything (manuals and brands)
uv run python scraper.py --clear-all
```

### Running the Manualzz Scraper

```bash
# Scrape catalog URLs from config.yaml
uv run python manualzz_scraper.py

# Scrape specific catalog URLs
uv run python manualzz_scraper.py --urls "https://manualzz.com/catalog/..."

# Scrape listings only (populate database, no downloads)
uv run python manualzz_scraper.py --scrape-only

# Download pending manuals only (skip scraping)
uv run python manualzz_scraper.py --download-only

# Clear manualzz records and start fresh
uv run python manualzz_scraper.py --clear
```

### Running the Dashboard

```bash
uv run python dashboard.py
```

Then open http://localhost:5000 in your browser.

### Running the Archive.org Checker

The archive checker runs as a background process, slowly checking if manuals already exist on archive.org. This pre-identifies archived manuals so they can be skipped during downloads.

```bash
# Check all pending manuals once (with default rate limiting)
uv run python archive_checker.py

# Run continuously, checking new manuals as they appear
uv run python archive_checker.py --continuous

# Check with faster rate (be careful not to hit rate limits)
uv run python archive_checker.py --delay-min 2 --delay-max 5

# Just show current statistics
uv run python archive_checker.py --stats
```

### Running Multiple Processes with Honcho

Use the `Procfile` to run the dashboard and archive checker together:

```bash
# Install dependencies (includes honcho)
uv sync

# Run all processes defined in Procfile
uv run honcho start

# Or run individual processes
uv run honcho start dashboard
uv run honcho start archive_checker
```

## Configuration

Edit `config.yaml` to configure brands, categories, and catalog URLs:

```yaml
# ManualsLib brands (slug from URL)
brands:
  - rca
  - sharp
  - panasonic
  - samsung
  - lg

# Categories to scrape for each brand (used when not using discovered brands)
# These are the URL slug suffixes, e.g. "tv" -> /brand/rca/tv.html
categories:
  - tv              # standalone TVs
  - tv-dvd-combo    # TV/DVD combos
  - tv-vcr-combo    # TV/VCR combos

download_dir: ./downloads

# Manualzz catalog URLs to scrape
manualzz_urls:
  - https://manualzz.com/catalog/computers+%26+electronics/TVs+%26+monitors/CRT+TVs
  - https://manualzz.com/catalog/computers+%26+electronics/TVs+%26+monitors/monitors+CRT
```

- **brands**: ManualsLib brand slugs (e.g., `https://www.manualslib.com/brand/rca/tv.html`)
- **categories**: Category slugs to scrape for each brand. When using `--use-discovered`, the discovered category URLs are used instead.
- **manualzz_urls**: Direct catalog URLs from manualzz.com

## Captcha Handling

ManualsLib uses reCAPTCHA to protect manual downloads. The scraper supports two modes:

### Automatic Solving with 2captcha (Recommended)

For hands-free operation, configure 2captcha automatic solving:

1. Get an API key from [2captcha.com](https://2captcha.com/enterpage)
2. Add your API key to `config.yaml`:
   ```yaml
   twocaptcha_api_key: your_api_key_here
   ```
3. The scraper will automatically solve captchas (~$2.99 per 1000 captchas)

When 2captcha is configured, the scraper will:
- Extract the reCAPTCHA sitekey from the page
- Submit to 2captcha and wait for solution (~10-30 seconds)
- Inject the solution token and continue automatically
- Fall back to manual solving if 2captcha fails

### Manual Solving (Fallback)

If 2captcha is not configured (or fails), the scraper falls back to manual solving:

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

## Ad Blocking

The scrapers support ad blocking to prevent ads from interfering with the scraping process. Two methods are available:

### uBlock Origin Extension (Recommended)

For comprehensive ad blocking, you can load the uBlock Origin browser extension:

1. Download uBlock Origin for Chromium from [GitHub releases](https://github.com/AmpMn/AmpMn/releases) (look for `uBlock0_X.XX.X.chromium.zip`)
2. Extract the `.zip` file to `./extensions/ublock_origin/` (the directory should contain `manifest.json`)
3. The scraper will automatically load the extension

Alternatively, specify a custom path in `config.yaml`:
```yaml
ublock_origin_path: /path/to/ublock_origin
```

### Route-Based Blocking (Fallback)

If no extension is configured, the scrapers fall back to route-based blocking which intercepts requests to known ad domains. This is less comprehensive but requires no setup.

## Dashboard Features

- **Summary Stats**: Total manuals, downloaded count, archived count, pending count
- **Stats by Source**: Breakdown of manuals by source (ManualsLib, Manualzz)
- **Progress by Brand**: Visual progress bars showing completion
- **Manual Table**: Filterable list of all manuals with source badges
- **Filters**: Filter by source, brand, and download status
- **Actions**: Links to view on source site, download locally, or view on archive.org
- **Database Management**: Clear buttons for specific sources or all data
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
| source | TEXT | Source site ("manualslib" or "manualzz") |
| source_id | TEXT | ID from source site |
| brand | TEXT | Brand name/slug |
| model | TEXT | Model name/number |
| model_url | TEXT | URL to model page |
| model_id | TEXT | ManualsLib model ID |
| doc_type | TEXT | Document type (e.g., "User Manual") |
| doc_description | TEXT | Document description |
| category | TEXT | Category (for manualzz) |
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

PDFs are saved organized by source and brand:

- **ManualsLib**: `downloads/{brand}/{model}_{doc_type}.pdf`
- **Manualzz**: `downloads/manualzz/{brand}/{title}.pdf`

Example:
```
downloads/
├── rca/
│   ├── RLDED5078A_User Manual.pdf
│   └── LED32A30RQ_User Manual.pdf
├── sharp/
│   └── LC-50LB371U_Operation Manual.pdf
├── panasonic/
│   └── TC-P50X5_Owner_s Manual.pdf
└── manualzz/
    ├── Sony/
    │   └── KV-27FS120 CRT Television.pdf
    └── Panasonic/
        └── CT-27SX12 Service Manual.pdf
```

## Resume Capability

The scraper tracks progress in the database:
- Already-scraped manuals won't be re-added
- Already-downloaded manuals won't be re-downloaded
- Archived manuals are skipped
- Use `--download-only` to resume downloading after interruption

## Rate Limiting

The scraper includes random delays between requests (2-5 seconds) to avoid overwhelming the server.
