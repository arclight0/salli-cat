#!/usr/bin/env python3
"""Browser helper for launching browsers with stealth and extension support."""

import logging
import os
import tempfile
from pathlib import Path

from playwright.sync_api import BrowserContext, Playwright, Page
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)


def get_web_unlocker_proxy() -> dict | None:
    """
    Get Bright Data Web Unlocker proxy config from environment variables.

    Returns a proxy dict for Playwright, or None if not configured.
    """
    host = os.environ.get("BRIGHTDATA_WEB_UNLOCKER_HOST")
    port = os.environ.get("BRIGHTDATA_WEB_UNLOCKER_PORT")
    user = os.environ.get("BRIGHTDATA_WEB_UNLOCKER_USER")
    password = os.environ.get("BRIGHTDATA_WEB_UNLOCKER_PASS")

    if host and port and user and password:
        return {
            "server": f"http://{host}:{port}",
            "username": user,
            "password": password,
        }
    return None

# Common ad-blocking patterns as fallback
AD_PATTERNS = [
    "*://*.doubleclick.net/*",
    "*://*.googlesyndication.com/*",
    "*://*.googleadservices.com/*",
    "*://*.google-analytics.com/*",
    "*://*.googletagmanager.com/*",
    "*://*.googletagservices.com/*",
    "*://*.adservice.google.com/*",
    "*://*.pagead2.googlesyndication.com/*",
    "*://pagead2.googlesyndication.com/*",
    "*://tpc.googlesyndication.com/*",
    "*://*.adsensecustomsearchads.com/*",
    "*://*.adnxs.com/*",
    "*://*.adsrvr.org/*",
    "*://*.amazon-adsystem.com/*",
    "*://*.facebook.net/*",
    "*://*.moatads.com/*",
    "*://*.rubiconproject.com/*",
    "*://*.pubmatic.com/*",
    "*://*.criteo.com/*",
    "*://*.outbrain.com/*",
    "*://*.taboola.com/*",
]


def launch_browser_with_extension(
    playwright: Playwright,
    extension_path: Path | str | None = None,
    headless: bool = False,
    user_data_dir: Path | str | None = None,
    viewport: dict = None,
    user_agent: str = None,
    use_proxy: bool = True,
    browser: str = "chromium",
) -> BrowserContext:
    """
    Launch a browser with optional extension and proxy support.

    To use extensions, Playwright requires a persistent context with Chromium.
    Extensions are NOT supported in Firefox or WebKit.

    Args:
        playwright: Playwright instance
        extension_path: Path to unpacked extension directory (must have manifest.json)
        headless: Run in headless mode (extensions may not work in headless)
        user_data_dir: Browser profile directory (created if None)
        viewport: Viewport dimensions dict {"width": 1280, "height": 800}
        user_agent: Custom user agent string
        use_proxy: If True, use Bright Data Web Unlocker proxy if configured
        browser: Browser to use - "chromium", "firefox", or "webkit"

    Returns:
        BrowserContext
    """
    if viewport is None:
        viewport = {"width": 1280, "height": 800}

    if user_agent is None:
        user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

    # Create user data dir if not provided
    if user_data_dir is None:
        user_data_dir = Path(tempfile.mkdtemp(prefix="playwright_profile_"))
    else:
        user_data_dir = Path(user_data_dir)
        user_data_dir.mkdir(parents=True, exist_ok=True)

    # Get the browser type
    browser = browser.lower()
    if browser == "firefox":
        browser_type = playwright.firefox
    elif browser == "webkit":
        browser_type = playwright.webkit
    else:
        browser_type = playwright.chromium
        browser = "chromium"  # Normalize

    logger.info(f"Using browser: {browser}")

    # Build browser args (extensions only work with Chromium)
    browser_args = []
    extension_loaded = False

    if extension_path and browser == "chromium":
        extension_path = Path(extension_path)
        if extension_path.exists() and (extension_path / "manifest.json").exists():
            ext_path_str = str(extension_path.absolute())
            browser_args.extend([
                f"--disable-extensions-except={ext_path_str}",
                f"--load-extension={ext_path_str}",
            ])
            logger.info(f"Loading extension from: {ext_path_str}")
            extension_loaded = True
        else:
            logger.warning(f"Extension path not valid: {extension_path}")
    elif extension_path and browser != "chromium":
        logger.warning(f"Extensions are only supported in Chromium, not {browser}")

    # Get proxy configuration
    proxy = get_web_unlocker_proxy() if use_proxy else None
    if proxy:
        logger.info(f"Using Bright Data Web Unlocker proxy: {proxy['server']}")

    # Launch persistent context
    context = browser_type.launch_persistent_context(
        user_data_dir=str(user_data_dir),
        headless=headless,
        args=browser_args if browser == "chromium" else [],
        viewport=viewport,
        user_agent=user_agent,
        proxy=proxy,
        # Grant permissions commonly needed
        permissions=["geolocation"],
        # Reduce detection
        ignore_https_errors=True,
    )

    return context, extension_loaded


def apply_stealth(page: Page) -> None:
    """
    Apply stealth patches to a page to avoid fingerprint detection.

    This patches various browser APIs to make automation less detectable:
    - Removes navigator.webdriver
    - Fixes Chrome runtime
    - Fixes permissions API
    - Fixes plugins/mimeTypes
    - And many other evasion techniques
    """
    stealth = Stealth()
    stealth.apply_stealth_sync(page)
    logger.info("Stealth patches applied to page")


def setup_route_ad_blocking(page: Page) -> None:
    """
    Set up route-based ad blocking on a page.

    This is a fallback when extension-based blocking isn't available.
    """
    def block_ads(route):
        route.abort()

    for pattern in AD_PATTERNS:
        page.route(pattern, block_ads)

    logger.info("Route-based ad blocking enabled")


def get_extension_path(config: dict, project_dir: Path) -> Path | None:
    """
    Get the extension path from config or default location.

    Config options:
    - ublock_origin_path: Explicit path to extension
    - extensions_dir: Directory containing extensions (default: ./extensions)

    Returns path to uBlock Origin extension or None.
    """
    # Check explicit path first
    if config.get("ublock_origin_path"):
        path = Path(config["ublock_origin_path"])
        if path.exists():
            return path

    # Check extensions directory
    extensions_dir = Path(config.get("extensions_dir", project_dir / "extensions"))
    ublock_path = extensions_dir / "ublock_origin"

    if ublock_path.exists() and (ublock_path / "manifest.json").exists():
        return ublock_path

    return None
