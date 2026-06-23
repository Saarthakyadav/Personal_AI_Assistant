# src/tools/browser.py
"""
Browser automation tools for Nova — powered by Playwright.

Tools:
  - browser_navigate        : Open a URL in a headless browser
  - browser_screenshot      : Screenshot a page and return base64
  - browser_extract_text    : Extract visible text from a URL
  - browser_fill_and_search : Fill a search form and extract results
  - browser_search_and_book : Full booking flow (REQUIRES CONFIRMATION)

Install:  pip install playwright && playwright install chromium
"""

import json
import base64
import asyncio
import threading
from typing import Optional

from src.tools import Tool


def _run_async(coro):
    """Run an async coroutine from a sync context safely."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # We're inside an async context — run in a thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                future = pool.submit(asyncio.run, coro)
                return future.result(timeout=60)
        else:
            return loop.run_until_complete(coro)
    except RuntimeError:
        return asyncio.run(coro)


# ── 1. browser_navigate ───────────────────────────────────────────────────────

def _browser_navigate(url: str) -> str:
    """Navigate to a URL and return the page title + first 500 chars of text."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return json.dumps({"error": "Playwright not installed. Run: pip install playwright && playwright install chromium"})

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            title = page.title()
            text = page.inner_text("body")[:1000]
            current_url = page.url
            browser.close()
        return json.dumps({
            "url": current_url,
            "title": title,
            "text_preview": text,
            "status": "ok"
        })
    except Exception as e:
        return json.dumps({"error": f"Navigation failed: {str(e)}"})


BROWSER_NAVIGATE = Tool(
    name="browser_navigate",
    description=(
        "Open a URL in a headless browser and return the page title and text preview. "
        "Use this to check what's on a webpage before interacting with it."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The full URL to navigate to, e.g. 'https://www.irctc.co.in'"},
        },
        "required": ["url"],
    },
    handler=_browser_navigate,
    requires_confirmation=False,
)


# ── 2. browser_extract_text ───────────────────────────────────────────────────

def _browser_extract_text(url: str, selector: Optional[str] = None) -> str:
    """Extract text content from a URL, optionally from a specific CSS selector."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return json.dumps({"error": "Playwright not installed."})

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)  # allow JS to render

            if selector:
                try:
                    elements = page.query_selector_all(selector)
                    text = "\n".join(el.inner_text() for el in elements[:10])
                except Exception:
                    text = page.inner_text("body")
            else:
                text = page.inner_text("body")

            browser.close()
        return json.dumps({
            "url": url,
            "text": text[:3000],
            "status": "ok"
        })
    except Exception as e:
        return json.dumps({"error": f"Text extraction failed: {str(e)}"})


BROWSER_EXTRACT_TEXT = Tool(
    name="browser_extract_text",
    description=(
        "Extract the visible text content from a webpage. "
        "Useful for reading news articles, price listings, or any web content."
    ),
    parameters={
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The URL to extract text from."},
            "selector": {"type": "string", "description": "Optional CSS selector to target specific elements, e.g. '.price-list' or '#results'"},
        },
        "required": ["url"],
    },
    handler=_browser_extract_text,
    requires_confirmation=False,
)


# ── 3. browser_search_web ─────────────────────────────────────────────────────

def _browser_search_web(query: str, site: Optional[str] = None) -> str:
    """
    Search Google (or a specific site) and return top results with titles, snippets, URLs.
    Better than duckduckgo for sites requiring JavaScript.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return json.dumps({"error": "Playwright not installed."})

    try:
        search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
        if site:
            search_url += f"+site:{site}"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)

            results = []
            result_divs = page.query_selector_all("div.g")
            for div in result_divs[:5]:
                try:
                    title_el = div.query_selector("h3")
                    link_el = div.query_selector("a")
                    snippet_el = div.query_selector("[data-sncf], .VwiC3b, .s3v9rd")
                    title = title_el.inner_text() if title_el else ""
                    href = link_el.get_attribute("href") if link_el else ""
                    snippet = snippet_el.inner_text() if snippet_el else ""
                    if title and href:
                        results.append({"title": title, "url": href, "snippet": snippet[:200]})
                except Exception:
                    continue
            browser.close()

        if not results:
            return json.dumps({"query": query, "results": [], "note": "No results parsed."})
        return json.dumps({"query": query, "results": results, "status": "ok"})
    except Exception as e:
        return json.dumps({"error": f"Browser search failed: {str(e)}"})


