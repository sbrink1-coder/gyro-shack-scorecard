"""
QU POS Fetcher — Net Sales for Overland (Retail + Catering), State, Eubank, Rapido
Uses the QU Beyond Data Export API (REST/JSON, no browser required).

Authentication:
  POST {AUTH_URL}/oauth2/token
  form: grant_type=client_credentials, client_id=..., client_secret=...
  Response: { access_token, token_type, expires_in }
  All requests: Authorization: Bearer <token>, X-Integration: <service_id>

Key endpoints:
  GET  {API_URL}/api/v4/data/export/locations          → discover location IDs
  POST {API_URL}/api/v4/data/export/checks             → raw check data for Net Sales
  POST {API_URL}/api/v4/data/export/employees/labor    → labor cost data

Net Sales formula (per QU docs):
  Net Sales = Item Sales - Discounts
  Item Sales = sum of all check items' "amount"
  Discounts  = sum of all check discounts' "amount"

Avg Check = Net Sales / Check Count
Labor %   = Total Labor Cost / Net Sales * 100

Environment variables (production):
  QU_CLIENT_ID       — OAuth2 client_id
  QU_CLIENT_SECRET   — OAuth2 client_secret
  QU_SERVICE_ID      — X-Integration header value
  QU_AUTH_URL        — Auth base URL (default: https://auth.qubeyond.com)
  QU_API_URL         — API base URL (default: https://gateway-api.qubeyond.com)
  QU_COMPANY_ID      — Gyro Shack company ID
  QU_LOCATION_IDS    — JSON map: {"overland":"<id>","state":"<id>","eubank":"<id>","rapido":"<id>"}

Staging environment (for testing before production credentials arrive):
  AUTH_URL: https://auth-stg.qubeyond.com/
  API_URL:  https://gateway.stg.qubeyond.com/
  client_id: INTGGateway420
  client_secret: QcO2y]1RkA){F7rJ&gLb
  X-Integration: 65804c197902231115103e70
  Company ID: 420, Location ID: 4870
"""

import os
import json
import logging
import requests
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Default URLs ─────────────────────────────────────────────────────────────
DEFAULT_AUTH_URL = "https://auth.qubeyond.com"
DEFAULT_API_URL  = "https://gateway-api.qubeyond.com"

# Staging URLs (used when QU_USE_STAGING=true or no production creds set)
STAGING_AUTH_URL = "https://auth-stg.qubeyond.com"
STAGING_API_URL  = "https://gateway.stg.qubeyond.com"
STAGING_CLIENT_ID     = "INTGGateway420"
STAGING_CLIENT_SECRET = "QcO2y]1RkA){F7rJ&gLb"
STAGING_SERVICE_ID    = "65804c197902231115103e70"
STAGING_COMPANY_ID    = 420
STAGING_LOCATION_ID   = 4870  # single test location in staging


def _get_config():
    """Return (auth_url, api_url, client_id, client_secret, service_id, company_id, use_staging)."""
    client_id     = os.environ.get("QU_CLIENT_ID", "")
    client_secret = os.environ.get("QU_CLIENT_SECRET", "")
    service_id    = os.environ.get("QU_SERVICE_ID", "")
    use_staging   = os.environ.get("QU_USE_STAGING", "").lower() in ("1", "true", "yes")

    if not client_id or not client_secret or use_staging:
        logger.info("Using QU Beyond STAGING credentials")
        return (
            STAGING_AUTH_URL,
            STAGING_API_URL,
            STAGING_CLIENT_ID,
            STAGING_CLIENT_SECRET,
            STAGING_SERVICE_ID,
            STAGING_COMPANY_ID,
            True,  # is_staging
        )

    auth_url   = os.environ.get("QU_AUTH_URL", DEFAULT_AUTH_URL).rstrip("/")
    api_url    = os.environ.get("QU_API_URL",  DEFAULT_API_URL).rstrip("/")
    company_id = int(os.environ.get("QU_COMPANY_ID", "0"))
    logger.info("Using QU Beyond PRODUCTION credentials")
    return (auth_url, api_url, client_id, client_secret, service_id, company_id, False)


def _get_token(auth_url: str, client_id: str, client_secret: str) -> str:
    """Obtain OAuth2 bearer token."""
    url = f"{auth_url}/oauth2/token"
    logger.info(f"Requesting token from {url}")
    resp = requests.post(
        url,
        data={
            "grant_type":    "client_credentials",
            "client_id":     client_id,
            "client_secret": client_secret,
        },
        timeout=30,
    )
    resp.raise_for_status()
    token = resp.json().get("access_token", "")
    if not token:
        raise ValueError(f"No access_token in response: {resp.text[:200]}")
    logger.info("Token obtained successfully")
    return token


def _headers(token: str, service_id: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Integration": service_id,
        "Content-Type":  "application/json",
    }


def _date_str(d: date) -> str:
    """Format date as MMDDYYYY for QU API."""
    return d.strftime("%m%d%Y")


