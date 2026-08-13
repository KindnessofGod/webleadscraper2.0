#!/usr/bin/env python3
"""Standalone diagnostic for "Chromium hangs navigating to Google Maps
through the proxy even though curl works fine" -- logs every individual
network request/response Chromium makes, live, so we can see exactly which
resource never comes back instead of just getting a generic 25s timeout
from the pipeline. Bypasses the pipeline/retry logic entirely.

Usage: python scripts/diagnose_proxy.py
"""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from playwright.async_api import async_playwright

from src.config import load_config
from src.scraper import launch_browser

URL = "https://www.google.com/maps/search/clinic/@6.422505,3.405533,16z"


async def main() -> None:
    cfg = load_config()
    pool = cfg.build_proxy_pool(concurrent_sessions=1, sticky_minutes=10, country="ng")
    session = pool.get(0)
    print(f"Using proxy: {session.host}:{session.port} (user={session.username})")

    t0 = time.time()

    async with async_playwright() as pw:
        browser = await launch_browser(pw)
        context = await browser.new_context(proxy=session.playwright_proxy(), locale="en-US")
        page = await context.new_page()

        pending = set()

        def on_request(req):
            pending.add(req.url)
            print(f"[{time.time()-t0:6.2f}s] -> REQUEST  {req.method} {req.url}")

        def on_response(res):
            pending.discard(res.url)
            print(f"[{time.time()-t0:6.2f}s] <- RESPONSE {res.status} {res.url}")

        def on_failed(req):
            pending.discard(req.url)
            print(f"[{time.time()-t0:6.2f}s] xx FAILED   {req.failure} {req.url}")

        page.on("request", on_request)
        page.on("response", on_response)
        page.on("requestfailed", on_failed)

        print(f"\nNavigating (wait_until='commit', timeout=30s): {URL}\n")
        try:
            resp = await page.goto(URL, wait_until="commit", timeout=30000)
            print(f"\n[{time.time()-t0:6.2f}s] COMMIT reached. status={resp.status if resp else None}\n")
        except Exception as exc:
            print(f"\n[{time.time()-t0:6.2f}s] COMMIT FAILED: {exc}\n")
            print("Requests still pending at failure:")
            for url in pending:
                print(f"  PENDING: {url}")
            await context.close()
            await browser.close()
            return

        print(f"Waiting for domcontentloaded (timeout=30s)...\n")
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=30000)
            print(f"\n[{time.time()-t0:6.2f}s] domcontentloaded reached successfully.")
        except Exception as exc:
            print(f"\n[{time.time()-t0:6.2f}s] domcontentloaded TIMED OUT: {exc}")
            print("\nRequests still pending (these are what's blocking the page load):")
            for url in pending:
                print(f"  PENDING: {url}")

        title = await page.title()
        content_len = len(await page.content())
        print(f"\nFinal page title: {title!r}")
        print(f"Final page content length: {content_len} bytes")

        await context.close()
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
