import json
import time
from playwright.sync_api import sync_playwright

def test_site(url):
    print(f"⏳ Testing {url}...")
    try:
        start_time = time.time()
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            title = page.title()
            browser.close()
            print(f"✅ Success! ({time.time() - start_time:.1f}s) - Title: {title}")
    except Exception as e:
        print(f"❌ Failed: {str(e)}")
    print("-" * 50)

if __name__ == "__main__":
    urls = [
        "https://www.ixigo.com",
        "https://www.confirmtkt.com",
        "https://www.cleartrip.com",
        "https://blinkit.com/s/?q=milk",
        "https://www.flipkart.com/search?q=laptop"
    ]
    for u in urls:
        test_site(u)
