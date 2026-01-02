#!/usr/bin/env python3
"""Browser helper for launching Chromium with extensions (like uBlock Origin)."""

import logging
import tempfile
from pathlib import Path

from playwright.sync_api import BrowserContext, Playwright

logger = logging.getLogger(__name__)

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
) -> BrowserContext:
    """
    Launch Chromium with an extension loaded.

    To use extensions, Playwright requires a persistent context.

    Args:
        playwright: Playwright instance
        extension_path: Path to unpacked extension directory (must have manifest.json)
        headless: Run in headless mode (extensions may not work in headless)
        user_data_dir: Browser profile directory (created if None)
        viewport: Viewport dimensions dict {"width": 1280, "height": 800}
        user_agent: Custom user agent string

    Returns:
        BrowserContext with extension loaded
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

    # Build Chrome args
    chrome_args = []

    if extension_path:
        extension_path = Path(extension_path)
        if extension_path.exists() and (extension_path / "manifest.json").exists():
            ext_path_str = str(extension_path.absolute())
            chrome_args.extend([
                f"--disable-extensions-except={ext_path_str}",
                f"--load-extension={ext_path_str}",
            ])
            logger.info(f"Loading extension from: {ext_path_str}")
        else:
            logger.warning(f"Extension path not valid: {extension_path}")

    # Launch persistent context (required for extensions)
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(user_data_dir),
        headless=headless,
        args=chrome_args,
        viewport=viewport,
        user_agent=user_agent,
        # Grant permissions commonly needed
        permissions=["geolocation"],
        # Reduce detection
        ignore_https_errors=True,
    )

    return context


def setup_route_ad_blocking(page) -> None:
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
