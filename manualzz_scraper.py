#!/usr/bin/env python3
"""Scraper for manualzz.com TV manuals."""

import argparse
import logging
import random
import re
import time
import urllib.parse
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

BASE_URL = "https://manualzz.com"
CAPTCHA_TIMEOUT = 300  # 5 minutes to solve captcha


def load_config() -> dict:
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def random_delay(min_sec: float = 2.0, max_sec: float = 5.0):
    delay = random.uniform(min_sec, max_sec)
    time.sleep(delay)


def sanitize_filename(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*]', '_', name)


def extract_manualzz_id(url: str) -> str | None:
    """Extract the numeric ID from a manualzz URL like /doc/12345/..."""
    match = re.search(r'/doc/(\d+)', url)
    if match:
        return match.group(1)
    # Also try download URL format
    match = re.search(r'/download/(\d+)', url)
    return match.group(1) if match else None


def extract_category_from_url(url: str) -> str:
    """Extract category name from catalog URL."""
    # URL like: /catalog/computers+%26+electronics/TVs+%26+monitors/CRT+TVs
    parts = url.rstrip('/').split('/')
    if parts:
        return urllib.parse.unquote_plus(parts[-1])
    return "Unknown"


def scrape_catalog_page(page: Page, catalog_url: str) -> int:
    """Scrape all manual listings from a manualzz catalog page (with pagination).

    Adds manuals to database immediately as they're found for real-time progress.
    Returns the count of manuals found.
    """
    seen_urls = set()
    category = extract_category_from_url(catalog_url)
    page_num = 1
    manual_count = 0

    current_url = catalog_url

    while current_url:
        logger.info(f"Scraping catalog page {page_num}: {current_url}")
        page.goto(current_url, wait_until="networkidle")
        random_delay(1, 2)

        # Find all manual/document listings (thumbnails)
        # Look for links to individual documents
        doc_links = page.query_selector_all('a[href*="/doc/"]')

        for link in doc_links:
            href = link.get_attribute("href")
            if not href:
                continue

            manual_url = href if href.startswith("http") else BASE_URL + href

            # Skip if already seen
            if manual_url in seen_urls:
                continue
            seen_urls.add(manual_url)

            # Try to get title from the link or nearby elements
            title = link.get_attribute("title") or link.inner_text().strip()

            # Clean up title
            if not title or len(title) < 3:
                # Try to find title in parent container
                parent = link.query_selector('xpath=..')
                if parent:
                    title_elem = parent.query_selector('h3, h4, .title, span')
                    if title_elem:
                        title = title_elem.inner_text().strip()

            if not title:
                title = "Unknown"

            # Extract manualzz ID
            manualzz_id = extract_manualzz_id(manual_url)

            # Try to extract brand from title (first word often is brand)
            brand = "Unknown"
            title_parts = title.split()
            if title_parts:
                brand = title_parts[0]

            # Add to database immediately for real-time progress
            manual_id = database.add_manual(
                brand=brand,
                model=title,  # Use title as model for manualzz
                manual_url=manual_url,
                source="manualzz",
                source_id=manualzz_id,
                category=category,
            )
            if manual_id:
                logger.info(f"Added: {title[:50]}...")
            manual_count += 1

        # Check for next page in pagination
        # Look for pagination links at bottom
        next_link = page.query_selector('a.next, a[rel="next"], .pagination a:has-text("Next"), .pagination a:has-text(">")')
        if next_link:
            next_href = next_link.get_attribute("href")
            if next_href and next_href not in seen_urls:
                current_url = next_href if next_href.startswith("http") else BASE_URL + next_href
                page_num += 1
                random_delay()
            else:
                current_url = None
        else:
            # Try numbered pagination - look for next page number
            current_page_elem = page.query_selector('.pagination .active, .pagination .current')
            if current_page_elem:
                try:
                    current_page_num = int(current_page_elem.inner_text().strip())
                    next_page_link = page.query_selector(f'.pagination a:has-text("{current_page_num + 1}")')
                    if next_page_link:
                        next_href = next_page_link.get_attribute("href")
                        if next_href:
                            current_url = next_href if next_href.startswith("http") else BASE_URL + next_href
                            page_num += 1
                            random_delay()
                        else:
                            current_url = None
                    else:
                        current_url = None
                except (ValueError, TypeError):
                    current_url = None
            else:
                current_url = None

    logger.info(f"Found {manual_count} manuals in catalog")
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


