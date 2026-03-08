"""
QU POS Fetcher — Net Sales for Overland (Retail + Catering), State, Eubank, Rapido
Uses the QU Enterprise Intelligence web dashboard (admin.qubeyond.com)
Authenticates with seth.brink credentials stored as environment variables
"""

import os
import json
import logging
import time
import re
from datetime import date, datetime

logger = logging.getLogger(__name__)

# QU POS store IDs (from admin.qubeyond.com store list)
STORE_IDS = {
    "overland": "810",     # 3001 Boise, ID - Overland Rd.
    "state": "811",        # 3002 - Boise, ID - State Street
    "eubank": "5645",      # 6601 - Albuquerque - Eubank Blvd.
    "rapido": "7209",      # 6602 - Albuquerque - San Mateo
}

# QU POS API endpoint (discovered from network traffic)
QU_API_BASE = "https://admin.qubeyond.com/api"
QU_REPORT_URL = "https://admin.qubeyond.com/reports/overview/summary-by-date"


def get_qu_credentials():
    """Get QU POS credentials from environment variables."""
    username = os.environ.get("QU_USERNAME", "seth.brink")
    password = os.environ.get("QU_PASSWORD", "")
    if not password:
        raise ValueError("QU_PASSWORD environment variable not set")
    return username, password


def fetch_all_locations(report_date: date = None) -> dict:
    """
    Fetch Net Sales for all QU POS locations.
    
    Returns dict with location keys mapping to data dicts.
    """
    if report_date is None:
        report_date = date.today()

    results = {
        "overland_retail": _empty_result(),
        "overland_catering": _empty_result(),
        "state": _empty_result(),
        "eubank": _empty_result(),
        "rapido": _empty_result(),
    }

    try:
        username, password = get_qu_credentials()
    except ValueError as e:
        logger.warning(f"QU POS credentials not configured: {e}")
        return results

    # Try Playwright first (preferred), fall back to requests-based approach
    try:
        return _fetch_via_playwright(report_date, username, password)
    except ImportError:
        logger.warning("Playwright not available, trying requests approach")
    except Exception as e:
        logger.error(f"Playwright fetch failed: {e}")

    # Fallback: try requests-based session
    try:
        return _fetch_via_requests(report_date, username, password)
    except Exception as e:
        logger.error(f"Requests fetch failed: {e}")

    return results


def _fetch_via_playwright(report_date: date, username: str, password: str) -> dict:
    """Fetch QU POS data using Playwright browser automation."""
    from playwright.sync_api import sync_playwright

    results = {
        "overland_retail": _empty_result(),
        "overland_catering": _empty_result(),
        "state": _empty_result(),
        "eubank": _empty_result(),
        "rapido": _empty_result(),
    }

    date_str = report_date.strftime("%m/%d/%Y")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        try:
            # Login
            logger.info("Logging into QU POS...")
            page.goto("https://admin.qubeyond.com/", wait_until="networkidle")

            # Check if already logged in
            if "login" in page.url.lower() or page.query_selector("input[type='password']"):
                page.fill("input[name='username'], input[type='text']", username)
                page.fill("input[type='password']", password)
                page.click("button[type='submit'], input[type='submit']")
                page.wait_for_url("**/configuration/**", timeout=15000)

            logger.info("Logged in successfully")

            # Fetch data for each location
            for location_key, store_id in STORE_IDS.items():
                logger.info(f"Fetching data for {location_key} (store {store_id})...")
                try:
                    data = _fetch_location_data(page, store_id, date_str)
                    
                    if location_key == "overland":
                        # Split Overland into retail vs catering
                        results["overland_retail"] = _extract_retail(data)
                        results["overland_catering"] = _extract_catering(data)
                    else:
                        results[location_key] = data
                        
                except Exception as e:
                    logger.error(f"Error fetching {location_key}: {e}")

        finally:
            browser.close()

    return results


def _fetch_location_data(page, store_id: str, date_str: str) -> dict:
    """Fetch Summary By Date report for a specific store."""
    # Navigate to Summary By Date report
    page.goto(QU_REPORT_URL, wait_until="networkidle")
    time.sleep(1)

    # Click Show Filters if available
    try:
        show_filters = page.query_selector("button:has-text('Show Filters')")
        if show_filters:
            show_filters.click()
            time.sleep(0.5)
    except Exception:
        pass

    # Set date to Yesterday (most recent complete day)
    try:
        date_select = page.query_selector("select")
        if date_select:
            date_select.select_option("Yesterday")
    except Exception:
        pass

    # Select Store List radio
    try:
        store_list_radio = page.query_selector("label:has-text('Store List')")
        if store_list_radio:
            store_list_radio.click()
            time.sleep(0.3)
    except Exception:
        pass

    # Type store ID in the search box
    try:
        store_input = page.query_selector("input[placeholder='Select Store']")
        if store_input:
            store_input.fill(store_id)
            time.sleep(0.5)
            # Click the matching option
            option = page.query_selector(f"div:has-text('[{store_id}]')")
            if option:
                option.click()
                time.sleep(0.3)
    except Exception as e:
        logger.warning(f"Could not select store {store_id}: {e}")

    # Run Report
    try:
        run_btn = page.query_selector("button:has-text('Run Report')")
        if run_btn:
            run_btn.click()
            page.wait_for_load_state("networkidle")
            time.sleep(2)
    except Exception as e:
        logger.warning(f"Could not run report: {e}")

    # Extract data from the page
    return _parse_report_page(page)