def _fetch_checks(api_url: str, headers: dict, company_id: int, location_id: int,
                  report_date: date) -> list:
    """Fetch raw check data for a location on a given date."""
    url = f"{api_url}/api/v4/data/export/checks"
    payload = {
        "companyId":  company_id,
        "locationId": location_id,
        "date": {
            "from": _date_str(report_date),
            "to":   _date_str(report_date),
        },
    }
    logger.info(f"  Fetching checks: location={location_id}, date={report_date}")
    resp = requests.post(url, headers=headers, json=payload, timeout=60)
    resp.raise_for_status()
    data = resp.json()
    # Response may be a list directly or wrapped in a "data" key
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("data", data.get("checks", []))
    return []


def _fetch_labor(api_url: str, headers: dict, company_id: int, location_id: int,
                 report_date: date) -> dict:
    """Fetch labor summary for a location on a given date."""
    url = f"{api_url}/api/v4/data/labor/summary"
    payload = {
        "companyId":      company_id,
        "storeId":        location_id,
        "clockInRequired": True,
        "date": {
            "from": _date_str(report_date),
            "to":   _date_str(report_date),
        },
    }
    logger.info(f"  Fetching labor: location={location_id}, date={report_date}")
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json() if isinstance(resp.json(), dict) else {}
    except Exception as e:
        logger.warning(f"  Labor fetch failed: {e}")
        return {}


def _fetch_sales_summary(api_url: str, headers: dict, company_id: int, location_id: int,
                          report_date: date) -> dict:
    """Fetch sales summary for a location on a given date (Summary API)."""
    url = f"{api_url}/api/v4/data/sales/summary"
    payload = {
        "companyId": company_id,
        "storeId":   location_id,
        "date": {
            "from": _date_str(report_date),
            "to":   _date_str(report_date),
        },
    }
    logger.info(f"  Fetching sales summary: location={location_id}, date={report_date}")
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json() if isinstance(resp.json(), dict) else {}
    except Exception as e:
        logger.warning(f"  Sales summary fetch failed: {e}")
        return {}


def _calc_from_checks(checks: list) -> dict:
    """
    Calculate Net Sales, Avg Check, and Trans Count from raw check data.

    Net Sales = Item Sales - Discounts
    Item Sales = sum of all items' "amount" across all checks
    Discounts  = sum of all discount "amount" across all checks
    """
    item_sales  = 0.0
    discounts   = 0.0
    check_count = 0

    for check in checks:
        # Skip voided checks
        if check.get("isVoid") or check.get("void"):
            continue
        check_count += 1

        # Sum item amounts
        for item in check.get("items", []):
            amt = item.get("amount", 0) or 0
            item_sales += float(amt)

        # Sum discount amounts
        for disc in check.get("discounts", []):
            amt = disc.get("amount", 0) or 0
            discounts += float(amt)

    net_sales  = item_sales - discounts
    avg_check  = (net_sales / check_count) if check_count > 0 else None

    return {
        "net_sales":   round(net_sales, 2)  if net_sales  else None,
        "avg_check":   round(avg_check, 2)  if avg_check  else None,
        "trans_count": check_count          if check_count else None,
        "item_sales":  round(item_sales, 2),
        "discounts":   round(discounts, 2),
    }


def _calc_from_summary(summary: dict) -> dict:
    """Extract metrics from the Sales Summary API response."""
    net_sales   = summary.get("netSales")
    check_count = summary.get("checkCount")
    avg_check   = summary.get("checksGrossSalesAverage")  # or calculate

    if net_sales is not None and check_count and not avg_check:
        avg_check = net_sales / check_count

    return {
        "net_sales":   round(float(net_sales), 2)  if net_sales   is not None else None,
        "avg_check":   round(float(avg_check), 2)  if avg_check   is not None else None,
        "trans_count": int(check_count)             if check_count is not None else None,
    }


def _get_location_ids(api_url: str, headers: dict) -> list:
    """Fetch all available locations to discover IDs."""
    url = f"{api_url}/api/v4/data/export/locations"
    logger.info(f"Fetching location list from {url}")
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return data
        # May be wrapped
        for key in ("data", "locations", "location"):
            if key in data:
                inner = data[key]
                if isinstance(inner, dict) and "location" in inner:
                    return inner["location"]
                return inner
        return []
    except Exception as e:
        logger.warning(f"Location list fetch failed: {e}")
        return []


def _empty_result() -> dict:
    return {
        "net_sales":   None,
        "labor_pct":   None,
        "avg_check":   None,
        "sos":         None,
        "trans_count": None,
    }


