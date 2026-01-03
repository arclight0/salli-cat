#!/usr/bin/env python3
"""Integration with Turnstile-Solver-NEW API for bypassing Cloudflare challenges."""

import logging
import time
import urllib.request
import urllib.parse
import json
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# Default solver API endpoint (run Turnstile-Solver-NEW locally)
SOLVER_API_URL = "http://localhost:5072"

# Cache for config
_config_cache = None


def get_config() -> dict:
    """Load config.yaml."""
    global _config_cache
    if _config_cache is None:
        config_path = Path(__file__).parent / "config.yaml"
        if config_path.exists():
            with open(config_path) as f:
                _config_cache = yaml.safe_load(f) or {}
        else:
            _config_cache = {}
    return _config_cache


def get_sitekey_from_config(domain: str) -> str | None:
    """Get a manually configured sitekey for a domain."""
    config = get_config()
    sitekeys = config.get("turnstile_sitekeys", {})
    return sitekeys.get(domain)


def extract_turnstile_sitekey(page, wait_timeout: int = 15) -> str | None:
    """Extract Cloudflare Turnstile sitekey from the page."""

    # First, wait for the Turnstile widget/iframe to appear
    logger.info("Waiting for Turnstile widget to load...")
    try:
        page.wait_for_selector(
            'iframe[src*="challenges.cloudflare.com"], '
            'iframe[src*="turnstile"], '
            '.cf-turnstile, '
            '#turnstile-wrapper, '
            '[data-sitekey]',
            timeout=wait_timeout * 1000
        )
        # Extra wait for JS to populate attributes
        time.sleep(2)
    except Exception as e:
        logger.warning(f"Timeout waiting for Turnstile widget: {e}")

    try:
        # Try to find sitekey from various sources
        sitekey = page.evaluate("""
            () => {
                // Method 1: Check for cf-turnstile element with data-sitekey
                const turnstile = document.querySelector('.cf-turnstile[data-sitekey], [data-sitekey]');
                if (turnstile) {
                    const key = turnstile.getAttribute('data-sitekey');
                    if (key && key.length > 10) return key;
                }

                // Method 2: Check for turnstile in iframe src
                const iframes = document.querySelectorAll('iframe');
                for (const iframe of iframes) {
                    const src = iframe.getAttribute('src') || '';
                    if (src.includes('challenges.cloudflare.com') || src.includes('turnstile')) {
                        // Try to extract sitekey from URL params
                        const match = src.match(/[?&]k=([^&]+)/);
                        if (match) return match[1];

                        // Try sitekey param
                        const match2 = src.match(/sitekey=([^&]+)/);
                        if (match2) return match2[1];
                    }
                }

                // Method 3: Check script tags for sitekey patterns
                const scripts = document.querySelectorAll('script');
                for (const script of scripts) {
                    const text = script.textContent || script.innerText || '';

                    // Look for sitekey in various formats
                    const patterns = [
                        /sitekey['":\s]+['"]([0-9a-zA-Z_-]{20,})['"]/,
                        /data-sitekey['":\s]+['"]([0-9a-zA-Z_-]{20,})['"]/,
                        /"sitekey"\s*:\s*"([^"]+)"/,
                        /turnstile[^}]*sitekey['":\s]+['"]([^'"]+)['"]/i,
                    ];

                    for (const pattern of patterns) {
                        const match = text.match(pattern);
                        if (match && match[1].length > 10) return match[1];
                    }
                }

                // Method 4: Check for Cloudflare challenge options
                if (window._cf_chl_opt) {
                    // Sometimes the sitekey is in cK or similar
                    if (window._cf_chl_opt.cK) return window._cf_chl_opt.cK;
                    if (window._cf_chl_opt.sitekey) return window._cf_chl_opt.sitekey;
                }

                // Method 5: Check for turnstile render calls in page
                if (window.turnstile && window.turnstile._lastWidgetId) {
                    // Try to get sitekey from widget
                    const widget = document.querySelector('[data-turnstile-widget-id]');
                    if (widget) {
                        const key = widget.getAttribute('data-sitekey');
                        if (key) return key;
                    }
                }

                return null;
            }
        """)

        if sitekey:
            logger.info(f"Found sitekey: {sitekey[:30]}...")
        else:
            # Debug: log what we can see on the page
            debug_info = page.evaluate("""
                () => {
                    const iframes = Array.from(document.querySelectorAll('iframe')).map(f => f.src);
                    const cfOpt = window._cf_chl_opt ? Object.keys(window._cf_chl_opt) : [];
                    return {
                        iframes: iframes,
                        cfOptKeys: cfOpt,
                        hasTurnstile: !!document.querySelector('.cf-turnstile'),
                        title: document.title
                    };
                }
            """)
            logger.warning(f"Could not find sitekey. Debug info: {debug_info}")

        return sitekey
    except Exception as e:
        logger.warning(f"Error extracting sitekey: {e}")
        return None


