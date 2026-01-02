#!/usr/bin/env python3
import argparse
import hashlib
import logging
import random
import re
import time
import urllib.request
import urllib.error
from pathlib import Path

import yaml
from playwright.sync_api import sync_playwright, Page

import database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

BASE_URL = "https://www.manualslib.com"
ARCHIVE_ORG_BASE = "https://archive.org/details/manualslib-id-"
CAPTCHA_TIMEOUT = 300  # 5 minutes to solve captcha


def extract_manualslib_id(url: str) -> str | None:
    """Extract the numeric ID from a manualslib URL like /manual/331384/..."""
    match = re.search(r'/manual/(\d+)/', url)
    return match.group(1) if match else None


def extract_model_id(url: str) -> str | None:
    """Extract the model ID from a product URL like /products/Rca-35v432t-328381.html"""
    match = re.search(r'-(\d+)\.html', url)
    return match.group(1) if match else None


def check_archive_org(manualslib_id: str) -> tuple[bool, str]:
    """Check if a manual exists on archive.org. Returns (exists, archive_url)."""
    archive_url = f"{ARCHIVE_ORG_BASE}{manualslib_id}"
    try:
        req = urllib.request.Request(archive_url, method='HEAD')
        req.add_header('User-Agent', 'Mozilla/5.0 (compatible; ManualsLibScraper/1.0)')
        with urllib.request.urlopen(req, timeout=10) as response:
            # 200 means it exists
            return True, archive_url
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return False, archive_url
        logger.warning(f"HTTP error checking archive.org: {e.code}")
        return False, archive_url
    except Exception as e:
        logger.warning(f"Error checking archive.org: {e}")
        return False, archive_url


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def random_delay(min_sec: float = 2.0, max_sec: float = 5.0):
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)


def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', name)


def compute_checksums(file_path: Path) -> tuple[str, str]:
    """Compute SHA1 and MD5 checksums for a file. Returns (sha1, md5)."""
    sha1 = hashlib.sha1()
    md5 = hashlib.md5()

    with open(file_path, 'rb') as f:
        while chunk := f.read(8192):
            sha1.update(chunk)
            md5.update(chunk)

    return sha1.hexdigest(), md5.hexdigest()


def extract_slug_from_url(url: str) -> str | None:
    """Extract brand slug from URL like /brand/hitachi/ or /brand/hitachi/tv.html"""
    match = re.search(r'/brand/([^/]+)/?', url)
    return match.group(1) if match else None


def is_tv_category(cat_name: str) -> bool:
    """Check if a category name matches our TV criteria.

    Matches:
    - Exact "TV" (case-insensitive)
    - "TV * Combo" pattern (e.g., "TV DVD Combo", "TV VCR Combo")
    """
    name_lower = cat_name.lower().strip()

    # Exact match for "TV"
    if name_lower == "tv":
        return True

    # Pattern: "TV <something> Combo"
    if name_lower.startswith("tv ") and name_lower.endswith(" combo"):
        return True

    return False