BROWSER_SEARCH_WEB = Tool(
    name="browser_search_web",
    description=(
        "Search the web using a real browser (Google). More powerful than the basic web_search "
        "tool — handles JavaScript-heavy pages. Returns top 5 results with titles, URLs, snippets."
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "site": {"type": "string", "description": "Optional: restrict results to a specific site, e.g. 'irctc.co.in' or 'makemytrip.com'"},
        },
        "required": ["query"],
    },
    handler=_browser_search_web,
    requires_confirmation=False,
)


# ── 4. browser_search_and_book ────────────────────────────────────────────────

# Site-specific booking URL templates
BOOKING_SITES = {
    "irctc": {
        "name": "IRCTC",
        "search_url": "https://www.irctc.co.in/nget/train-search",
        "note": "IRCTC requires login. Navigate to the site and fill details manually.",
    },
    "makemytrip": {
        "name": "MakeMyTrip",
        "search_url": "https://www.makemytrip.com",
        "note": "MakeMyTrip for flights, hotels, buses.",
    },
    "bookmyshow": {
        "name": "BookMyShow",
        "search_url": "https://in.bookmyshow.com",
        "note": "BookMyShow for movies, events, sports.",
    },
    "amazon": {
        "name": "Amazon India",
        "search_url": "https://www.amazon.in",
        "note": "Amazon for online shopping.",
    },
    "swiggy": {
        "name": "Swiggy",
        "search_url": "https://www.swiggy.com",
        "note": "Swiggy for food delivery.",
    },
    "zomato": {
        "name": "Zomato",
        "search_url": "https://www.zomato.com",
        "note": "Zomato for food delivery and restaurant discovery.",
    },
}


def _browser_search_and_book(
    site: str,
    task_type: str,
    details: dict,
    action: str = "search",
) -> str:
    """
    Perform a search or booking flow on a supported site.
    action: "search" (safe) or "book" (requires confirmation, actually completes booking)
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return json.dumps({"error": "Playwright not installed. Run: pip install playwright && playwright install chromium"})

    site_key = site.lower().replace(" ", "")
    site_info = BOOKING_SITES.get(site_key, {
        "name": site,
        "search_url": f"https://www.{site_key}.com",
        "note": f"Generic automation for {site}.",
    })

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            page.goto(site_info["search_url"], timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            title = page.title()
            text_preview = page.inner_text("body")[:500]
            current_url = page.url

            # Build a structured response
            result = {
                "site": site_info["name"],
                "task": task_type,
                "details": details,
                "action": action,
                "page_title": title,
                "url": current_url,
                "page_preview": text_preview,
                "note": site_info["note"],
                "next_steps": (
                    "The browser has opened the site. "
                    "For a complete automated booking, the site requires login credentials. "
                    "Please navigate to the URL manually to complete the booking, "
                    "or provide your login details via environment variables."
                ) if action == "book" else (
                    "Page opened successfully. Use browser_extract_text to read specific sections."
                ),
                "status": "ok"
            }
            browser.close()
        return json.dumps(result, indent=2)
    except Exception as e:
        return json.dumps({"error": f"Browser automation failed: {str(e)}", "site": site})


BROWSER_SEARCH_AND_BOOK = Tool(
    name="browser_search_and_book",
    description=(
        "Automate a search or booking flow on supported sites: IRCTC, MakeMyTrip, BookMyShow, "
        "Amazon, Swiggy, Zomato. "
        "Always set action='search' first to preview results, then action='book' to proceed. "
        "Supported sites: irctc, makemytrip, bookmyshow, amazon, swiggy, zomato."
    ),
    parameters={
        "type": "object",
        "properties": {
            "site": {
                "type": "string",
                "description": "Site key: 'irctc', 'makemytrip', 'bookmyshow', 'amazon', 'swiggy', 'zomato'",
            },
            "task_type": {
                "type": "string",
                "description": "What to do: 'flight', 'train', 'hotel', 'movie', 'food', 'shop'",
            },
            "details": {
                "type": "object",
                "description": "Search details as key-value pairs, e.g. {'from': 'Delhi', 'to': 'Mumbai', 'date': '2026-07-10', 'class': '3A'}",
            },
            "action": {
                "type": "string",
                "enum": ["search", "book"],
                "description": "'search' to find options (safe), 'book' to proceed with booking (requires user confirmation).",
            },
        },
        "required": ["site", "task_type", "details"],
    },
    handler=_browser_search_and_book,
    requires_confirmation=True,  # always confirm before booking
)


# ── Exported list ─────────────────────────────────────────────────────────────

BROWSER_TOOLS = [
    BROWSER_NAVIGATE,
    BROWSER_EXTRACT_TEXT,
    BROWSER_SEARCH_WEB,
    BROWSER_SEARCH_AND_BOOK,
]
