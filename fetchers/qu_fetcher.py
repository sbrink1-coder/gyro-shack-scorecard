"""
QU Beyond Data Export API Fetcher
Pulls Net Sales, Labor %, and Avg Check for all QU POS locations.

Confirmed production API details (tested 2026-03-25):
  Auth:  POST https://gateway-api.qubeyond.com/api/v4/authentication/oauth2/access-token
         Body: grant_type=client_credentials, client_id=..., client_secret=...
         Content-Type: application/x-www-form-urlencoded

  Sales: POST https://gateway-api.qubeyond.com/api/v4/data/sales/summary
         Body: {"storeId": <int>, "date": {"from": "MMddyyyy", "to": "MMddyyyy"}}

  Labor: POST https://gateway-api.qubeyond.com/api/v4/data/labor/summary
         Body: {"storeId": <int>, "date": {"from": "MMddyyyy", "to": "MMddyyyy"}}

  Locs:  GET  https://gateway-api.qubeyond.com/api/v4/data/export/locations
         Returns location list with id, name, dba_name fields

Confirmed location IDs for Gyro Shack (Company 379):
  810  → 3001 Boise, ID - Overland Rd.   (Retail + Catering combined)
  811  → 3002 - Boise, ID - State Street
  5645 → 6601 - Albuquerque - Eubank Blvd.
  814  → 7201 - Meridian, ID - Fairview  (Rapido)

Environment variables:
  QU_CLIENT_ID       — OAuth2 client_id
  QU_CLIENT_SECRET   — OAuth2 client_secret
  QU_SERVICE_ID      — X-Integration header value
  QU_COMPANY_ID      — Company ID (379 for Gyro Shack)
  QU_LOCATION_IDS    — Optional JSON override: {"overland":"810","state":"811",...}
"""

import json
import logging
import os
from datetime import date, timedelta

import requests

logger = logging.getLogger(__name__)

# ── API Configuration ─────────────────────────────────────────────────────────
API_BASE  = "https://gateway-api.qubeyond.com"
AUTH_URL  = f"{API_BASE}/api/v4/authentication/oauth2/access-token"
SALES_URL = f"{API_BASE}/api/v4/data/sales/summary"
LABOR_URL = f"{API_BASE}/api/v4/data/labor/summary"
LOCS_URL  = f"{API_BASE}/api/v4/data/export/locations"

# Confirmed production location IDs for Gyro Shack
DEFAULT_LOCATION_IDS = {
    "overland": 810,   # Overland Rd. — Retail + Catering combined
    "state":    811,   # State Street
    "eubank":   5645,  # Albuquerque - Eubank Blvd.
    "rapido":   814,   # Meridian - Fairview (Rapido)
}


def _get_credentials():
    """Return (client_id, client_secret, service_id, company_id)."""
    return (
        os.environ.get("QU_CLIENT_ID", ""),
        os.environ.get("QU_CLIENT_SECRET", ""),
        os.environ.get("QU_SERVICE_ID", ""),
        os.environ.get("QU_COMPANY_ID", "379"),
    )