def discover_brands(page: Page) -> tuple[list[dict], set[str]]:
    """Discover all brands that have TV in their categories.

    Returns:
        tuple: (list of brand dicts, set of all categories containing 'tv')

    1. Visit https://www.manualslib.com/brand/
    2. Find all letter/number links in the header
    3. Visit each page (with pagination) and find brands with TV category
    """
    brands = []
    seen_slugs = set()
    all_tv_related_categories = set()  # Track all categories with "tv" in name

    # First, get all the letter/number index links
    logger.info("Discovering brands with TV category...")
    page.goto(f"{BASE_URL}/brand/", wait_until="networkidle")
    random_delay(1, 2)

    # Find all index links in the bmap div
    index_links = page.query_selector_all('div.bmap a')
    index_urls = []
    for link in index_links:
        href = link.get_attribute("href")
        if href:
            url = href if href.startswith("http") else BASE_URL + href
            index_urls.append(url)

    logger.info(f"Found {len(index_urls)} index pages to scan")

    # Visit each index page
    for index_url in index_urls:
        current_url = index_url
        page_num = 1

        while current_url:
            logger.info(f"Scanning: {current_url} (page {page_num})")
            page.goto(current_url, wait_until="networkidle")
            random_delay(1, 2)

            # Find all brand rows
            brand_rows = page.query_selector_all('div.row.tabled')

            for row in brand_rows:
                # Get brand info from col1
                brand_link = row.query_selector('div.col1 a, div.col-xs-3 a')
                if not brand_link:
                    continue

                brand_name = brand_link.inner_text().strip()
                brand_href = brand_link.get_attribute("href")
                brand_url = brand_href if brand_href.startswith("http") else BASE_URL + brand_href
                slug = extract_slug_from_url(brand_url)

                if not slug or slug in seen_slugs:
                    continue

                # Get categories from catel div
                category_links = row.query_selector_all('div.catel a, div.col-xs-9 a')
                all_categories = []
                tv_categories = []
                tv_category_urls = []

                for cat_link in category_links:
                    cat_name = cat_link.inner_text().strip()
                    cat_href = cat_link.get_attribute("href")
                    cat_url = cat_href if cat_href and cat_href.startswith("http") else BASE_URL + (cat_href or "")

                    all_categories.append(cat_name)

                    # Track all categories with "tv" in them for review
                    if 'tv' in cat_name.lower():
                        all_tv_related_categories.add(cat_name)

                    # Check if this matches our exact TV criteria
                    if is_tv_category(cat_name):
                        tv_categories.append(cat_name)
                        tv_category_urls.append(cat_url)

                if tv_categories:
                    seen_slugs.add(slug)
                    brand_info = {
                        "name": brand_name,
                        "slug": slug,
                        "brand_url": brand_url,
                        "tv_categories": ", ".join(tv_categories),
                        "tv_category_urls": ", ".join(tv_category_urls),
                        "all_categories": ", ".join(all_categories),
                    }
                    brands.append(brand_info)

                    # Add to database immediately so progress is visible
                    brand_id = database.add_brand(
                        name=brand_info["name"],
                        slug=brand_info["slug"],
                        brand_url=brand_info["brand_url"],
                        tv_categories=brand_info["tv_categories"],
                        tv_category_urls=brand_info["tv_category_urls"],
                        all_categories=brand_info["all_categories"],
                    )
                    if brand_id:
                        logger.info(f"Added TV brand: {brand_name} ({slug}) - Categories: {', '.join(tv_categories)}")
                    else:
                        logger.info(f"Found TV brand (already in DB): {brand_name} ({slug})")

            # Check for next page in pagination
            next_page_link = page.query_selector('ul.pagination li.active + li a.plink')
            if next_page_link:
                next_href = next_page_link.get_attribute("href")
                if next_href:
                    current_url = next_href if next_href.startswith("http") else BASE_URL + next_href
                    page_num += 1
                    random_delay(1, 2)
                else:
                    current_url = None
            else:
                current_url = None

    logger.info(f"Discovered {len(brands)} brands with TV category")
    return brands, all_tv_related_categories


