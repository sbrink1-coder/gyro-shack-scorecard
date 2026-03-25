"""
Square API Fetcher — Food Truck Net Sales
Account: seth.brink@gyroshack.com
Uses Square Orders API to calculate Net Sales (post-discounts/refunds)
Returns both daily and MTD (month-to-date) figures.
"""

import os
import logging
from datetime import datetime, date, timedelta, timezone

logger = logging.getLogger(__name__)

SQUARE_BASE_URL = "https://connect.squareup.com/v2"

# Mountain Time offset — MDT is UTC-6, MST is UTC-7
# Using UTC-6 (MDT) for spring/summer; adjust to -7 for winter if needed
MST_OFFSET = timedelta(hours=-6)


def get_square_headers():
    token = os.environ.get("SQUARE_ACCESS_TOKEN", "")
    if not token:
        raise ValueError("SQUARE_ACCESS_TOKEN environment variable not set")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Square-Version": "2024-01-18",
    }


def _fetch_orders_for_range(headers: dict, location_id: str,
                             start_date: date, end_date: date) -> list:
    """
    Fetch all completed Square orders for a location between start_date and end_date (inclusive).
    Returns a list of order dicts.
    """
    try:
        import requests
    except ImportError:
        logger.error("requests library not available")
        return []

    mst = timezone(MST_OFFSET)
    start_dt = datetime(start_date.year, start_date.month, start_date.day,
                        0, 0, 0, tzinfo=mst)
    end_dt = datetime(end_date.year, end_date.month, end_date.day,
                      23, 59, 59, tzinfo=mst)

    logger.info(f"Querying Square orders {start_date} → {end_date} "
                f"({start_dt.isoformat()} → {end_dt.isoformat()})")

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

    return all_orders


def _calc_net_sales(orders: list) -> tuple:
    """
    Calculate net_sales and trans_count from a list of Square orders.
    Net Sales = total - tax - tip (discounts already reduce total_money in Square).
    Returns (net_sales, trans_count).
    """
    net_sales = 0.0
    trans_count = 0

    for order in orders:
        total = order.get("total_money", {}).get("amount", 0) or 0
        tax   = order.get("total_tax_money", {}).get("amount", 0) or 0
        tip   = order.get("total_tip_money", {}).get("amount", 0) or 0

        order_net = (total - tax - tip) / 100.0
        if order_net > 0:
            net_sales += order_net
            trans_count += 1

    return round(net_sales, 2), trans_count


def get_food_truck_net_sales(report_date: date = None) -> dict:
    """
    Fetch Net Sales for the Food Truck from Square API.
    Returns dict with:
      net_sales, avg_check, trans_count          — for report_date (daily)
      mtd_net_sales, mtd_avg_check, mtd_trans_count — month-to-date
      labor_pct and sos are always None (Square doesn't track these).
    """
    try:
        import requests
    except ImportError:
        logger.error("requests library not available")
        return _empty_result()

    if report_date is None:
        report_date = date.today() - timedelta(days=1)

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

    # ── Daily: fetch orders for report_date ──────────────────────────────────
    daily_orders = _fetch_orders_for_range(headers, location_id, report_date, report_date)
    logger.info(f"Daily orders fetched: {len(daily_orders)}")

    daily_net_sales, daily_trans_count = _calc_net_sales(daily_orders)
    daily_avg_check = round(daily_net_sales / daily_trans_count, 2) if daily_trans_count > 0 else None

    logger.info(f"Square Food Truck DAILY: net_sales=${daily_net_sales:.2f}, "
                f"trans_count={daily_trans_count}, avg_check={daily_avg_check}")

    # ── MTD: fetch orders from 1st of month through report_date ─────────────
    mtd_start = report_date.replace(day=1)
    logger.info(f"Fetching MTD orders from {mtd_start} to {report_date}...")
    mtd_orders = _fetch_orders_for_range(headers, location_id, mtd_start, report_date)
    logger.info(f"MTD orders fetched: {len(mtd_orders)}")

    mtd_net_sales, mtd_trans_count = _calc_net_sales(mtd_orders)
    mtd_avg_check = round(mtd_net_sales / mtd_trans_count, 2) if mtd_trans_count > 0 else None

    logger.info(f"Square Food Truck MTD: net_sales=${mtd_net_sales:.2f}, "
                f"trans_count={mtd_trans_count}, avg_check={mtd_avg_check}")

    return {
        # Daily
        "net_sales":     round(daily_net_sales, 2) if daily_net_sales > 0 else None,
        "labor_pct":     None,   # Square doesn't have labor data
        "avg_check":     daily_avg_check,
        "sos":           None,   # Square doesn't track SOS
        "trans_count":   daily_trans_count if daily_trans_count > 0 else None,
        # MTD
        "mtd_net_sales":   round(mtd_net_sales, 2) if mtd_net_sales > 0 else None,
        "mtd_labor_pct":   None,
        "mtd_avg_check":   mtd_avg_check,
        "mtd_trans_count": mtd_trans_count if mtd_trans_count > 0 else None,
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
        "net_sales":       None,
        "labor_pct":       None,
        "avg_check":       None,
        "sos":             None,
        "trans_count":     None,
        "mtd_net_sales":   None,
        "mtd_labor_pct":   None,
        "mtd_avg_check":   None,
        "mtd_trans_count": None,
    }
