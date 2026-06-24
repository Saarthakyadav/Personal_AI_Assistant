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
    Search the web using DuckDuckGo via a real browser.
    FIX Bug #8: replaced brittle Google scraping with DuckDuckGo's stabler DOM.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return json.dumps({"error": "Playwright not installed."})

    try:
        search_query = query
        if site:
            search_query += f" site:{site}"
        search_url = f"https://duckduckgo.com/?q={search_query.replace(' ', '+')}"

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            page.goto(search_url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            results = []

            # DuckDuckGo result selectors (much more stable than Google's)
            result_articles = page.query_selector_all("article[data-testid='result']")
            if not result_articles:
                # Fallback: try older DDG layout
                result_articles = page.query_selector_all(".result")

            for article in result_articles[:5]:
                try:
                    title_el = article.query_selector("h2 a, a.result__a")
                    snippet_el = article.query_selector("[data-result='snippet'], .result__snippet")
                    title = title_el.inner_text() if title_el else ""
                    href = title_el.get_attribute("href") if title_el else ""
                    snippet = snippet_el.inner_text() if snippet_el else ""
                    if title and href:
                        results.append({"title": title, "url": href, "snippet": snippet[:200]})
                except Exception:
                    continue

            # If structured parsing fails, grab visible text as fallback
            if not results:
                body_text = page.inner_text("body")[:3000]
                results = [{"title": "Search results (raw)", "url": search_url, "snippet": body_text[:500]}]

            browser.close()

        return json.dumps({"query": query, "results": results, "status": "ok"})
    except Exception as e:
        return json.dumps({"error": f"Browser search failed: {str(e)}"})


BROWSER_SEARCH_WEB = Tool(
    name="browser_search_web",
    description=(
        "Search the web using a real browser (DuckDuckGo). More powerful than the basic web_search "
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


# ── Site-specific form fillers (FIX Bug #9) ──────────────────────────────────

def _fill_irctc_search(page, details: dict) -> str:
    """Attempt to fill IRCTC train search form."""
    try:
        from_station = details.get("from", "")
        to_station = details.get("to", "")
        date = details.get("date", "")

        filled = []

        if from_station:
            from_input = page.query_selector("input#origin, input[placeholder*='From'], p-autocomplete#origin input")
            if from_input:
                from_input.click()
                from_input.fill(from_station)
                page.wait_for_timeout(800)
                suggestion = page.query_selector(".ui-autocomplete-list-item, .ng-star-inserted .list-item")
                if suggestion:
                    suggestion.click()
                    page.wait_for_timeout(300)
                filled.append(f"from={from_station}")

        if to_station:
            to_input = page.query_selector("input#destination, input[placeholder*='To'], p-autocomplete#destination input")
            if to_input:
                to_input.click()
                to_input.fill(to_station)
                page.wait_for_timeout(800)
                suggestion = page.query_selector(".ui-autocomplete-list-item, .ng-star-inserted .list-item")
                if suggestion:
                    suggestion.click()
                    page.wait_for_timeout(300)
                filled.append(f"to={to_station}")

        if date:
            date_input = page.query_selector("input#jDate, input[placeholder*='Date'], p-calendar input")
            if date_input:
                date_input.click()
                date_input.fill(date)
                page.wait_for_timeout(300)
                filled.append(f"date={date}")

        return ", ".join(filled) if filled else "Could not fill form fields (site may require login)"
    except Exception as e:
        return f"Form fill partial: {str(e)}"


def _fill_makemytrip_search(page, details: dict) -> str:
    """Attempt to fill MakeMyTrip flight search form."""
    try:
        from_city = details.get("from", "")
        to_city = details.get("to", "")

        filled = []

        # Close any popups
        try:
            close_btn = page.query_selector("[data-cy='closeModal'], .autopop__close")
            if close_btn:
                close_btn.click()
                page.wait_for_timeout(500)
        except Exception:
            pass

        if from_city:
            from_el = page.query_selector("#fromCity, [data-cy='departureCity']")
            if from_el:
                from_el.click()
                page.wait_for_timeout(300)
                from_input = page.query_selector("input[placeholder*='From'], input.react-autosuggest__input")
                if from_input:
                    from_input.fill(from_city)
                    page.wait_for_timeout(800)
                    suggestion = page.query_selector(".react-autosuggest__suggestion, .makeFlex .font14")
                    if suggestion:
                        suggestion.click()
                        page.wait_for_timeout(300)
                    filled.append(f"from={from_city}")

        if to_city:
            to_el = page.query_selector("#toCity, [data-cy='arrivalCity']")
            if to_el:
                to_el.click()
                page.wait_for_timeout(300)
                to_input = page.query_selector("input[placeholder*='To'], input.react-autosuggest__input")
                if to_input:
                    to_input.fill(to_city)
                    page.wait_for_timeout(800)
                    suggestion = page.query_selector(".react-autosuggest__suggestion, .makeFlex .font14")
                    if suggestion:
                        suggestion.click()
                        page.wait_for_timeout(300)
                    filled.append(f"to={to_city}")

        return ", ".join(filled) if filled else "Could not fill form fields"
    except Exception as e:
        return f"Form fill partial: {str(e)}"


def _fill_amazon_search(page, details: dict) -> str:
    """Fill Amazon search box and extract results."""
    try:
        search_query = details.get("query", details.get("product", ""))
        
        # Check if results are already present from a direct URL load
        items = page.query_selector_all("[data-component-type='s-search-result']")
        if not items and search_query:
            search_box = page.query_selector("input#twotabsearchtextbox, input[name='field-keywords']")
            if search_box:
                search_box.fill(search_query)
                search_box.press("Enter")
                page.wait_for_timeout(3000)
                items = page.query_selector_all("[data-component-type='s-search-result']")

        results = []
        for item in items[:5]:
            try:
                title_el = item.query_selector("h2 a span, .a-text-normal")
                price_el = item.query_selector(".a-price .a-offscreen, .a-price-whole")
                title = title_el.inner_text() if title_el else ""
                price = price_el.inner_text() if price_el else "N/A"
                if title:
                    results.append(f"{title} — {price}")
            except Exception:
                continue

        if results:
            return f"Found {len(results)} results: " + " | ".join(results)
        return "Search page loaded — no items matched results selector structure"
    except Exception as e:
        return f"Amazon search partial: {str(e)}"


def _get_direct_search_url(site_key: str, task_type: str, details: dict) -> Optional[str]:
    """Generate direct query search URL to bypass homepage popups/selectors."""
    import urllib.parse
    import re
    
    if site_key == "amazon":
        query = details.get("query") or details.get("product") or ""
        if query:
            return f"https://www.amazon.in/s?k={urllib.parse.quote(query)}"
            
    elif site_key == "makemytrip":
        from_city = details.get("from", "").strip().upper()
        to_city = details.get("to", "").strip().upper()
        date = details.get("date", "").strip()
        
        if from_city and to_city:
            if re.match(r"^\d{4}-\d{2}-\d{2}$", date):
                parts = date.split("-")
                date = f"{parts[2]}/{parts[1]}/{parts[0]}"
            elif re.match(r"^\d{2}-\d{2}-\d{4}$", date):
                date = date.replace("-", "/")
            elif not date:
                import datetime
                date = (datetime.date.today() + datetime.timedelta(days=7)).strftime("%d/%m/%Y")
            
            airport_codes = {
                "DELHI": "DEL", "NEW DELHI": "DEL", "MUMBAI": "BOM", "BOMBAY": "BOM",
                "BANGALORE": "BLR", "BENGALURU": "BLR", "KOLKATA": "CCU", "CALCUTTA": "CCU",
                "CHENNAI": "MAA", "MADRAS": "MAA", "HYDERABAD": "HYD", "PUNE": "PNQ"
            }
            from_code = airport_codes.get(from_city, from_city)
            to_code = airport_codes.get(to_city, to_city)
            return f"https://www.makemytrip.com/flight/search?itinerary={urllib.parse.quote(from_code)}-{urllib.parse.quote(to_code)}-{date}&tripType=O&itineraryType=ONE_WAY&paxType=A-1_C-0_I-0&intl=false&cabinetClass=E"
            
    elif site_key == "swiggy":
        query = details.get("query") or details.get("food") or ""
        if query:
            return f"https://www.swiggy.com/search?query={urllib.parse.quote(query)}"
            
    elif site_key == "zomato":
        query = details.get("query") or details.get("food") or ""
        if query:
            return f"https://www.zomato.com/search?q={urllib.parse.quote(query)}"
            
    elif site_key == "bookmyshow":
        city = details.get("city", "mumbai").lower().strip()
        query = details.get("query") or details.get("movie") or ""
        if query:
            return f"https://in.bookmyshow.com/search?search={urllib.parse.quote(query)}"
        else:
            return f"https://in.bookmyshow.com/explore/movies-{city}"
            
    return None


def _browser_search_and_book(
    site: str,
    task_type: str,
    details: dict,
    action: str = "search",
) -> str:
    """
    Perform a search or booking flow on a supported site.
    FIX Bug #9: Now actually constructs direct query URLs and fills search forms where needed.
    action: "search" (safe) or "book" (requires confirmation via agent layer)
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

    # Generate direct search URL if possible to skip popups and land directly on results
    direct_url = _get_direct_search_url(site_key, task_type, details)
    target_url = direct_url if direct_url else site_info["search_url"]

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            page.goto(target_url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(2000)

            title = page.title()

            # Try site-specific form filling only if we didn't use a direct URL
            form_result = "Direct query URL navigated successfully" if direct_url else "No form filling attempted"
            if not direct_url:
                if site_key == "irctc":
                    form_result = _fill_irctc_search(page, details)
                elif site_key == "makemytrip":
                    form_result = _fill_makemytrip_search(page, details)
                elif site_key == "amazon":
                    form_result = _fill_amazon_search(page, details)
                elif site_key in ("swiggy", "zomato"):
                    form_result = "Food delivery sites require location access — page loaded for manual use"
                elif site_key == "bookmyshow":
                    form_result = "BookMyShow loaded — use browser_extract_text for specific content"
            else:
                # If we used direct URL but want to run the extraction part of the helpers:
                if site_key == "amazon":
                    form_result = _fill_amazon_search(page, details)

            text_preview = page.inner_text("body")[:800]
            final_url = page.url

            result = {
                "site": site_info["name"],
                "task": task_type,
                "details": details,
                "action": action,
                "page_title": title,
                "url": final_url,
                "form_result": form_result,
                "page_preview": text_preview,
                "note": site_info["note"],
                "next_steps": (
                    "Form fields have been filled and prepared where possible. "
                    "For complete booking, the site requires login credentials and checkout payment. "
                    "Navigate to the URL to review and complete the booking."
                ) if action == "book" else (
                    "Search query prepared and results extracted. Click the URL to view in browser."
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
        "Prepare a search query or navigate to booking pages on supported sites "
        "(IRCTC, MakeMyTrip, BookMyShow, Amazon, Swiggy, Zomato). "
        "This tool constructs direct search URLs and loads them using a headless browser to extract "
        "results, then returns the search URL and page preview. "
        "WARNING: This tool CANNOT complete transactions, checkout, or log into accounts due to "
        "security and authentication requirements (e.g. passwords, OTP, Captcha). The user must "
        "manually click the returned URL to complete any booking or purchase."
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
                "description": "Search details as key-value pairs, e.g. {'from': 'Delhi', 'to': 'Mumbai', 'date': '2026-07-10', 'class': '3A', 'query': 'laptop'}",
            },
            "action": {
                "type": "string",
                "enum": ["search", "book"],
                "description": "'search' to find options (safe), 'book' to prepare final booking state (requires confirmation).",
            },
        },
        "required": ["site", "task_type", "details"],
    },
    handler=_browser_search_and_book,
    requires_confirmation=False,
)


# ── Exported list ─────────────────────────────────────────────────────────────

BROWSER_TOOLS = [
    BROWSER_NAVIGATE,
    BROWSER_EXTRACT_TEXT,
    BROWSER_SEARCH_WEB,
    BROWSER_SEARCH_AND_BOOK,
]
