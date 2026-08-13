#!/usr/bin/env python3
"""Standalone diagnostic for Google Maps navigation through the proxy.

Root cause confirmed: individual residential proxy exit IPs can be
silently black-holed by Google Maps specifically (no response, no captcha
page -- indistinguishable from a network hang) even though the same proxy
works fine for other destinations. This script mirrors the pipeline's
actual fix -- rotate to a fresh exit IP and retry -- so you can see how
many IPs it typically takes to get a clean one, before trusting the full
pipeline run.

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
from src.scraper import DESKTOP_USER_AGENT, launch_browser

URL = "https://www.google.com/maps/search/clinic/@6.422505,3.405533,16z"
MAX_ATTEMPTS = 5


async def try_once(browser, session, t0) -> bool:
    print(f"\nUsing proxy: {session.host}:{session.port} (user={session.username})")
    context = await browser.new_context(
        proxy=session.playwright_proxy(), locale="en-US", user_agent=DESKTOP_USER_AGENT
    )
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

    print(f"Navigating (wait_until='commit', timeout=20s): {URL}\n")
    try:
        resp = await page.goto(URL, wait_until="commit", timeout=20000)
        print(f"\n[{time.time()-t0:6.2f}s] COMMIT reached. status={resp.status if resp else None}")
    except Exception as exc:
        print(f"\n[{time.time()-t0:6.2f}s] COMMIT FAILED: {exc}")
        print("Requests still pending at failure:")
        for url in pending:
            print(f"  PENDING: {url}")
        await context.close()
        return False

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=20000)
        print(f"[{time.time()-t0:6.2f}s] domcontentloaded reached successfully.")
    except Exception as exc:
        print(f"[{time.time()-t0:6.2f}s] domcontentloaded TIMED OUT: {exc}")
        await context.close()
        return False

    title = await page.title()
    content_len = len(await page.content())
    print(f"Final page title: {title!r}")
    print(f"Final page content length: {content_len} bytes")
    await context.close()
    return True


async def main() -> None:
    cfg = load_config()
    pool = cfg.build_proxy_pool(concurrent_sessions=1, sticky_minutes=10, country="ng")
    t0 = time.time()

    async with async_playwright() as pw:
        browser = await launch_browser(pw)
        session = pool.get(0)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            print(f"\n=== Attempt {attempt}/{MAX_ATTEMPTS} ===")
            ok = await try_once(browser, session, t0)
            if ok:
                print(f"\nSUCCESS on attempt {attempt} with exit IP {session.host}:{session.port}")
                break
            session = pool.rotate(0)
        else:
            print(f"\nAll {MAX_ATTEMPTS} exit IPs failed -- something other than IP reputation is going on.")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