def solve_turnstile(url: str, sitekey: str, api_url: str = SOLVER_API_URL, timeout: int = 120) -> str | None:
    """
    Call the Turnstile solver API to solve a Cloudflare challenge.

    Args:
        url: The URL of the page with the Turnstile challenge
        sitekey: The Turnstile sitekey
        api_url: Base URL of the solver API (default: http://localhost:6080)
        timeout: Maximum time to wait for solution in seconds

    Returns:
        The Turnstile token if successful, None otherwise
    """
    # Start the solve task
    params = urllib.parse.urlencode({
        'url': url,
        'sitekey': sitekey,
    })

    try:
        # POST to /turnstile to start solving
        req = urllib.request.Request(
            f"{api_url}/turnstile?{params}",
            method='POST',
            headers={'Content-Type': 'application/json'}
        )

        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode())
            task_id = result.get('taskId')

            if not task_id:
                logger.error(f"No taskId in solver response: {result}")
                return None

            logger.info(f"Turnstile solve task started: {task_id}")

    except Exception as e:
        logger.error(f"Error starting Turnstile solve: {e}")
        return None

    # Poll for result
    start_time = time.time()

    while time.time() - start_time < timeout:
        try:
            req = urllib.request.Request(
                f"{api_url}/result?id={task_id}",
                method='GET'
            )

            with urllib.request.urlopen(req, timeout=10) as response:
                result = json.loads(response.read().decode())
                status = result.get('status')

                if status == 'ready':
                    token = result.get('token')
                    elapsed = result.get('elapsed', 'unknown')
                    logger.info(f"Turnstile solved in {elapsed}s")
                    return token
                elif status == 'fail':
                    logger.error(f"Turnstile solve failed: {result}")
                    return None
                else:
                    # Still processing
                    logger.debug(f"Turnstile solving in progress...")

        except Exception as e:
            logger.warning(f"Error polling solver result: {e}")

        time.sleep(2)

    logger.error(f"Turnstile solve timeout after {timeout}s")
    return None


def inject_turnstile_token(page, token: str) -> bool:
    """
    Inject the solved Turnstile token into the page.

    Args:
        page: Playwright page object
        token: The solved Turnstile token

    Returns:
        True if injection successful, False otherwise
    """
    try:
        result = page.evaluate(f"""
            (token) => {{
                // Set the token in cf-turnstile-response input
                const inputs = document.querySelectorAll(
                    'input[name="cf-turnstile-response"], ' +
                    'input[name="g-recaptcha-response"], ' +
                    'textarea[name="cf-turnstile-response"]'
                );

                let found = false;
                for (const input of inputs) {{
                    input.value = token;
                    found = true;
                }}

                // Also try to set window.turnstile callback
                if (window.turnstile && window.turnstile.getResponse) {{
                    // Turnstile widget exists
                    found = true;
                }}

                // Trigger any callback that might be waiting
                if (window._cf_chl_opt && window._cf_chl_opt.cOgUHash) {{
                    found = true;
                }}

                return found;
            }}
        """, token)

        if result:
            logger.info("Turnstile token injected successfully")
        else:
            logger.warning("Could not find Turnstile input elements")

        return result

    except Exception as e:
        logger.error(f"Error injecting Turnstile token: {e}")
        return False


def is_solver_available(api_url: str = SOLVER_API_URL) -> bool:
    """Check if the Turnstile solver API is available."""
    try:
        req = urllib.request.Request(f"{api_url}/", method='GET')
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def solve_cloudflare_with_api(page, api_url: str = SOLVER_API_URL, timeout: int = 120) -> bool:
    """
    Attempt to solve Cloudflare Turnstile challenge using the solver API.

    Args:
        page: Playwright page object
        api_url: Base URL of the solver API
        timeout: Maximum time to wait for solution

    Returns:
        True if challenge solved, False otherwise
    """
    url = page.url

    # Try to get sitekey from config first (for domains where auto-detection fails)
    try:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc
        sitekey = get_sitekey_from_config(domain)
        if sitekey:
            logger.info(f"Using configured sitekey for {domain}")
    except Exception:
        sitekey = None

    # Fall back to extraction if not configured
    if not sitekey:
        sitekey = extract_turnstile_sitekey(page)

    if not sitekey:
        logger.warning("Could not extract Turnstile sitekey from page")
        return False

    logger.info(f"Found Turnstile sitekey: {sitekey[:20]}...")

    # Solve the challenge
    token = solve_turnstile(url, sitekey, api_url, timeout)

    if not token:
        return False

    # Inject the token
    inject_turnstile_token(page, token)

    # The page should auto-submit or we need to trigger it
    # Wait a moment for any auto-submit
    time.sleep(2)

    # Try clicking submit button if present
    try:
        submit_btn = page.query_selector(
            'button[type="submit"], '
            'input[type="submit"], '
            '.challenge-form button'
        )
        if submit_btn:
            submit_btn.click()
            time.sleep(3)
    except Exception:
        pass

    return True
