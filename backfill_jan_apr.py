"""
backfill_jan_apr.py
Pulls Jan-Apr 2026 monthly totals from QU Beyond and Square APIs,
then writes them into the AFG Sales Goals Google Sheet.
"""

import sys, os, json, datetime, requests, logging

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

from fetchers.qu_fetcher import (
    AUTH_URL, SALES_URL, EXPORT_URL,
    DEFAULT_LOCATION_IDS, CATERING_KEYWORDS,
    _get_credentials, _get_catering_order_type_id,
    _fetch_checks_for_date_range, _sum_checks_by_order_type,
)
from fetchers.sheets_writer import _get_client, SHEET_ID, MONTH_COL, ROW_DAYS, ROW_ACTUAL, ROW_RAPIDO_CATERING, _write_cell

# ── Auth ───────────────────────────────────────────────────────────────────────
def get_token():
    client_id, client_secret, service_id, company_id = _get_credentials()
    resp = requests.post(AUTH_URL, data={
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
    }, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"], service_id, company_id

def make_headers(token, service_id):
    return {
        "Authorization": f"Bearer {token}",
        "X-Integration": service_id,
        "Content-Type": "application/json",
    }

def fetch_qu_sales_summary(headers, store_id, start_date, end_date):
    """Use the Sales Summary API for a full month total (fast, single call)."""
    body = {"storeId": store_id, "date": {
        "from": start_date.strftime("%m%d%Y"),
        "to":   end_date.strftime("%m%d%Y"),
    }}
    resp = requests.post(SALES_URL, headers=headers, json=body, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # The Sales Summary API returns a flat object at the root level
    # Try root first, then nested under 'data' or 'result'
    candidates = [data]
    nested = data.get("data") or data.get("result")
    if isinstance(nested, dict):
        candidates.append(nested)
        summary = nested.get("summary") or nested.get("sales") or {}
        if isinstance(summary, dict):
            candidates.append(summary)
    for d in candidates:
        if isinstance(d, dict):
            for key in ["netSales", "net_sales", "totalSales", "total_sales"]:
                if key in d:
                    return float(d[key])
    logger.warning(f"Could not parse sales summary for store {store_id}: {json.dumps(data)[:400]}")
    return 0.0

def fetch_square_monthly_gross(start_date, end_date):
    """Fetch gross sales from Square for the Food Truck."""
    token = os.environ.get("SQUARE_ACCESS_TOKEN", "")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Square-Version": "2024-01-17",
    }
    resp = requests.get("https://connect.squareup.com/v2/locations", headers=headers, timeout=15)
    resp.raise_for_status()
    locs = resp.json().get("locations", [])
    # Use the same location selection as square_fetcher: prefer 'food truck' in name,
    # otherwise fall back to the first active location
    loc_id = None
    for loc in locs:
        name = (loc.get("name") or "").lower()
        if "truck" in name or "food" in name:
            loc_id = loc["id"]
            break
    if not loc_id:
        active = [l for l in locs if l.get("status") == "ACTIVE"]
        loc_id = active[0]["id"] if active else (locs[0]["id"] if locs else None)
    logger.info(f"Square location ID for Food Truck: {loc_id}")
    if not loc_id:
        return 0.0

    body = {
        "location_ids": [loc_id],
        "query": {
            "filter": {
                "date_time_filter": {
                    "closed_at": {
                        "start_at": start_date.strftime("%Y-%m-%dT00:00:00Z"),
                        "end_at":   end_date.strftime("%Y-%m-%dT23:59:59Z"),
                    }
                },
                "state_filter": {"states": ["COMPLETED"]},
            }
        },
        "limit": 500,
    }
    gross = 0.0
    cursor = None
    while True:
        if cursor:
            body["cursor"] = cursor
        resp = requests.post(
            "https://connect.squareup.com/v2/orders/search",
            headers=headers, json=body, timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        for order in data.get("orders", []):
            for item in order.get("line_items", []):
                gm = item.get("gross_sales_money", {})
                gross += float(gm.get("amount", 0)) / 100.0
        cursor = data.get("cursor")
        if not cursor:
            break
    return round(gross, 2)

# ── Month ranges ───────────────────────────────────────────────────────────────
MONTHS = [
    (1, datetime.date(2026, 1, 1),  datetime.date(2026, 1, 31),  31),
    (2, datetime.date(2026, 2, 1),  datetime.date(2026, 2, 28),  28),
    (3, datetime.date(2026, 3, 1),  datetime.date(2026, 3, 31),  31),
    (4, datetime.date(2026, 4, 1),  datetime.date(2026, 4, 30),  30),
]

# ── Pull data ──────────────────────────────────────────────────────────────────
token, service_id, company_id = get_token()
headers = make_headers(token, service_id)

loc_ids     = DEFAULT_LOCATION_IDS
overland_id = loc_ids["overland"]
state_id    = loc_ids["state"]
rapido_id   = loc_ids["rapido"]

catering_id = _get_catering_order_type_id(headers, company_id, overland_id)
logger.info(f"Catering order type ID: {catering_id}")

results = {}

for month_num, start, end, days in MONTHS:
    print(f"\n── {start.strftime('%B %Y')} ──────────────────────────────")
    month_data = {"days": days}

    # State Street
    try:
        state_sales = fetch_qu_sales_summary(headers, state_id, start, end)
        month_data["state"] = state_sales
        print(f"  State Street:      ${state_sales:,.2f}")
    except Exception as e:
        print(f"  State ERROR: {e}")
        month_data["state"] = 0.0

    # Rapido
    try:
        rapido_sales = fetch_qu_sales_summary(headers, rapido_id, start, end)
        month_data["rapido"] = rapido_sales
        print(f"  Rapido:            ${rapido_sales:,.2f}")
    except Exception as e:
        print(f"  Rapido ERROR: {e}")
        month_data["rapido"] = 0.0

    # Overland (checks for retail/catering split)
    try:
        print(f"  Fetching Overland checks {start} to {end}...")
        checks = _fetch_checks_for_date_range(headers, company_id, overland_id, start, end)
        retail_t, catering_t = _sum_checks_by_order_type(checks, catering_id)
        retail   = round(retail_t["net_sales"], 2)
        catering = round(catering_t["net_sales"], 2)
        month_data["overland_retail"]   = retail
        month_data["overland_catering"] = catering
        print(f"  Overland retail:   ${retail:,.2f}  ({retail_t['trans_count']} checks)")
        print(f"  Overland catering: ${catering:,.2f}  ({catering_t['trans_count']} checks)")
    except Exception as e:
        print(f"  Overland ERROR: {e}")
        month_data["overland_retail"]   = 0.0
        month_data["overland_catering"] = 0.0

    # Food Truck (Square gross sales)
    try:
        truck = fetch_square_monthly_gross(start, end)
        month_data["food_truck"] = truck
        print(f"  Food Truck:        ${truck:,.2f}")
    except Exception as e:
        print(f"  Food Truck ERROR: {e}")
        month_data["food_truck"] = 0.0

    month_data["overland_combined"] = round(
        month_data["overland_retail"] + month_data["food_truck"], 2
    )
    print(f"  Overland+Truck:    ${month_data['overland_combined']:,.2f}")

    results[month_num] = month_data

# ── Write to Google Sheet ──────────────────────────────────────────────────────
print("\n\n=== Writing to Google Sheet ===")
try:
    client = _get_client()
    sh = client.open_by_key(SHEET_ID)

    def ws(name):
        try:
            return sh.worksheet(name)
        except Exception as e:
            print(f"  Tab '{name}' not found: {e}")
            return None

    for month_num, data in results.items():
        col = MONTH_COL[month_num]
        days = data["days"]
        month_name = datetime.date(2026, month_num, 1).strftime("%B")
        print(f"\n  Writing {month_name}...")

        # Overland (combined)
        w = ws("Overland")
        if w:
            _write_cell(w, ROW_DAYS,   col, days)
            _write_cell(w, ROW_ACTUAL, col, data["overland_combined"])
            print(f"    Overland tab: days={days}, sales=${data['overland_combined']:,.2f}")

        # OV-Truck
        w = ws("OV-Truck")
        if w:
            _write_cell(w, ROW_DAYS,   col, days)
            _write_cell(w, ROW_ACTUAL, col, data["food_truck"])
            print(f"    OV-Truck tab: sales=${data['food_truck']:,.2f}")

        # OV-Catering
        w = ws("OV-Catering")
        if w:
            _write_cell(w, ROW_DAYS,   col, days)
            _write_cell(w, ROW_ACTUAL, col, data["overland_catering"])
            print(f"    OV-Catering tab: sales=${data['overland_catering']:,.2f}")

        # State
        w = ws("State")
        if w:
            _write_cell(w, ROW_DAYS,   col, days)
            _write_cell(w, ROW_ACTUAL, col, data["state"])
            print(f"    State tab: sales=${data['state']:,.2f}")

        # Rapido
        w = ws("Rapido")
        if w:
            _write_cell(w, ROW_DAYS,   col, days)
            _write_cell(w, ROW_ACTUAL, col, data["rapido"])
            print(f"    Rapido tab: sales=${data['rapido']:,.2f}")

    print("\nAll months written successfully.")
except Exception as e:
    print(f"Sheet write ERROR: {e}")
    raise

print("\n=== FINAL SUMMARY ===")
print(json.dumps(results, indent=2))