def scrape_category_listing(page: Page, brand: str, category_url: str, category_name: str = None) -> int:
    """Scrape all manual links from a brand's category listing pages.

    Args:
        page: Playwright page object
        brand: Brand name/slug for database records
        category_url: Full URL to the category page (e.g., /brand/magnavox/tv-dvd-combo.html)
        category_name: Optional category name for logging

    Adds manuals to database immediately as they're found for real-time progress.
    Returns the count of manuals found.

    HTML structure:
    <div class="row tabled">
        <div class="col-sm-2 mname">
            <a href="/products/Rca-35v432t-328381.html">35V432T</a>
        </div>
        <div class="col-sm-10 mlinks">
            <div class="mdiv">
                <a href="/manual/138703/Rca-35v432t.html" title="2 pages...">Specification sheet</a>
                <a href="/manual/313150/Rca-35v432t.html" title="64 pages...">user manual</a>
            </div>
        </div>
    </div>
    """
    seen_urls = set()
    page_num = 1
    manual_count = 0

    # Parse the base URL for pagination
    base_url = category_url.split('?')[0]  # Remove any existing query params
    cat_display = category_name or category_url.split('/')[-1].replace('.html', '')

    while True:
        if page_num == 1:
            url = category_url
        else:
            url = f"{base_url}?p={page_num}"

        logger.info(f"Scraping {brand} [{cat_display}] page {page_num}: {url}")
        page.goto(url, wait_until="networkidle")
        random_delay(1, 2)

        # Find all model rows
        model_rows = page.query_selector_all('div.row.tabled')

        if not model_rows:
            logger.info(f"No more models found for {brand} [{cat_display}] on page {page_num}")
            break

        for row in model_rows:
            # Get model info from the mname column
            model_link_elem = row.query_selector('div.mname a')
            if not model_link_elem:
                continue

            model_name = model_link_elem.inner_text().strip()
            model_href = model_link_elem.get_attribute("href")
            model_url = model_href if model_href.startswith("http") else BASE_URL + model_href
            model_id = extract_model_id(model_url)

            # Find all manual links in the mlinks column
            manual_links = row.query_selector_all('div.mlinks a[href*="/manual/"]')

            for link in manual_links:
                href = link.get_attribute("href")
                if not href:
                    continue

                manual_url = href if href.startswith("http") else BASE_URL + href

                # Skip if we've already seen this URL
                if manual_url in seen_urls:
                    continue
                seen_urls.add(manual_url)

                # Document type is the link text
                doc_type = link.inner_text().strip()

                # Document description is in the title attribute
                doc_description = link.get_attribute("title") or ""

                # Extract manualslib ID from the manual URL
                manualslib_id = extract_manualslib_id(manual_url)

                # Add to database immediately for real-time progress
                manual_id = database.add_manual(
                    brand=brand,
                    model=model_name,
                    model_url=model_url,
                    model_id=model_id,
                    doc_type=doc_type,
                    doc_description=doc_description,
                    manual_url=manual_url,
                    manualslib_id=manualslib_id,
                )
                if manual_id:
                    logger.info(f"Added: {model_name} - {doc_type}")
                manual_count += 1

        # Check for next page
        next_button = page.query_selector('a.pag-pnext:not(.disabled)')
        if next_button:
            page_num += 1
            random_delay()
        else:
            logger.info(f"Reached last page for {brand} [{cat_display}]")
            break

    logger.info(f"Found {manual_count} manuals for {brand} [{cat_display}]")
    return manual_count


def wait_for_captcha_solved(page: Page, timeout: int = CAPTCHA_TIMEOUT) -> bool:
    """Wait for human to solve captcha. Returns True if solved, False if timeout."""
    logger.info("Waiting for captcha to be solved...")
    print("\n" + "=" * 60)
    print("CAPTCHA DETECTED - Please solve it in the browser window")
    print("=" * 60 + "\n")

    start_time = time.time()

    while time.time() - start_time < timeout:
        # Check if captcha iframe is still present and visible
        captcha_frame = page.query_selector('iframe[src*="recaptcha"]')
        if not captcha_frame:
            logger.info("Captcha appears to be solved (iframe gone)")
            return True

        # Check if captcha is in solved state
        try:
            # Look for the checkmark that appears when solved
            captcha_response = page.evaluate("""
                () => {
                    const response = document.querySelector('[name="g-recaptcha-response"]');
                    return response && response.value.length > 0;
                }
            """)
            if captcha_response:
                logger.info("Captcha solved (response token present)")
                return True
        except Exception:
            pass

        time.sleep(2)

    logger.warning("Captcha timeout - skipping this manual")
    return False


def download_file_from_url(url: str, file_path: Path) -> bool:
    """Download a file directly from URL. Returns True if successful."""
    try:
        req = urllib.request.Request(url)
        req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
        with urllib.request.urlopen(req, timeout=120) as response:
            with open(file_path, 'wb') as f:
                f.write(response.read())
        return True
    except Exception as e:
        logger.error(f"Failed to download {url}: {e}")
        return False


