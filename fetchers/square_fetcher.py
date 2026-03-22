"""
Square API Fetcher — Food Truck Net Sales
Account: seth.brink@gyroshack.com
Uses Square Orders API to calculate Net Sales (post-discounts/refunds)
"""

import os
import logging
from datetime import datetime, date, timedelta, timezone

logger = logging.getLogger(__name__)

SQUARE_BASE_URL = "https://connect.squareup.com/v2"

# Mountain Standard Time offset (UTC-7 in summer MDT, UTC-7 MST in winter)
# Gyro Shack is in Albuquerque/Boise — use UTC-7 as a safe default
MST_OFFSET = timedelta(hours=-7)


def get_square_headers():
    token = os.environ.get("SQUARE_ACCESS_TOKEN", "")
    if not token:
        raise ValueError("SQUARE_ACCESS_TOKEN environment variable not set")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Square-Version": "2024-01-18",
    }


def get_food_truck_net_sales(report_date: date = None) -> dict:
    """
    Fetch Net Sales for the Food Truck from Square API.
    Returns dict with net_sales, avg_check, trans_count (labor_pct and sos are None).
    """
    try:
        import requests
    except ImportError:
        logger.error("requests library not available")
        return _empty_result()

    if report_date is None:
        report_date = date.today()

    try:
        headers = get_square_headers()
    except ValueError as e:
        logger.warning(f"Square credentials not configured: {e}")
        return _empty_result()

    # ── List all Square locations ────────────────────────────────────────────
    logger.info("Fetching Square locations...")
    try:
        resp = requests.get(f"{SQUARE_BASE_URL}/locations", headers=headers, timeout=15)
        resp.raise_for_status()
        locations = resp.json().get("locations", [])
    except Exception as e:
        logger.error(f"Error fetching Square locations: {e}")
        return _empty_result()

    logger.info(f"Found {len(locations)} Square location(s):")
    for loc in locations:
        logger.info(f"  [{loc.get('id')}] {loc.get('name')} — status: {loc.get('status')}")

    # ── Find Food Truck location ─────────────────────────────────────────────
    location_id = _find_food_truck_location(locations)
    if not location_id:
        logger.warning("Could not identify Food Truck location — trying first active location")
        active = [l for l in locations if l.get("status") == "ACTIVE"]
        if active:
            location_id = active[0]["id"]
            logger.info(f"Falling back to first active location: {active[0].get('name')} [{location_id}]")
        else:
            logger.error("No active Square locations found")
            return _empty_result()

    # ── Build date range in RFC3339 (Mountain Time) ──────────────────────────
    mst = timezone(MST_OFFSET)
    start_dt = datetime(report_date.year, report_date.month, report_date.day,
                        0, 0, 0, tzinfo=mst)
    end_dt = datetime(report_date.year, report_date.month, report_date.day,
                      23, 59, 59, tzinfo=mst)

    logger.info(f"Querying Square orders for {report_date} "
                f"({start_dt.isoformat()} → {end_dt.isoformat()})")

    # ── Fetch all completed orders for the day ───────────────────────────────
    all_orders = []
    cursor = None

    while True:
        payload = {
            "location_ids": [location_id],
            "query": {
                "filter": {
                    "date_time_filter": {
                        "closed_at": {
                            "start_at": start_dt.isoformat(),
                            "end_at": end_dt.isoformat(),
                        }
                    },
                    "state_filter": {"states": ["COMPLETED"]},
                }
            },
            "limit": 500,
        }
        if cursor:
            payload["cursor"] = cursor

        try:
            resp = requests.post(
                f"{SQUARE_BASE_URL}/orders/search",
                headers=headers,
                json=payload,
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            logger.error(f"Square Orders API error: {e}")
            break

        orders = data.get("orders", [])
        all_orders.extend(orders)
        logger.info(f"  Fetched {len(orders)} orders (total so far: {len(all_orders)})")
        cursor = data.get("cursor")
        if not cursor:
            break

    logger.info(f"Total orders fetched: {len(all_orders)}")

    if not all_orders:
        logger.warning(f"No completed orders found for {report_date} at location {location_id}")
        return _empty_result()

    # ── Calculate Net Sales ──────────────────────────────────────────────────
    # Net Sales = Total - Tax - Tip (discounts already reduce total_money)
    net_sales = 0.0
    trans_count = 0

    for order in all_orders:
        total = order.get("total_money", {}).get("amount", 0) or 0
        tax = order.get("total_tax_money", {}).get("amount", 0) or 0
        tip = order.get("total_tip_money", {}).get("amount", 0) or 0

        order_net = (total - tax - tip) / 100.0

        if order_net > 0:
            net_sales += order_net
            trans_count += 1

    avg_check = (net_sales / trans_count) if trans_count > 0 else None

    logger.info(f"Square Food Truck: net_sales=${net_sales:.2f}, "
                f"trans_count={trans_count}, avg_check=${avg_check:.2f if avg_check else 0:.2f}")

    return {
        "net_sales": round(net_sales, 2) if net_sales > 0 else None,
        "labor_pct": None,   # Square doesn't have labor data
        "avg_check": round(avg_check, 2) if avg_check else None,
        "sos": None,          # Square doesn't track SOS
        "trans_count": trans_count if trans_count > 0 else None,
    }


def _find_food_truck_location(locations: list) -> str | None:
    """
    Find the Food Truck location ID from the list of Square locations.
    Searches by name keywords first, then falls back to the only active location.
    """
    truck_keywords = [
        "truck", "food truck", "mobile", "trailer", "gyro truck",
        "gyroshack truck", "gyro shack truck",
    ]

    for loc in locations:
        if loc.get("status") != "ACTIVE":
            continue
        name = loc.get("name", "").lower()
        for kw in truck_keywords:
            if kw in name:
                logger.info(f"Found Food Truck by keyword '{kw}': "
                            f"{loc['name']} [{loc['id']}]")
                return loc["id"]

    # If only one active location, assume it's the food truck
    active = [l for l in locations if l.get("status") == "ACTIVE"]
    if len(active) == 1:
        logger.info(f"Only one active Square location — assuming Food Truck: "
                    f"{active[0]['name']} [{active[0]['id']}]")
        return active[0]["id"]

    return None


def _empty_result() -> dict:
    return {
        "net_sales": None,
        "labor_pct": None,
        "avg_check": None,
        "sos": None,
        "trans_count": None,
    }