def _parse_report_page(page) -> dict:
    """Parse the Summary By Date report page to extract KPIs."""
    content = page.content()
    
    net_sales = _extract_value(content, "Net Sales")
    labor_pct = _extract_value(content, "Total Labor %")
    avg_check = _extract_value(content, "Check Average (Net)")
    sos = _extract_sos(content)
    trans_count = _extract_int_value(content, "Total Checks Count")

    return {
        "net_sales": net_sales,
        "labor_pct": labor_pct,
        "avg_check": avg_check,
        "sos": sos,
        "trans_count": trans_count,
        "_raw_content": content[:5000],  # Keep first 5000 chars for debugging
    }


def _extract_value(html: str, label: str) -> float | None:
    """Extract a numeric value following a label in the HTML."""
    # Look for the label followed by a number
    patterns = [
        rf'{re.escape(label)}\s*[\s\S]{{0,100}}?(\d{{1,3}}(?:,\d{{3}})*(?:\.\d{{2}})?)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            try:
                return float(match.group(1).replace(",", ""))
            except ValueError:
                pass
    return None


def _extract_int_value(html: str, label: str) -> int | None:
    """Extract an integer value following a label."""
    val = _extract_value(html, label)
    return int(val) if val is not None else None


def _extract_sos(html: str) -> float | None:
    """Extract Speed of Service in minutes."""
    # SOS is typically shown as M:SS format
    pattern = r'(?:Speed of Service|SOS|Avg\s+Service\s+Time)[^0-9]*(\d+):(\d{2})'
    match = re.search(pattern, html, re.IGNORECASE)
    if match:
        minutes = int(match.group(1))
        seconds = int(match.group(2))
        return minutes + seconds / 60.0
    return None


def _extract_retail(data: dict) -> dict:
    """Extract retail (in-store) portion from Overland data."""
    # For Overland, retail = total net sales minus catering orders
    # We'll use the full net_sales as retail for now since catering is tracked separately
    return {
        "net_sales": data.get("net_sales"),
        "labor_pct": data.get("labor_pct"),
        "avg_check": data.get("avg_check"),
        "sos": data.get("sos"),
        "trans_count": data.get("trans_count"),
    }


def _extract_catering(data: dict) -> dict:
    """Extract catering portion from Overland data."""
    # Catering is tracked separately in QU POS via order type/channel
    # This would need a separate report filtered by catering order type
    return _empty_result()


def _fetch_via_requests(report_date: date, username: str, password: str) -> dict:
    """
    Fallback: fetch QU POS data via requests session.
    Attempts to authenticate and call the reporting API directly.
    """
    import requests

    results = {
        "overland_retail": _empty_result(),
        "overland_catering": _empty_result(),
        "state": _empty_result(),
        "eubank": _empty_result(),
        "rapido": _empty_result(),
    }

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Accept": "application/json, text/plain, */*",
    })

    # Attempt login
    try:
        login_resp = session.post(
            "https://admin.qubeyond.com/api/auth/login",
            json={"username": username, "password": password},
            timeout=15,
        )
        if login_resp.status_code != 200:
            logger.error(f"QU POS login failed: {login_resp.status_code}")
            return results
        logger.info("QU POS login successful via requests")
    except Exception as e:
        logger.error(f"QU POS login error: {e}")
        return results

    # Fetch reports for each store
    yesterday = (report_date - __import__('datetime').timedelta(days=1)).isoformat()

    for location_key, store_id in STORE_IDS.items():
        try:
            resp = session.get(
                f"{QU_API_BASE}/reports/summary-by-date",
                params={
                    "storeId": store_id,
                    "date": yesterday,
                    "dateRange": "custom",
                },
                timeout=30,
            )
            if resp.status_code == 200:
                data = resp.json()
                parsed = _parse_api_response(data)
                if location_key == "overland":
                    results["overland_retail"] = parsed
                else:
                    results[location_key] = parsed
        except Exception as e:
            logger.error(f"Error fetching {location_key} via requests: {e}")

    return results


def _parse_api_response(data: dict) -> dict:
    """Parse QU POS API JSON response."""
    sales = data.get("sales", {})
    labor = data.get("labor", {})
    checks = data.get("checks", {})

    return {
        "net_sales": sales.get("netSales") or sales.get("net_sales"),
        "labor_pct": labor.get("totalLaborPct") or labor.get("total_labor_pct"),
        "avg_check": checks.get("checkAverageNet") or checks.get("check_average_net"),
        "sos": None,
        "trans_count": checks.get("totalChecksCount") or checks.get("total_checks_count"),
    }


def _empty_result() -> dict:
    return {
        "net_sales": None,
        "labor_pct": None,
        "avg_check": None,
        "sos": None,
        "trans_count": None,
    }
