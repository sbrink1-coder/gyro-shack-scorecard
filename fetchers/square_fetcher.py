"""
Square API Fetcher — Food Truck Net Sales
Account: seth.brink@gyroshack.com
Uses Square Orders API to calculate Net Sales (post-discounts/refunds)
"""

import os
import json
import logging
from datetime import datetime, date, timedelta, timezone

logger = logging.getLogger(__name__)

# Square API base URL
SQUARE_BASE_URL = "https://connect.squareup.com/v2"


def get_square_headers():
    """Return auth headers for Square API."""
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
    
    Returns dict with:
      - net_sales: float
      - labor_pct: None (Square doesn't have labor data)
      - avg_check: float
      - sos: None (Square doesn't track SOS)
      - trans_count: int
    """
    try:
        import requests
    except ImportError:
        logger.error("requests library not available")
        return _empty_result()

    if report_date is None:
        report_date = date.today()

    # Build date range in RFC3339 format (Mountain Time → UTC)
    # Gyro Shack is in Mountain Time (UTC-7 in summer, UTC-6 in winter)
    mst = timezone(timedelta(hours=-7))
    start_dt = datetime(report_date.year, report_date.month, report_date.day, 0, 0, 0, tzinfo=mst)
    end_dt = datetime(report_date.year, report_date.month, report_date.day, 23, 59, 59, tzinfo=mst)

    start_str = start_dt.isoformat()
    end_str = end_dt.isoformat()

    try:
        headers = get_square_headers()
    except ValueError as e:
        logger.warning(f"Square credentials not configured: {e}")
        return _empty_result()

    # First, get the location ID for the Food Truck
    location_id = _get_food_truck_location_id(headers)
    if not location_id:
        logger.warning("Could not find Food Truck location in Square")
        return _empty_result()

    # Search orders for the day
    all_orders = []
    cursor = None

    while True:
        payload = {
            "location_ids": [location_id],
            "query": {
                "filter": {
                    "date_time_filter": {
                        "closed_at": {
                            "start_at": start_str,
                            "end_at": end_str,
                        }
                    },
                    "state_filter": {
                        "states": ["COMPLETED"]
                    }
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
            logger.error(f"Square API error: {e}")
            return _empty_result()

        orders = data.get("orders", [])
        all_orders.extend(orders)
        cursor = data.get("cursor")
        if not cursor:
            break

    # Calculate Net Sales from orders
    # Net Sales = Total Amount - Taxes - Tips - Refunds
    net_sales = 0.0
    trans_count = 0
    total_amount = 0.0

    for order in all_orders:
        # Square amounts are in cents
        order_net = order.get("net_amount_due_money", {}).get("amount", 0) or 0
        # net_amount_due = total - taxes - tips - discounts already applied
        # But we want: total_money - tax_money - tip_money
        total = order.get("total_money", {}).get("amount", 0) or 0
        tax = order.get("total_tax_money", {}).get("amount", 0) or 0
        tip = order.get("total_tip_money", {}).get("amount", 0) or 0
        discount = order.get("total_discount_money", {}).get("amount", 0) or 0
        
        # Net Sales = Gross Sales (after discounts) - Tax - Tip
        # Gross Sales = total - tax - tip
        # Net Sales = total - tax - tip (discounts already reduce total)
        order_net_sales = (total - tax - tip) / 100.0
        
        if order_net_sales > 0:
            net_sales += order_net_sales
            trans_count += 1
            total_amount += total / 100.0

    avg_check = (net_sales / trans_count) if trans_count > 0 else None

    return {
        "net_sales": round(net_sales, 2) if net_sales > 0 else None,
        "labor_pct": None,  # Square doesn't have labor data
        "avg_check": round(avg_check, 2) if avg_check else None,
        "sos": None,  # Square doesn't track SOS
        "trans_count": trans_count if trans_count > 0 else None,
    }


def _get_food_truck_location_id(headers: dict) -> str | None:
    """Find the Food Truck location ID in Square."""
    try:
        import requests
        resp = requests.get(
            f"{SQUARE_BASE_URL}/locations",
            headers=headers,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        locations = data.get("locations", [])
        
        # Look for food truck location (search by name keywords)
        truck_keywords = ["truck", "food truck", "mobile", "trailer"]
        for loc in locations:
            name = loc.get("name", "").lower()
            if any(kw in name for kw in truck_keywords):
                logger.info(f"Found Food Truck location: {loc['name']} [{loc['id']}]")
                return loc["id"]
        
        # If not found by name, log all locations for debugging
        logger.warning("Food Truck location not found. Available locations:")
        for loc in locations:
            logger.warning(f"  - {loc.get('name', 'Unknown')} [{loc.get('id', 'N/A')}]")
        
        # Fall back to first active location if only one exists
        active = [l for l in locations if l.get("status") == "ACTIVE"]
        if len(active) == 1:
            return active[0]["id"]
        
        return None
    except Exception as e:
        logger.error(f"Error fetching Square locations: {e}")
        return None


def _empty_result() -> dict:
    return {
        "net_sales": None,
        "labor_pct": None,
        "avg_check": None,
        "sos": None,
        "trans_count": None,
    }