def download_manual(page: Page, manual: dict, download_dir: Path) -> str | None:
    """Download a single manual from manualzz. Returns file path if successful."""
    logger.info(f"Downloading: {manual['title']} - {manual['manual_url']}")

    page.goto(manual["manual_url"], wait_until="networkidle")
    random_delay(1, 2)

    # Look for download button with bi-download class
    download_btn = page.query_selector('a.bi-download, button.bi-download, [class*="bi-download"], a:has-text("Download")')

    if not download_btn:
        logger.warning(f"No download button found for {manual['title']}")
        return None

    # Click the download button
    download_btn.click()
    random_delay(1, 2)

    # Check if a "reminder" popup appeared
    reminder_link = page.query_selector('a[href*="/download/"]:has-text("still want to look it up")')
    if reminder_link:
        logger.info("Reminder popup detected, clicking through...")
        reminder_link.click()
        random_delay(1, 2)
    else:
        # Maybe we need to navigate directly to download page
        manualzz_id = manual.get("manualzz_id") or extract_manualzz_id(manual["manual_url"])
        if manualzz_id:
            download_page_url = f"{BASE_URL}/download/{manualzz_id}"
            logger.info(f"Navigating to download page: {download_page_url}")
            page.goto(download_page_url, wait_until="networkidle")
            random_delay(1, 2)

    # Now we should be on the download page with captcha
    # Check for captcha
    captcha_frame = page.query_selector('iframe[src*="recaptcha"]')
    if captcha_frame:
        if not wait_for_captcha_solved(page):
            return None
        random_delay(1, 2)

    # Prepare download directory
    brand = sanitize_filename(manual.get("brand", "unknown"))
    brand_dir = download_dir / "manualzz" / brand
    brand_dir.mkdir(parents=True, exist_ok=True)

    title = sanitize_filename(manual.get("title", "manual"))[:100]  # Limit filename length
    filename = f"{title}.pdf"
    file_path = brand_dir / filename

    # After captcha, look for the download link
    # The download link uses javascript:download_source()
    # We need to intercept the actual download or find the direct URL

    # Try to find the actual download link in .formats
    format_link = page.query_selector('.formats a.format, .formats a[onclick*="download_source"]')

    if format_link:
        # We need to click and capture the download
        logger.info("Found download format link, initiating download...")

        # Set up download handling
        with page.expect_download(timeout=60000) as download_info:
            try:
                format_link.click()
                download = download_info.value
                download.save_as(file_path)
                logger.info(f"Downloaded: {file_path}")
                return str(file_path)
            except Exception as e:
                logger.error(f"Download failed: {e}")
                return None

    # Fallback: try any PDF link
    pdf_link = page.query_selector('a[href*=".pdf"]')
    if pdf_link:
        pdf_url = pdf_link.get_attribute("href")
        if pdf_url:
            logger.info(f"Found PDF link: {pdf_url}")
            try:
                req = urllib.request.Request(pdf_url)
                req.add_header('User-Agent', 'Mozilla/5.0')
                with urllib.request.urlopen(req, timeout=120) as response:
                    with open(file_path, 'wb') as f:
                        f.write(response.read())
                logger.info(f"Downloaded: {file_path}")
                return str(file_path)
            except Exception as e:
                logger.error(f"Direct download failed: {e}")

    logger.warning(f"Could not download {manual['title']}")
    return None


def scrape_manualzz(catalog_urls: list[str], download_dir: Path, download: bool = True):
    """Main scraping function for manualzz."""
    database.init_db()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            total_count = 0
            for catalog_url in catalog_urls:
                logger.info(f"Scraping catalog: {catalog_url}")

                # Scrape all manual listings (adds to DB immediately for real-time progress)
                manual_count = scrape_catalog_page(page, catalog_url)
                total_count += manual_count

                random_delay(2, 4)

            if not download:
                logger.info(f"Scraping complete. Found {total_count} manuals. Skipping downloads.")
                browser.close()
                return

            # Download pending manuals
            pending = database.get_undownloaded_manuals(source="manualzz")
            logger.info(f"Found {len(pending)} manuals to download")

            for manual_record in pending:
                try:
                    file_path = download_manual(
                        page,
                        {
                            "title": manual_record["model"],
                            "brand": manual_record["brand"],
                            "manual_url": manual_record["manual_url"],
                            "manualzz_id": manual_record.get("source_id"),
                        },
                        download_dir
                    )
                    if file_path:
                        database.update_downloaded(manual_record["id"], file_path)
                    random_delay()
                except Exception as e:
                    logger.error(f"Error downloading {manual_record['model']}: {e}")
                    continue

        finally:
            browser.close()

    stats = database.get_stats(source="manualzz")
    logger.info(f"Manualzz scraping complete. Total: {stats['total']}, Downloaded: {stats['downloaded']}, Pending: {stats['pending']}")


def main():
    parser = argparse.ArgumentParser(description="Scrape TV manuals from Manualzz")
    parser.add_argument("--urls", nargs="*", help="Specific catalog URLs to scrape (overrides config)")
    parser.add_argument("--scrape-only", action="store_true", help="Only scrape listings, don't download")
    parser.add_argument("--download-only", action="store_true", help="Only download pending manuals")
    parser.add_argument("--clear", action="store_true", help="Clear all manualzz records from database before scraping")
    args = parser.parse_args()

    config = load_config()
    download_dir = Path(config.get("download_dir", "./downloads")).resolve()
    download_dir.mkdir(parents=True, exist_ok=True)

    database.init_db()

    if args.clear:
        logger.info("Clearing all manualzz records from database...")
        database.clear_manuals_by_source("manualzz")
        logger.info("Manualzz records cleared.")

    catalog_urls = args.urls or config.get("manualzz_urls", [])

    if not catalog_urls:
        logger.error("No catalog URLs specified. Add manualzz_urls to config.yaml or use --urls")
        return

    if args.download_only:
        # Only download pending manuals
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = context.new_page()

            try:
                pending = database.get_undownloaded_manuals(source="manualzz")
                logger.info(f"Found {len(pending)} pending manualzz downloads")

                for manual_record in pending:
                    try:
                        file_path = download_manual(
                            page,
                            {
                                "title": manual_record["model"],
                                "brand": manual_record["brand"],
                                "manual_url": manual_record["manual_url"],
                                "manualzz_id": manual_record.get("source_id"),
                            },
                            download_dir
                        )
                        if file_path:
                            database.update_downloaded(manual_record["id"], file_path)
                        random_delay()
                    except Exception as e:
                        logger.error(f"Error downloading {manual_record['model']}: {e}")
            finally:
                browser.close()
    else:
        scrape_manualzz(catalog_urls, download_dir, download=not args.scrape_only)


if __name__ == "__main__":
    main()
