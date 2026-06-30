import json
import time
from src.tools.browser import _browser_search_and_book

def test_all_sites():
    print("🚀 Starting Automated Browser Tests for NEW alternatives...\n")
    
    tests = [
        {
            "site": "flipkart",
            "task_type": "shop",
            "details": {"query": "macbook pro m3"}
        },
        {
            "site": "cleartrip",
            "task_type": "flight",
            "details": {"from": "Delhi", "to": "Mumbai", "date": "10/07/2026"}
        },
        {
            "site": "ixigo",
            "task_type": "flight",
            "details": {"from": "DEL", "to": "BOM", "date": "10/07/2026"}
        },
        {
            "site": "confirmtkt",
            "task_type": "train",
            "details": {"from": "NDLS", "to": "BCT", "date": "10/07/2026"}
        },
        {
            "site": "blinkit",
            "task_type": "food",
            "details": {"query": "milk"}
        }
    ]
    
    for t in tests:
        site = t["site"]
        print(f"⏳ Testing {site.upper()}...")
        try:
            start_time = time.time()
            result_json = _browser_search_and_book(
                site=site,
                task_type=t["task_type"],
                details=t["details"],
                action="search"
            )
            result = json.loads(result_json)
            
            if "error" in result:
                print(f"❌ {site.upper()} Failed: {result['error']}")
            else:
                form_result = result.get('form_result', 'N/A')
                print(f"✅ {site.upper()} Success! ({time.time() - start_time:.1f}s)")
                print(f"   URL Generated: {result.get('url')}")
                
        except Exception as e:
            print(f"❌ {site.upper()} Crashed: {str(e)}")
        print("-" * 50)
        
if __name__ == "__main__":
    test_all_sites()