def fetch_all_locations(report_date: date = None) -> dict:
    """
    Main entry point. Returns a dict with keys:
      overland_retail, overland_catering, state, eubank, rapido
    Each value is a dict with: net_sales, labor_pct, avg_check, sos, trans_count
    """
    if report_date is None:
        report_date = date.today() - timedelta(days=1)

    empty = {k: _empty_result() for k in
             ["overland_retail", "overland_catering", "state", "eubank", "rapido"]}

    try:
        auth_url, api_url, client_id, client_secret, service_id, company_id, is_staging = _get_config()
        token   = _get_token(auth_url, client_id, client_secret)
        hdrs    = _headers(token, service_id)
    except Exception as e:
        logger.error(f"QU API auth failed: {e}")
        return empty

    # ── Discover location IDs ─────────────────────────────────────────────────
    location_map = _build_location_map(api_url, hdrs, company_id, is_staging)
    logger.info(f"Location map: {location_map}")

    results = dict(empty)

    # ── Fetch data for each location ──────────────────────────────────────────
    for key, loc_id in location_map.items():
        if loc_id is None:
            logger.warning(f"No location ID for {key}, skipping")
            continue
        try:
            sales, labor_cost = _fetch_location_data(
                api_url, hdrs, company_id, loc_id, report_date
            )
            labor_pct = None
            if labor_cost is not None and sales.get("net_sales"):
                labor_pct = round(labor_cost / sales["net_sales"] * 100, 2)

            results[key] = {
                "net_sales":   sales.get("net_sales"),
                "labor_pct":   labor_pct,
                "avg_check":   sales.get("avg_check"),
                "sos":         None,
                "trans_count": sales.get("trans_count"),
            }
            logger.info(
                f"  {key}: net_sales={results[key]['net_sales']}, "
                f"labor_pct={results[key]['labor_pct']}, "
                f"avg_check={results[key]['avg_check']}"
            )
        except Exception as e:
            logger.error(f"Failed to fetch {key} (loc_id={loc_id}): {e}", exc_info=True)

    return results


def _fetch_location_data(api_url, hdrs, company_id, loc_id, report_date):
    """Try Summary API first, fall back to raw check data. Returns (sales_dict, labor_cost)."""
    # Try Summary API (faster, pre-calculated)
    summary = _fetch_sales_summary(api_url, hdrs, company_id, loc_id, report_date)
    if summary.get("netSales") is not None:
        sales = _calc_from_summary(summary)
        logger.info(f"  Used Summary API for location {loc_id}")
    else:
        # Fall back to raw check data
        logger.info(f"  Summary API returned no data, falling back to check data")
        checks = _fetch_checks(api_url, hdrs, company_id, loc_id, report_date)
        logger.info(f"  Got {len(checks)} checks")
        sales = _calc_from_checks(checks)

    # Fetch labor
    labor_data = _fetch_labor(api_url, hdrs, company_id, loc_id, report_date)
    labor_cost = labor_data.get("totalLaborCost")

    return sales, labor_cost


def _build_location_map(api_url: str, hdrs: dict, company_id: int, is_staging: bool) -> dict:
    """
    Build a map of {result_key: location_id} for all Gyro Shack locations.

    Production: reads QU_LOCATION_IDS env var (JSON) or auto-discovers from locations endpoint.
    Staging: uses the single test location for all keys.
    """
    if is_staging:
        # In staging, only one test location exists — map all keys to it
        return {
            "overland_retail":   STAGING_LOCATION_ID,
            "overland_catering": STAGING_LOCATION_ID,
            "state":             STAGING_LOCATION_ID,
            "eubank":            STAGING_LOCATION_ID,
            "rapido":            STAGING_LOCATION_ID,
        }

    # Check for manually configured location IDs
    loc_ids_json = os.environ.get("QU_LOCATION_IDS", "")
    if loc_ids_json:
        try:
            manual = json.loads(loc_ids_json)
            logger.info(f"Using manually configured location IDs: {manual}")
            return {
                "overland_retail":   int(manual.get("overland", 0)) or None,
                "overland_catering": int(manual.get("overland_catering",
                                         manual.get("overland", 0))) or None,
                "state":             int(manual.get("state", 0)) or None,
                "eubank":            int(manual.get("eubank", 0)) or None,
                "rapido":            int(manual.get("rapido", 0)) or None,
            }
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(f"QU_LOCATION_IDS parse error: {e}")

    # Auto-discover from locations endpoint
    locations = _get_location_ids(api_url, hdrs)
    logger.info(f"Discovered {len(locations)} locations")
    for loc in locations:
        logger.info(f"  Location: id={loc.get('id')}, name={loc.get('name')}, "
                    f"store_number={loc.get('store_number')}")

    # Match by store number or name keywords
    STORE_KEYWORDS = {
        "overland_retail":   ["overland", "3001"],
        "overland_catering": ["overland", "3001"],  # same location, split by order type
        "state":             ["state", "3002"],
        "eubank":            ["eubank", "6601"],
        "rapido":            ["fairview", "7201", "rapido"],
    }

    loc_map = {k: None for k in STORE_KEYWORDS}
    for loc in locations:
        name   = (loc.get("name", "") or "").lower()
        number = str(loc.get("store_number", "") or "")
        loc_id = loc.get("id")
        for key, keywords in STORE_KEYWORDS.items():
            if loc_map[key] is None:
                if any(kw in name or kw == number for kw in keywords):
                    loc_map[key] = loc_id
                    logger.info(f"  Matched {key} → location id={loc_id} ({loc.get('name')})")

    return loc_map
