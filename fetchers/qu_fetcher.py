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

  Order Type Config (per QU support, case 00153802):
    GET /api/v4/data/export/{customerid}/{locationid}?data_type=config&sub_data_type=order_type
    Returns: { "data": { "order_type": [ { "id": <int>, "name": "..." }, ... ] } }

  Checks Export (for order-type-level split):
    GET /api/v4/data/export/{customerid}/{locationid}?data_type=checks&date=MMddyyyy
    Returns: { "data": { "checks": [ { "orderTypeId": <int>, "netSales": <float>, ... } ] } }

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
API_BASE   = "https://gateway-api.qubeyond.com"
AUTH_URL   = f"{API_BASE}/api/v4/authentication/oauth2/access-token"
SALES_URL  = f"{API_BASE}/api/v4/data/sales/summary"
LABOR_URL  = f"{API_BASE}/api/v4/data/labor/summary"
LOCS_URL   = f"{API_BASE}/api/v4/data/export/locations"
EXPORT_URL = f"{API_BASE}/api/v4/data/export"   # /{customerid}/{locationid}?...

# Confirmed production location IDs for Gyro Shack
DEFAULT_LOCATION_IDS = {
    "overland": 810,   # Overland Rd. — Retail + Catering combined
    "state":    811,   # State Street
    "eubank":   5645,  # Albuquerque - Eubank Blvd.
    "rapido":   814,   # Meridian - Fairview (Rapido)
}

# Keyword used to identify the Catering order type by name
CATERING_KEYWORDS = ["catering", "cater"]


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
    logger.info("Requesting QU Beyond token...")
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


