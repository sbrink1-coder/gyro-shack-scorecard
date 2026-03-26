"""
Daily Data Collection Script
Runs via GitHub Actions at 4:00 AM MST
Fetches data from Square (Food Truck) and QU POS (all other locations)
Writes results to data/scorecard_data.json
"""

import json
import logging
import os
import sys
from datetime import date, datetime, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.dirname(__file__))

from fetchers.square_fetcher import get_food_truck_net_sales
from fetchers.qu_fetcher import fetch_all_locations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


# ── Monthly Daily Targets (from 2026 AFG Sales Goals sheet, row 9 per tab) ────
# Format: [Jan, Feb, Mar, Apr, May, Jun, Jul, Aug, Sep, Oct, Nov, Dec]
# Source tabs: OV-Store Only (row 9), OV-Catering (row 9), OV-Truck (row 9),
#              Eubank (row 9), State (row 9), Rapido (row 9)
MONTHLY_DAILY_TARGETS = {
    "overland_retail":   [1550, 1587, 1969, 2118, 2179, 2140, 2184, 2107, 2258, 2280, 1990, 2265],
    "overland_catering": [ 453,  671,  432,  881,  497,  454,  378,  606,  599,  600,  334,  143],
    "food_truck":        [ 291,  536, 1265,  520,  888,  902,  946, 1003,  476,  333,  621,  719],
    "eubank":            [1853, 1758, 2514, 2829, 2382, 2188, 2382, 2382, 2188, 2382, 2263, 2188],
    "state":             [1279, 1289, 1496, 1732, 1770, 1744, 1823, 1587, 1583, 1525, 1335, 1421],
    "rapido":            [1832, 1689, 1901, 1851, 1734, 1536, 1417, 1640, 1847, 1941, 1830, 1611],
}

LOCATION_NAMES = {
    "overland_retail": "Overland — Retail",
    "overland_catering": "Overland — Catering",
    "food_truck": "Overland — Food Truck",
    "state": "State Street",
    "eubank": "Eubank",
    "rapido": "Rapido (San Mateo)",
}


def get_daily_target(location_key: str, report_date: date) -> float:
    """Get the daily target for a location based on the month."""
    targets = MONTHLY_DAILY_TARGETS.get(location_key, [])
    if not targets:
        return 0.0
    month_idx = report_date.month - 1
    return float(targets[month_idx])


def collect_and_save(report_date: date = None) -> dict:
    """
    Main collection function.
    Fetches data from all sources and saves to JSON.
    """
    if report_date is None:
        # Use yesterday's date since 4 AM run collects prior day's data
        report_date = date.today() - timedelta(days=1)

    logger.info(f"Collecting data for {report_date}")

    # ── Fetch QU POS data (Overland, State, Eubank, Rapido) ──
    logger.info("Fetching QU POS data...")
    qu_data = fetch_all_locations(report_date)
    logger.info(f"QU POS data fetched: {list(qu_data.keys())}")

    # ── Fetch Square data (Food Truck) ──
    logger.info("Fetching Square data (Food Truck)...")
    square_data = get_food_truck_net_sales(report_date)
    logger.info(f"Square data: net_sales={square_data.get('net_sales')}")

    # ── Build scorecard payload ──
    locations = {}

    for loc_key in ["overland_retail", "overland_catering", "state", "eubank", "rapido"]:
        loc_data = qu_data.get(loc_key, {})
        daily_target = get_daily_target(loc_key, report_date)
        # MTD target = daily target * number of days elapsed so far this month
        days_elapsed = report_date.day
        mtd_target = round(daily_target * days_elapsed, 2)
        locations[loc_key] = {
            "name": LOCATION_NAMES[loc_key],
            "net_sales": loc_data.get("net_sales"),
            "target": daily_target,
            "labor_pct": loc_data.get("labor_pct"),
            "avg_check": loc_data.get("avg_check"),
            "sos": loc_data.get("sos"),
            "trans_count": loc_data.get("trans_count"),
            "mtd_net_sales": loc_data.get("mtd_net_sales"),
            "mtd_target": mtd_target,
            "mtd_labor_pct": loc_data.get("mtd_labor_pct"),
            "mtd_avg_check": loc_data.get("mtd_avg_check"),
            "mtd_trans_count": loc_data.get("mtd_trans_count"),
        }

    # Food Truck from Square
    ft_daily_target = get_daily_target("food_truck", report_date)
    ft_mtd_target = round(ft_daily_target * report_date.day, 2)
    locations["food_truck"] = {
        "name": LOCATION_NAMES["food_truck"],
        "net_sales": square_data.get("net_sales"),
        "target": ft_daily_target,
        "labor_pct": square_data.get("labor_pct"),
        "avg_check": square_data.get("avg_check"),
        "sos": square_data.get("sos"),
        "trans_count": square_data.get("trans_count"),
        "mtd_net_sales": square_data.get("mtd_net_sales"),
        "mtd_target": ft_mtd_target,
        "mtd_labor_pct": square_data.get("mtd_labor_pct"),
        "mtd_avg_check": square_data.get("mtd_avg_check"),
        "mtd_trans_count": square_data.get("mtd_trans_count"),
    }

    scorecard = {
        "last_updated": datetime.utcnow().isoformat() + "Z",
        "report_date": report_date.isoformat(),
        "data_source": "live",
        "locations": locations,
    }

    # ── Save to JSON ──
    data_dir = os.path.join(os.path.dirname(__file__), "data")
    os.makedirs(data_dir, exist_ok=True)
    output_path = os.path.join(data_dir, "scorecard_data.json")

    with open(output_path, "w") as f:
        json.dump(scorecard, f, indent=2)

    logger.info(f"Scorecard data saved to {output_path}")

    # Print summary
    logger.info("=" * 60)
    logger.info(f"SCORECARD SUMMARY — {report_date}")
    logger.info("=" * 60)
    for loc_key, loc_data in locations.items():
        ns = loc_data.get("net_sales")
        target = loc_data.get("target")
        pct = (ns / target * 100) if ns and target else None
        pct_str = f"{pct:.1f}%" if pct else "N/A"
        logger.info(
            f"{loc_data['name']:30s} | "
            f"Net Sales: ${ns:>8,.2f} | "
            f"Target: ${target:>8,.2f} | "
            f"Pct: {pct_str:>7}"
            if ns else
            f"{loc_data['name']:30s} | No data"
        )

    return scorecard


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Collect Gyro Shack scorecard data")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Report date in YYYY-MM-DD format (default: yesterday)",
    )
    args = parser.parse_args()

    if args.date:
        report_date = date.fromisoformat(args.date)
    else:
        report_date = None

    result = collect_and_save(report_date)
    print(json.dumps(result, indent=2))