def _get_token(client_id: str, client_secret: str) -> str:
    """Obtain OAuth2 bearer token from QU Beyond."""
    logger.info(f"Requesting QU Beyond token...")
    resp = requests.post(
        AUTH_URL,
        data={
            "grant_type":    "client_credentials",
            "client_id":     client_id,
            "client_secret": client_secret,
        },
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    if resp.status_code != 200:
        raise ValueError(f"Auth failed {resp.status_code}: {resp.text[:300]}")
    token = resp.json().get("access_token", "")
    if not token:
        raise ValueError(f"No access_token in response: {resp.text[:200]}")
    logger.info("QU Beyond token obtained successfully.")
    return token


def _make_headers(token: str, service_id: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "X-Integration": service_id,
        "Content-Type":  "application/json",
    }


def _date_filter(report_date: date) -> dict:
    """Return the date filter object in MMddyyyy format."""
    d = report_date.strftime("%m%d%Y")
    return {"from": d, "to": d}


def _mtd_filter(report_date: date) -> dict:
    """Return a month-to-date date filter (1st of month through report_date)."""
    first = report_date.replace(day=1)
    return {
        "from": first.strftime("%m%d%Y"),
        "to":   report_date.strftime("%m%d%Y"),
    }


def _fetch_sales(headers: dict, store_id: int, date_filter: dict) -> dict:
    """Fetch sales summary for a single store."""
    resp = requests.post(
        SALES_URL,
        headers=headers,
        json={"storeId": store_id, "date": date_filter},
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error(f"Sales API error for store {store_id}: {resp.status_code} — {resp.text[:300]}")
        return {}
    return resp.json()


def _fetch_labor(headers: dict, store_id: int, date_filter: dict) -> dict:
    """Fetch labor summary for a single store."""
    resp = requests.post(
        LABOR_URL,
        headers=headers,
        json={"storeId": store_id, "date": date_filter},
        timeout=30,
    )
    if resp.status_code != 200:
        logger.warning(f"Labor API error for store {store_id}: {resp.status_code} — {resp.text[:300]}")
        return {}
    return resp.json()


def _empty_result() -> dict:
    return {
        "net_sales":       None,
        "labor_pct":       None,
        "avg_check":       None,
        "sos":             None,
        "trans_count":     None,
        "labor_cost":      None,
        "mtd_net_sales":   None,
        "mtd_labor_pct":   None,
        "mtd_avg_check":   None,
        "mtd_trans_count": None,
    }


def fetch_all_locations(report_date: date = None) -> dict:
    """
    Main entry point. Returns a dict with keys:
      overland_retail, overland_catering, state, eubank, rapido

    Each value is a dict with:
      net_sales, labor_pct, avg_check, sos, trans_count, labor_cost  (daily)
      mtd_net_sales, mtd_labor_pct, mtd_avg_check, mtd_trans_count   (month-to-date)
    """
    if report_date is None:
        report_date = date.today() - timedelta(days=1)

    empty = {k: _empty_result() for k in
             ["overland_retail", "overland_catering", "state", "eubank", "rapido"]}

    client_id, client_secret, service_id, company_id = _get_credentials()

    if not client_id or not client_secret or not service_id:
        logger.warning("QU Beyond API credentials not set — returning empty data.")
        return empty

    try:
        token = _get_token(client_id, client_secret)
    except Exception as e:
        logger.error(f"Failed to get QU Beyond token: {e}")
        return empty

    hdrs = _make_headers(token, service_id)
    df   = _date_filter(report_date)
    mdf  = _mtd_filter(report_date)

    # Get location IDs (from env override or defaults)
    loc_ids_json = os.environ.get("QU_LOCATION_IDS", "")
    if loc_ids_json:
        try:
            raw = json.loads(loc_ids_json)
            location_ids = {k: int(v) for k, v in raw.items()}
            logger.info(f"Using env-configured location IDs: {location_ids}")
        except Exception as e:
            logger.warning(f"Could not parse QU_LOCATION_IDS: {e}. Using defaults.")
            location_ids = DEFAULT_LOCATION_IDS
    else:
        location_ids = DEFAULT_LOCATION_IDS

    results = dict(empty)

    for loc_key, store_id in location_ids.items():
        logger.info(f"Fetching data for {loc_key} (storeId={store_id}) on {report_date}...")
        try:
            # ── Daily data ──
            sales = _fetch_sales(hdrs, store_id, df)
            labor = _fetch_labor(hdrs, store_id, df)

            net_sales   = sales.get("netSales")
            check_count = sales.get("checkCount")
            labor_cost  = labor.get("totalLaborCost")

            avg_check = None
            if net_sales is not None and check_count and check_count > 0:
                avg_check = round(float(net_sales) / int(check_count), 2)

            labor_pct = None
            if labor_cost is not None and net_sales and float(net_sales) > 0:
                labor_pct = round(float(labor_cost) / float(net_sales) * 100, 2)

            # ── MTD data ──
            mtd_sales = _fetch_sales(hdrs, store_id, mdf)
            mtd_labor = _fetch_labor(hdrs, store_id, mdf)

            mtd_net_sales   = mtd_sales.get("netSales")
            mtd_check_count = mtd_sales.get("checkCount")
            mtd_labor_cost  = mtd_labor.get("totalLaborCost")

            mtd_avg_check = None
            if mtd_net_sales is not None and mtd_check_count and mtd_check_count > 0:
                mtd_avg_check = round(float(mtd_net_sales) / int(mtd_check_count), 2)

            mtd_labor_pct = None
            if mtd_labor_cost is not None and mtd_net_sales and float(mtd_net_sales) > 0:
                mtd_labor_pct = round(float(mtd_labor_cost) / float(mtd_net_sales) * 100, 2)

            result = {
                "net_sales":       round(float(net_sales), 2) if net_sales is not None else None,
                "labor_pct":       labor_pct,
                "avg_check":       avg_check,
                "sos":             None,  # SOS not available via API
                "trans_count":     int(check_count) if check_count is not None else None,
                "labor_cost":      round(float(labor_cost), 2) if labor_cost is not None else None,
                "mtd_net_sales":   round(float(mtd_net_sales), 2) if mtd_net_sales is not None else None,
                "mtd_labor_pct":   mtd_labor_pct,
                "mtd_avg_check":   mtd_avg_check,
                "mtd_trans_count": int(mtd_check_count) if mtd_check_count is not None else None,
            }

            logger.info(
                f"  {loc_key}: daily net_sales={result['net_sales']}, "
                f"mtd_net_sales={result['mtd_net_sales']}, "
                f"labor_pct={result['labor_pct']}%, "
                f"avg_check=${result['avg_check']}"
            )

            # Map to the correct dashboard keys
            if loc_key == "overland":
                results["overland_retail"] = result
                # Catering is combined in the same store — not separately available
                results["overland_catering"] = _empty_result()
            elif loc_key in results:
                results[loc_key] = result

        except Exception as e:
            logger.error(f"Error fetching {loc_key} (storeId={store_id}): {e}", exc_info=True)

    return results