def _get_catering_order_type_id(headers: dict, company_id: str, location_id: int) -> int | None:
    """
    Call the QU order type config endpoint to find the ID for 'Catering'.
    Returns the integer ID, or None if not found.
    """
    url = f"{EXPORT_URL}/{company_id}/{location_id}"
    params = {"data_type": "config", "sub_data_type": "order_type"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        if resp.status_code != 200:
            logger.warning(f"Order type config error {resp.status_code}: {resp.text[:300]}")
            return None
        data = resp.json()
        order_types = data.get("data", {}).get("order_type", [])
        logger.info(f"Order types for location {location_id}: {order_types}")
        for ot in order_types:
            name = ot.get("name", "").lower()
            for kw in CATERING_KEYWORDS:
                if kw in name:
                    logger.info(f"Found Catering order type: id={ot['id']}, name='{ot['name']}'")
                    return int(ot["id"])
        logger.warning(f"No catering order type found among: {[o.get('name') for o in order_types]}")
        return None
    except Exception as e:
        logger.error(f"Error fetching order type config: {e}")
        return None


def _fetch_checks_for_date_range(
    headers: dict, company_id: str, location_id: int,
    start_date: date, end_date: date
) -> list:
    """
    Fetch all check records for a location over a date range using the
    QU Data Export checks endpoint.

    The endpoint accepts a single date per call, so we iterate day by day
    and aggregate results.
    Returns a flat list of check dicts.
    """
    all_checks = []
    current = start_date
    while current <= end_date:
        date_str = current.strftime("%m%d%Y")
        url = f"{EXPORT_URL}/{company_id}/{location_id}"
        params = {"data_type": "checks", "start_date": date_str, "end_date": date_str}
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            if resp.status_code == 200:
                # API returns 'check' (singular) as the key, not 'checks'
                checks = resp.json().get("data", {}).get("check", [])
                all_checks.extend(checks)
                logger.debug(f"  {current}: {len(checks)} checks fetched")
            else:
                logger.warning(
                    f"Checks export error for {current} (loc {location_id}): "
                    f"{resp.status_code} — {resp.text[:200]}"
                )
        except Exception as e:
            logger.error(f"Error fetching checks for {current}: {e}")
        current += timedelta(days=1)
    return all_checks


def _sum_checks_by_order_type(
    checks: list, catering_id: int | None
) -> tuple[dict, dict]:
    """
    Split a list of checks into retail and catering buckets.
    Returns (retail_totals, catering_totals) where each is:
      { "net_sales": float, "trans_count": int }
    """
    retail   = {"net_sales": 0.0, "trans_count": 0}
    catering = {"net_sales": 0.0, "trans_count": 0}

    for check in checks:
        # QU checks export uses 'total' for the check total (not 'netSales')
        ns = check.get("total") or check.get("netSales") or check.get("net_sales") or 0
        try:
            ns = float(ns)
        except (TypeError, ValueError):
            ns = 0.0

        # QU checks export uses 'order_type_id' (snake_case)
        ot_id = check.get("order_type_id") or check.get("orderTypeId")
        try:
            ot_id = int(ot_id) if ot_id is not None else None
        except (TypeError, ValueError):
            ot_id = None

        if catering_id is not None and ot_id == catering_id:
            catering["net_sales"]   += ns
            catering["trans_count"] += 1
        else:
            retail["net_sales"]   += ns
            retail["trans_count"] += 1

    retail["net_sales"]   = round(retail["net_sales"], 2)
    catering["net_sales"] = round(catering["net_sales"], 2)
    return retail, catering


def _build_result(net_sales, check_count, labor_cost,
                  mtd_net_sales, mtd_check_count, mtd_labor_cost) -> dict:
    """Assemble a standard location result dict."""
    avg_check = None
    if net_sales is not None and check_count and check_count > 0:
        avg_check = round(float(net_sales) / int(check_count), 2)

    labor_pct = None
    if labor_cost is not None and net_sales and float(net_sales) > 0:
        labor_pct = round(float(labor_cost) / float(net_sales) * 100, 2)

    mtd_avg_check = None
    if mtd_net_sales is not None and mtd_check_count and mtd_check_count > 0:
        mtd_avg_check = round(float(mtd_net_sales) / int(mtd_check_count), 2)

    mtd_labor_pct = None
    if mtd_labor_cost is not None and mtd_net_sales and float(mtd_net_sales) > 0:
        mtd_labor_pct = round(float(mtd_labor_cost) / float(mtd_net_sales) * 100, 2)

    return {
        "net_sales":       round(float(net_sales), 2) if net_sales is not None else None,
        "labor_pct":       labor_pct,
        "avg_check":       avg_check,
        "sos":             None,
        "trans_count":     int(check_count) if check_count is not None else None,
        "labor_cost":      round(float(labor_cost), 2) if labor_cost is not None else None,
        "mtd_net_sales":   round(float(mtd_net_sales), 2) if mtd_net_sales is not None else None,
        "mtd_labor_pct":   mtd_labor_pct,
        "mtd_avg_check":   mtd_avg_check,
        "mtd_trans_count": int(mtd_check_count) if mtd_check_count is not None else None,
    }


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

    For Overland, uses the checks export + order type config to split
    Retail vs Catering. All other locations use the Sales Summary API.

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
            if loc_key == "overland":
                # ── Overland: split Retail vs Catering via checks export ──────
                catering_type_id = _get_catering_order_type_id(
                    hdrs, company_id, store_id
                )
                logger.info(f"Overland catering orderTypeId: {catering_type_id}")

                # Daily checks
                daily_checks = _fetch_checks_for_date_range(
                    hdrs, company_id, store_id, report_date, report_date
                )
                logger.info(f"Overland daily checks fetched: {len(daily_checks)}")
                daily_retail, daily_catering = _sum_checks_by_order_type(
                    daily_checks, catering_type_id
                )

                # MTD checks
                mtd_start = report_date.replace(day=1)
                mtd_checks = _fetch_checks_for_date_range(
                    hdrs, company_id, store_id, mtd_start, report_date
                )
                logger.info(f"Overland MTD checks fetched: {len(mtd_checks)}")
                mtd_retail, mtd_catering = _sum_checks_by_order_type(
                    mtd_checks, catering_type_id
                )

                # Labor comes from the summary API (applies to the whole store)
                labor      = _fetch_labor(hdrs, store_id, df)
                mtd_labor  = _fetch_labor(hdrs, store_id, mdf)
                labor_cost     = labor.get("totalLaborCost")
                mtd_labor_cost = mtd_labor.get("totalLaborCost")

                results["overland_retail"] = _build_result(
                    daily_retail["net_sales"],   daily_retail["trans_count"],   labor_cost,
                    mtd_retail["net_sales"],     mtd_retail["trans_count"],     mtd_labor_cost,
                )
                results["overland_catering"] = _build_result(
                    daily_catering["net_sales"], daily_catering["trans_count"], None,
                    mtd_catering["net_sales"],   mtd_catering["trans_count"],   None,
                )

                logger.info(
                    f"  overland_retail:   daily=${daily_retail['net_sales']:.2f}  "
                    f"mtd=${mtd_retail['net_sales']:.2f}"
                )
                logger.info(
                    f"  overland_catering: daily=${daily_catering['net_sales']:.2f}  "
                    f"mtd=${mtd_catering['net_sales']:.2f}"
                )

            else:
                # ── All other locations: use Sales Summary API ────────────────
                sales = _fetch_sales(hdrs, store_id, df)
                labor = _fetch_labor(hdrs, store_id, df)

                net_sales   = sales.get("netSales")
                check_count = sales.get("checkCount")
                labor_cost  = labor.get("totalLaborCost")

                mtd_sales = _fetch_sales(hdrs, store_id, mdf)
                mtd_labor = _fetch_labor(hdrs, store_id, mdf)

                mtd_net_sales   = mtd_sales.get("netSales")
                mtd_check_count = mtd_sales.get("checkCount")
                mtd_labor_cost  = mtd_labor.get("totalLaborCost")

                result = _build_result(
                    net_sales, check_count, labor_cost,
                    mtd_net_sales, mtd_check_count, mtd_labor_cost,
                )

                logger.info(
                    f"  {loc_key}: daily net_sales={result['net_sales']}, "
                    f"mtd_net_sales={result['mtd_net_sales']}, "
                    f"labor_pct={result['labor_pct']}%, "
                    f"avg_check=${result['avg_check']}"
                )

                if loc_key in results:
                    results[loc_key] = result

        except Exception as e:
            logger.error(f"Error fetching {loc_key} (storeId={store_id}): {e}", exc_info=True)

    return results