def download_manual(page: Page, manual: dict, download_dir: Path, brand: str) -> tuple[str, str, str, int] | None:
    """Download a single manual. Returns (file_path, sha1, md5, file_size) if successful, None otherwise."""
    logger.info(f"Downloading: {manual['model']} - {manual['url']}")

    page.goto(manual["url"], wait_until="networkidle")
    random_delay(1, 2)

    # Look for download button
    download_btn = page.query_selector('a:has-text("Download"), button:has-text("Download")')
    if not download_btn:
        # Try alternative selectors
        download_btn = page.query_selector('.download-btn, .btn-download, [class*="download"]')

    if not download_btn:
        logger.warning(f"No download button found for {manual['model']}")
        return None

    # Click download button
    download_btn.click()
    random_delay(1, 2)

    # Check for captcha
    captcha_frame = page.query_selector('iframe[src*="recaptcha"]')
    if captcha_frame:
        if not wait_for_captcha_solved(page):
            return None

    # Prepare download directory
    brand_dir = download_dir / sanitize_filename(brand)
    brand_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{sanitize_filename(manual['model'])}_{sanitize_filename(manual['doc_type'])}.pdf"
    file_path = brand_dir / filename

    # Flow: Captcha solved → "Get Manual" button → "Download PDF" button

    # Step 1: Wait for and click "Get Manual" button
    logger.info("Waiting for Get Manual button...")
    try:
        get_manual_btn = page.wait_for_selector(
            'a:has-text("Get Manual"), button:has-text("Get Manual")',
            timeout=10000
        )
        if get_manual_btn:
            logger.info("Found Get Manual button, clicking...")
            get_manual_btn.click()
            random_delay(1, 2)
    except Exception as e:
        logger.debug(f"No Get Manual button found: {e}")

    # Step 2: Wait for "Download PDF" link and extract URL
    logger.info("Waiting for Download PDF link...")
    try:
        pdf_link = page.wait_for_selector(
            'a[href*="manualslib.com/pdf"], a[href*=".pdf"][href*="take=binary"], a:has-text("Download PDF")',
            timeout=10000
        )
        if pdf_link:
            pdf_url = pdf_link.get_attribute("href")
            if pdf_url:
                logger.info(f"Found PDF URL: {pdf_url}")
                if download_file_from_url(pdf_url, file_path):
                    sha1, md5 = compute_checksums(file_path)
                    file_size = file_path.stat().st_size
                    logger.info(f"Downloaded: {file_path} ({file_size} bytes, SHA1: {sha1[:8]}..., MD5: {md5[:8]}...)")
                    return str(file_path), sha1, md5, file_size
    except Exception as e:
        logger.debug(f"No Download PDF link found: {e}")

    # Fallback: look for any direct PDF link
    pdf_link = page.query_selector('a[href*=".pdf"]')
    if pdf_link:
        pdf_url = pdf_link.get_attribute("href")
        if pdf_url:
            logger.info(f"Found fallback PDF URL: {pdf_url}")
            if download_file_from_url(pdf_url, file_path):
                sha1, md5 = compute_checksums(file_path)
                file_size = file_path.stat().st_size
                logger.info(f"Downloaded: {file_path} ({file_size} bytes, SHA1: {sha1[:8]}..., MD5: {md5[:8]}...)")
                return str(file_path), sha1, md5, file_size

    logger.warning(f"Could not find download mechanism for {manual['model']}")
    return None


