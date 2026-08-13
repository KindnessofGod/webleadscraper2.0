"""Stage A: Playwright-driven Google Maps grid scraper.

Maintenance note: Google Maps' DOM uses obfuscated, frequently-changing CSS
class names. We deliberately select on stable attributes instead --
`role="feed"` for the results list, `data-item-id` on detail-panel buttons
(e.g. `data-item-id="authority"` for the website link, `data-item-id="oloc"`
for the address, `href^="tel:"` for phone) -- the same approach used by most
maintained open-source Maps scrapers, because these attributes change far
less often than class names. If extraction starts silently returning empty
fields, this is the first place to check with the browser inspector before
assuming the pipeline itself is broken.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from playwright.async_api import Browser, Page, Playwright, Response, TimeoutError as PWTimeoutError

from src.grid import GridCell
from src.proxy import ProxyPool, ProxySession

logger = logging.getLogger("pipeline.scraper")

CAPTCHA_MARKERS = [
    "unusual traffic",
    "detected unusual traffic",
    "recaptcha",
    "our systems have detected",
]

RESULTS_FEED_SELECTOR = 'div[role="feed"]'
RESULT_CARD_SELECTOR = 'div[role="feed"] > div > div[role="article"], div[role="feed"] a[href*="/maps/place/"]'
MAX_RESULTS_PER_QUERY = 200


class CaptchaDetected(Exception):
    pass


@dataclass
class ScrapedLead:
    business_name: str
    category_raw: Optional[str] = None
    address: Optional[str] = None
    phone_raw: Optional[str] = None
    website: Optional[str] = None
    maps_url: Optional[str] = None
    place_id: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    rating: Optional[float] = None
    review_count: Optional[int] = None
    permanently_closed: bool = False


@dataclass
class CellScrapeResult:
    leads: list[ScrapedLead] = field(default_factory=list)
    bytes_used: int = 0
    outcome: str = "pass"  # pass | empty | error | captcha
    error_detail: Optional[str] = None
    http_status: Optional[int] = None
    retry_count: int = 0


def _looks_like_captcha(html: str) -> bool:
    lowered = html.lower()
    return any(marker in lowered for marker in CAPTCHA_MARKERS)


CHROMIUM_LAUNCH_ARGS = [
    # /dev/shm defaults to a small size on most cloud VMs (EC2 included);
    # Chromium's renderer processes hang or crash under load without this,
    # especially on JS-heavy pages like Google Maps under concurrency.
    "--disable-dev-shm-usage",
    # Google advertises HTTP/3 (QUIC, over UDP) via the alt-svc header.
    # Chromium will try to use it for a page's sub-resource requests; a
    # CONNECT-based HTTP proxy only tunnels TCP and can't forward QUIC at
    # all, so those attempts hang silently and block domcontentloaded --
    # this is what caused every navigation to time out even though the
    # proxy itself worked fine (plain curl never attempts QUIC). Forcing
    # TCP-only HTTP/2 avoids that.
    "--disable-quic",
    # Blink sets navigator.webdriver=true by default, which Google Maps'
    # bot-detection reads and responds to by silently black-holing the
    # connection (no response, no captcha page -- indistinguishable from a
    # network hang) rather than serving content. This is what caused every
    # navigation to time out even after proxy auth, sticky ports, and the
    # per-context proxy setup were all confirmed working via curl and via
    # plain non-Google destinations through the same proxy.
    "--disable-blink-features=AutomationControlled",
]

# Default Playwright/Chromium UA string literally contains "HeadlessChrome",
# an easy bot-detection tell. Use a plain recent desktop Chrome UA instead.
DESKTOP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


async def launch_browser(pw: Playwright) -> Browser:
    """One Chromium *process* shared for the whole scrape run -- callers
    open one lightweight context per grid cell against it rather than each
    grid cell spawning its own browser process (which is what made 8
    concurrent cells launch 8 full Chromium processes and starve a
    t3.small's 2GB RAM).

    The `proxy={"server": "per-context"}` placeholder is required for
    Chromium to honor a *per-context* proxy at all -- without a proxy set
    at browser-launch time, Chromium's network/proxy-resolver service never
    properly initializes for later per-context overrides, and requests
    just hang indefinitely instead of failing cleanly (this is what caused
    100% navigation timeouts even though curl proved the proxy itself,
    credentials, and sticky-port scheme all worked). See Playwright docs on
    `browser.newContext(proxy=...)`.
    """
    return await pw.chromium.launch(
        headless=True,
        args=CHROMIUM_LAUNCH_ARGS,
        proxy={"server": "per-context"},
    )


class _ByteCounter:
    def __init__(self):
        self.total = 0

    def on_response(self, response: Response) -> None:
        try:
            length = response.headers.get("content-length")
            self.total += int(length) if length else 0
        except Exception:
            pass


async def _extract_detail_fields(page: Page) -> dict:
    """Reads the currently-open place detail panel."""
    fields: dict = {}

    try:
        name_el = page.locator("h1").first
        fields["business_name"] = (await name_el.text_content(timeout=3000) or "").strip()
    except PWTimeoutError:
        fields["business_name"] = ""

    try:
        website_el = page.locator('a[data-item-id="authority"]').first
        fields["website"] = await website_el.get_attribute("href", timeout=1500)
    except Exception:
        fields["website"] = None

    try:
        phone_el = page.locator('button[data-item-id^="phone:tel:"], a[href^="tel:"]').first
        raw = await phone_el.get_attribute("data-item-id", timeout=1500)
        if raw and raw.startswith("phone:tel:"):
            fields["phone_raw"] = raw.split("phone:tel:", 1)[1]
        else:
            href = await phone_el.get_attribute("href", timeout=1500)
            fields["phone_raw"] = href.replace("tel:", "") if href else None
    except Exception:
        fields["phone_raw"] = None

    try:
        addr_el = page.locator('button[data-item-id="oloc"]').first
        fields["address"] = await addr_el.get_attribute("aria-label", timeout=1500)
        if fields["address"]:
            fields["address"] = fields["address"].replace("Address: ", "")
    except Exception:
        fields["address"] = None

    try:
        category_el = page.locator('button[jsaction*="category"]').first
        fields["category_raw"] = (await category_el.text_content(timeout=1500) or "").strip() or None
    except Exception:
        fields["category_raw"] = None

    try:
        rating_el = page.locator('div[role="img"][aria-label*="star"]').first
        aria = await rating_el.get_attribute("aria-label", timeout=1500)
        if aria:
            # typical format: "4.5 stars 213 Reviews"
            parts = aria.replace("stars", "").replace("Reviews", "").split()
            fields["rating"] = float(parts[0])
            fields["review_count"] = int(parts[1].replace(",", "")) if len(parts) > 1 else None
    except Exception:
        fields["rating"] = None
        fields["review_count"] = None

    try:
        html = await page.content()
        fields["permanently_closed"] = "permanently closed" in html.lower()
    except Exception:
        fields["permanently_closed"] = False

    fields["maps_url"] = page.url
    return fields


async def scrape_grid_cell(
    browser: Browser,
    cell: GridCell,
    query: str,
    proxy_session: ProxySession,
    zoom: int,
    delay_min: float,
    delay_max: float,
    nav_timeout_ms: int = 25000,
) -> CellScrapeResult:
    result = CellScrapeResult()
    url = cell.maps_search_url(query, zoom)
    counter = _ByteCounter()

    context = await browser.new_context(
        proxy=proxy_session.playwright_proxy(),
        locale="en-US",
        viewport={"width": 1280, "height": 900},
        user_agent=DESKTOP_USER_AGENT,
    )
    try:
        page = await context.new_page()
        page.on("response", counter.on_response)
        page.set_default_navigation_timeout(nav_timeout_ms)

        resp = await page.goto(url, wait_until="domcontentloaded")
        result.http_status = resp.status if resp else None

        html = await page.content()
        if _looks_like_captcha(html):
            result.outcome = "captcha"
            raise CaptchaDetected(f"captcha marker on grid cell {cell.id}")

        try:
            await page.wait_for_selector(RESULTS_FEED_SELECTOR, timeout=8000)
        except PWTimeoutError:
            # Genuinely empty result set for this cell/query -- not an error.
            result.outcome = "empty"
            return result

        # Scroll the results feed to load up to the 200-result cap.
        feed = page.locator(RESULTS_FEED_SELECTOR)
        seen_hrefs: set[str] = set()
        stagnant_scrolls = 0
        while len(seen_hrefs) < MAX_RESULTS_PER_QUERY and stagnant_scrolls < 4:
            cards = page.locator('div[role="feed"] a[href*="/maps/place/"]')
            count = await cards.count()
            hrefs = set()
            for i in range(count):
                href = await cards.nth(i).get_attribute("href")
                if href:
                    hrefs.add(href)
            if len(hrefs) == len(seen_hrefs):
                stagnant_scrolls += 1
            else:
                stagnant_scrolls = 0
            seen_hrefs = hrefs
            await feed.evaluate("el => el.scrollBy(0, el.scrollHeight)")
            await asyncio.sleep(random.uniform(0.8, 1.6))

        if not seen_hrefs:
            result.outcome = "empty"
            return result

        for href in list(seen_hrefs)[:MAX_RESULTS_PER_QUERY]:
            await asyncio.sleep(random.uniform(delay_min, delay_max))
            try:
                await page.goto(href, wait_until="domcontentloaded")
                html = await page.content()
                if _looks_like_captcha(html):
                    result.outcome = "captcha"
                    raise CaptchaDetected(f"captcha marker mid-cell {cell.id}")

                fields = await _extract_detail_fields(page)
                if not fields.get("business_name"):
                    continue
                lead = ScrapedLead(
                    business_name=fields["business_name"],
                    category_raw=fields.get("category_raw"),
                    address=fields.get("address"),
                    phone_raw=fields.get("phone_raw"),
                    website=fields.get("website"),
                    maps_url=fields.get("maps_url"),
                    lat=cell.lat,
                    lon=cell.lon,
                    rating=fields.get("rating"),
                    review_count=fields.get("review_count"),
                    permanently_closed=fields.get("permanently_closed", False),
                )
                result.leads.append(lead)
            except CaptchaDetected:
                raise
            except Exception as exc:  # noqa: BLE001 -- one bad card must not kill the batch
                logger.warning("card_extract_failed cell=%s href=%s err=%s", cell.id, href, exc)
                continue

    finally:
        result.bytes_used = counter.total
        await context.close()

    return result


async def scrape_grid_cell_with_retry(
    browser: Browser,
    cell: GridCell,
    query: str,
    pool: ProxyPool,
    slot: int,
    zoom: int,
    delay_min: float,
    delay_max: float,
    max_retries: int,
    backoff_base: float,
) -> tuple[CellScrapeResult, ProxySession]:
    """Retries a grid cell on navigation failure, rotating to a fresh proxy
    exit IP on each retry rather than reusing the same one. Google Maps can
    silently black-hole (never respond, no captcha page -- indistinguishable
    from a network hang) requests from an individual exit IP it doesn't like,
    even when the same proxy/credentials work fine elsewhere; retrying the
    identical IP would just fail the same way every time, so a genuine
    navigation failure is treated as a signal to burn that IP and try again
    on a new one. Returns the last session actually used, for logging.
    """
    last_error: Optional[Exception] = None
    session = pool.get(slot)
    for attempt in range(max_retries + 1):
        try:
            result = await scrape_grid_cell(browser, cell, query, session, zoom, delay_min, delay_max)
            result.retry_count = attempt
            return result, session
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            if attempt < max_retries:
                backoff = backoff_base * (2 ** attempt)
                logger.warning(
                    "scrape_retry cell=%s attempt=%d backoff=%.1fs err=%s -- rotating proxy exit IP",
                    cell.id, attempt, backoff, exc,
                )
                await asyncio.sleep(backoff)
                session = pool.rotate(slot)
            else:
                logger.error("scrape_failed_permanently cell=%s err=%s", cell.id, exc)

    return CellScrapeResult(outcome="error", error_detail=str(last_error), retry_count=max_retries), session
