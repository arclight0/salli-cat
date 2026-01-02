# ManualsLib TV Manual Scraper

A Python-based scraper to download TV manuals from manualslib.com with a web dashboard for monitoring progress.

## Project Structure

```
manualslib-scraper/
├── config.yaml        # Brand list configuration
├── scraper.py         # Main Playwright scraper
├── database.py        # SQLite database layer
├── dashboard.py       # Flask web dashboard
├── templates/
│   └── index.html     # Dashboard UI
├── downloads/         # Downloaded PDFs (organized by brand)
├── manuals.db         # SQLite database (created on first run)
├── .venv/             # Python virtual environment
└── requirements.txt   # Python dependencies
```

## Setup

```bash
# Activate the virtual environment
source .venv/bin/activate

# Dependencies are already installed, but if needed:
pip install -r requirements.txt
playwright install chromium
```

## Usage

### Running the Scraper

```bash
# Activate venv first
source .venv/bin/activate

# Scrape all brands in config.yaml
python scraper.py

# Scrape specific brands only
python scraper.py --brands rca sharp panasonic

# Scrape listings only (populate database, no downloads)
python scraper.py --scrape-only

# Download pending manuals only (skip scraping)
python scraper.py --download-only
```

### Running the Dashboard

```bash
source .venv/bin/activate
python dashboard.py
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

- **Summary Stats**: Total manuals, downloaded count, pending count
- **Progress by Brand**: Visual progress bars showing download completion
- **Manual Table**: Searchable/filterable list of all manuals
- **Filters**: Filter by brand and download status
- **Actions**: Links to view on manualslib or download locally
- **Auto-Refresh**: Updates every 30 seconds

## Database Schema

SQLite database (`manuals.db`) with a single `manuals` table:

| Column | Type | Description |
|--------|------|-------------|
| id | INTEGER | Primary key |
| brand | TEXT | Brand name (e.g., "rca") |
| model | TEXT | Model name/number |
| doc_type | TEXT | Document type (e.g., "User Manual") |
| doc_name | TEXT | Document name |
| manual_url | TEXT | URL to manual page on manualslib |
| downloaded | INTEGER | 0 = pending, 1 = downloaded |
| file_path | TEXT | Local path to downloaded PDF |
| created_at | TEXT | Timestamp when added |

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
- Use `--download-only` to resume downloading after interruption

## Rate Limiting

The scraper includes random delays between requests (2-5 seconds) to avoid overwhelming the server.