def scrape_brand(page: Page, brand: str, download_dir: Path, download: bool = True, category_urls: list[str] = None, categories: list[str] = None):
    """Scrape all TV manuals for a brand.

    Args:
        page: Playwright page object
        brand: Brand slug
        download_dir: Directory to download files to
        download: Whether to download files after scraping
        category_urls: List of full category URLs to scrape (from discovered brands)
        categories: List of category slugs like ['tv', 'tv-dvd-combo'] to build URLs from
    """
    logger.info(f"Starting scrape for brand: {brand}")

    # Determine which category URLs to scrape
    urls_to_scrape = []
    if category_urls:
        # Use provided category URLs (from discovered brands)
        urls_to_scrape = [(url, None) for url in category_urls]
    elif categories:
        # Build URLs from category slugs
        for cat in categories:
            url = f"{BASE_URL}/brand/{brand}/{cat}.html"
            urls_to_scrape.append((url, cat))
    else:
        # Default to just "tv" category
        urls_to_scrape = [(f"{BASE_URL}/brand/{brand}/tv.html", "tv")]

    # Scrape all category listings
    total_manual_count = 0
    for cat_url, cat_name in urls_to_scrape:
        manual_count = scrape_category_listing(page, brand, cat_url, cat_name)
        total_manual_count += manual_count
        random_delay(1, 2)

    if not download:
        logger.info(f"Scraping complete for {brand}. Found {total_manual_count} manuals. Skipping downloads.")
        return

    # Download manuals that haven't been downloaded yet (excludes archived)
    pending = database.get_undownloaded_manuals(brand)
    logger.info(f"Found {len(pending)} manuals to download for {brand}")

    for manual_record in pending:
        try:
            # Extract manualslib_id if not already in DB
            manualslib_id = manual_record.get("manualslib_id")
            if not manualslib_id:
                manualslib_id = extract_manualslib_id(manual_record["manual_url"])
                if manualslib_id:
                    database.update_manualslib_id(manual_record["id"], manualslib_id)

            # Check if already archived on archive.org
            if manualslib_id:
                logger.info(f"Checking archive.org for {manual_record['model']} (ID: {manualslib_id})...")
                is_archived, archive_url = check_archive_org(manualslib_id)
                if is_archived:
                    logger.info(f"Already archived: {archive_url}")
                    database.update_archived(manual_record["id"], archive_url)
                    continue

            # Not archived, proceed with download
            result = download_manual(
                page,
                {"model": manual_record["model"], "url": manual_record["manual_url"], "doc_type": manual_record["doc_type"]},
                download_dir,
                brand
            )
            if result:
                file_path, sha1, md5, file_size = result
                database.update_downloaded(manual_record["id"], file_path, sha1, md5, file_size)
            random_delay()
        except Exception as e:
            logger.error(f"Error downloading {manual_record['model']}: {e}")
            continue


