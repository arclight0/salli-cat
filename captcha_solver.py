"""2captcha integration for automatic reCAPTCHA solving."""

import logging
import time
import urllib.request
import urllib.parse
import json

logger = logging.getLogger(__name__)

TWOCAPTCHA_API_URL = "http://2captcha.com"


class TwoCaptchaSolver:
    """Solve reCAPTCHA using 2captcha.com API."""

    def __init__(self, api_key: str, poll_interval: int = 5, timeout: int = 120):
        """
        Initialize the solver.

        Args:
            api_key: Your 2captcha API key
            poll_interval: Seconds between polling for result (default: 5)
            timeout: Maximum seconds to wait for solution (default: 120)
        """
        self.api_key = api_key
        self.poll_interval = poll_interval
        self.timeout = timeout

    def solve_recaptcha(self, sitekey: str, page_url: str) -> str | None:
        """
        Solve a reCAPTCHA v2 challenge.

        Args:
            sitekey: The reCAPTCHA sitekey (data-sitekey attribute)
            page_url: The URL of the page with the captcha

        Returns:
            The g-recaptcha-response token if successful, None otherwise
        """
        logger.info(f"Submitting reCAPTCHA to 2captcha (sitekey: {sitekey[:20]}...)")

        # Submit the captcha
        task_id = self._submit_captcha(sitekey, page_url)
        if not task_id:
            return None

        logger.info(f"2captcha task ID: {task_id}")

        # Poll for result
        return self._poll_result(task_id)

    def _submit_captcha(self, sitekey: str, page_url: str) -> str | None:
        """Submit captcha to 2captcha and return task ID."""
        params = {
            "key": self.api_key,
            "method": "userrecaptcha",
            "googlekey": sitekey,
            "pageurl": page_url,
            "json": "1",
        }

        url = f"{TWOCAPTCHA_API_URL}/in.php?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())

            if data.get("status") == 1:
                return data.get("request")
            else:
                error = data.get("request", "Unknown error")
                logger.error(f"2captcha submit failed: {error}")
                return None

        except Exception as e:
            logger.error(f"2captcha submit error: {e}")
            return None

    def _poll_result(self, task_id: str) -> str | None:
        """Poll 2captcha for the solution."""
        params = {
            "key": self.api_key,
            "action": "get",
            "id": task_id,
            "json": "1",
        }

        url = f"{TWOCAPTCHA_API_URL}/res.php?{urllib.parse.urlencode(params)}"
        start_time = time.time()

        while time.time() - start_time < self.timeout:
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as response:
                    data = json.loads(response.read().decode())

                if data.get("status") == 1:
                    token = data.get("request")
                    logger.info("2captcha solved successfully")
                    return token
                elif data.get("request") == "CAPCHA_NOT_READY":
                    logger.debug("2captcha: still solving...")
                    time.sleep(self.poll_interval)
                else:
                    error = data.get("request", "Unknown error")
                    logger.error(f"2captcha error: {error}")
                    return None

            except Exception as e:
                logger.error(f"2captcha poll error: {e}")
                time.sleep(self.poll_interval)

        logger.error("2captcha timeout")
        return None

    def get_balance(self) -> float | None:
        """Get current 2captcha account balance."""
        params = {
            "key": self.api_key,
            "action": "getbalance",
            "json": "1",
        }

        url = f"{TWOCAPTCHA_API_URL}/res.php?{urllib.parse.urlencode(params)}"

        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())

            if data.get("status") == 1:
                return float(data.get("request", 0))
            else:
                logger.error(f"Failed to get balance: {data.get('request')}")
                return None

        except Exception as e:
            logger.error(f"Error getting balance: {e}")
            return None


def extract_sitekey_from_page(page) -> str | None:
    """
    Extract reCAPTCHA sitekey from a Playwright page.

    Looks for:
    1. data-sitekey attribute on reCAPTCHA div
    2. sitekey in reCAPTCHA iframe URL
    """
    try:
        # Method 1: Look for data-sitekey attribute
        sitekey = page.evaluate("""
            () => {
                // Check for data-sitekey on various elements
                const selectors = [
                    '.g-recaptcha[data-sitekey]',
                    '[data-sitekey]',
                    '#recaptcha[data-sitekey]'
                ];
                for (const selector of selectors) {
                    const elem = document.querySelector(selector);
                    if (elem) {
                        return elem.getAttribute('data-sitekey');
                    }
                }
                return null;
            }
        """)

        if sitekey:
            return sitekey

        # Method 2: Extract from iframe URL
        iframe = page.query_selector('iframe[src*="recaptcha"]')
        if iframe:
            src = iframe.get_attribute("src")
            if src and "k=" in src:
                # Parse sitekey from URL like: ...recaptcha/api2/anchor?k=SITEKEY&...
                import re
                match = re.search(r'[?&]k=([^&]+)', src)
                if match:
                    return match.group(1)

        return None

    except Exception as e:
        logger.error(f"Error extracting sitekey: {e}")
        return None


def inject_captcha_response(page, token: str) -> bool:
    """
    Inject the solved captcha token into the page.

    Args:
        page: Playwright page object
        token: The g-recaptcha-response token from 2captcha

    Returns:
        True if injection was successful
    """
    try:
        result = page.evaluate(f"""
            (token) => {{
                // Find and fill the g-recaptcha-response textarea
                const responseTextarea = document.querySelector('[name="g-recaptcha-response"]');
                if (responseTextarea) {{
                    responseTextarea.value = token;
                    responseTextarea.style.display = 'block';  // Make visible for debugging
                }}

                // Also try to find hidden textarea in iframe (for invisible recaptcha)
                const hiddenTextareas = document.querySelectorAll('textarea[name="g-recaptcha-response"]');
                hiddenTextareas.forEach(ta => {{
                    ta.value = token;
                }});

                // Try to trigger the callback if it exists
                if (typeof ___grecaptcha_cfg !== 'undefined') {{
                    const clients = ___grecaptcha_cfg.clients;
                    if (clients) {{
                        for (const key in clients) {{
                            const client = clients[key];
                            if (client && client.callback) {{
                                client.callback(token);
                                return true;
                            }}
                        }}
                    }}
                }}

                // Alternative: Look for callback in grecaptcha object
                if (typeof grecaptcha !== 'undefined' && grecaptcha.enterprise) {{
                    // Enterprise recaptcha
                    return true;
                }}

                return responseTextarea !== null;
            }}
        """, token)

        return result

    except Exception as e:
        logger.error(f"Error injecting captcha response: {e}")
        return False