def main():
    parser = argparse.ArgumentParser(description="Scrape TV manuals from ManualsLib")
    parser.add_argument("--brands", nargs="*", help="Specific brands to scrape (overrides config and discovered brands)")
    parser.add_argument("--discover-brands", action="store_true", help="Discover all brands with TV category")
    parser.add_argument("--use-discovered", action="store_true", help="Scrape all discovered brands (instead of config)")
    parser.add_argument("--scrape-only", action="store_true", help="Only scrape listings, don't download")
    parser.add_argument("--download-only", action="store_true", help="Only download pending manuals")
    parser.add_argument("--clear", action="store_true", help="Clear all manual records from database before scraping")
    parser.add_argument("--clear-brands", action="store_true", help="Clear all discovered brands from database")
    parser.add_argument("--clear-all", action="store_true", help="Clear both manuals and brands from database")
    args = parser.parse_args()

    config = load_config()
    download_dir = Path(config.get("download_dir", "./downloads")).resolve()
    download_dir.mkdir(parents=True, exist_ok=True)

    database.init_db()

    if args.clear_all:
        logger.info("Clearing all records from database (manuals and brands)...")
        database.clear_everything()
        logger.info("Database cleared.")
    elif args.clear_brands:
        logger.info("Clearing all discovered brands from database...")
        database.clear_brands()
        logger.info("Brands cleared.")
    elif args.clear:
        logger.info("Clearing all manual records from database...")
        database.clear_all()
        logger.info("Manuals cleared.")

    with sync_playwright() as p:
        # Launch browser in headed mode so human can solve captchas
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            # Brand discovery mode
            if args.discover_brands:
                # Brands are added to DB inside discover_brands() for real-time progress
                discovered_brands, all_tv_related_categories = discover_brands(page)

                brand_stats = database.get_brand_stats()
                logger.info(f"Brand discovery complete. Total: {brand_stats['total']}, Pending: {brand_stats['pending']}")

                # Log all TV-related categories for review
                if all_tv_related_categories:
                    logger.info("\n" + "=" * 60)
                    logger.info("ALL CATEGORIES WITH 'TV' IN NAME (for review):")
                    logger.info("=" * 60)
                    for cat in sorted(all_tv_related_categories):
                        logger.info(f"  - {cat}")
                    logger.info("=" * 60)
                    logger.info(f"Total: {len(all_tv_related_categories)} unique TV-related categories")
                    logger.info("Note: Only exact 'TV' and 'TV * Combo' patterns were included in brand discovery.")

                browser.close()
                return

            # Determine which brands to scrape
            if args.brands:
                brands = args.brands
                use_discovered_urls = False
            elif args.use_discovered:
                # Get discovered brands (will use full category URL support for scraping)
                discovered_brands_list = database.get_unscraped_brands()
                brands = [b["slug"] for b in discovered_brands_list]
                use_discovered_urls = True
                logger.info(f"Using {len(brands)} discovered brands")
            else:
                brands = config.get("brands", [])
                use_discovered_urls = False

            if args.download_only:
                # Only download pending manuals
                for brand in brands:
                    pending = database.get_undownloaded_manuals(brand)
                    logger.info(f"Downloading {len(pending)} pending manuals for {brand}")
                    for manual_record in pending:
                        try:
                            # Extract manualslib_id if not already in DB
                            manualslib_id = manual_record.get("manualslib_id")
                            if not manualslib_id:
                                manualslib_id = extract_manualslib_id(manual_record["manual_url"])
                                if manualslib_id:
                                    database.update_manualslib_id(manual_record["id"], manualslib_id)

                            # Check if already archived on archive.org
                            if manualslib_id:
                                logger.info(f"Checking archive.org for {manual_record['model']} (ID: {manualslib_id})...")
                                is_archived, archive_url = check_archive_org(manualslib_id)
                                if is_archived:
                                    logger.info(f"Already archived: {archive_url}")
                                    database.update_archived(manual_record["id"], archive_url)
                                    continue

                            # Not archived, proceed with download
                            result = download_manual(
                                page,
                                {"model": manual_record["model"], "url": manual_record["manual_url"], "doc_type": manual_record["doc_type"]},
                                download_dir,
                                brand
                            )
                            if result:
                                file_path, sha1, md5, file_size = result
                                database.update_downloaded(manual_record["id"], file_path, sha1, md5, file_size)
                            random_delay()
                        except Exception as e:
                            logger.error(f"Error downloading {manual_record['model']}: {e}")
            else:
                # Get configured categories (defaults to just "tv")
                configured_categories = config.get("categories", ["tv"])

                if use_discovered_urls:
                    # Use discovered brands from database with their saved category URLs
                    for brand_record in discovered_brands_list:
                        brand = brand_record["slug"]
                        # Parse saved category URLs
                        cat_urls_str = brand_record.get("tv_category_urls", "")
                        category_urls = [url.strip() for url in cat_urls_str.split(",") if url.strip()]

                        scrape_brand(page, brand, download_dir, download=not args.scrape_only, category_urls=category_urls)
                        database.mark_brand_scraped(brand_record["id"])
                        random_delay(3, 6)
                else:
                    # Use brands from config or CLI with configured categories
                    for brand in brands:
                        scrape_brand(page, brand, download_dir, download=not args.scrape_only, categories=configured_categories)
                        random_delay(3, 6)
        finally:
            browser.close()

    stats = database.get_stats()
    logger.info(f"Scraping complete. Total: {stats['total']}, Downloaded: {stats['downloaded']}, Archived: {stats['archived']}, Pending: {stats['pending']}")


if __name__ == "__main__":
    main()
