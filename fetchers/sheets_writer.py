"""
sheets_writer.py
Writes actual MTD sales and days-completed back to the AFG Sales Goals Google Sheet
each morning after POS data is collected.

Tab mapping (row 13 = days complete, row 14 = actual sales):
  Overland      -> combined Overland Retail + Food Truck  (row 14 label: "Overland + Truck")
  OV-Store Only -> Overland Retail only                   (row 14 label: "Overland (store only)")
  OV-Truck      -> Food Truck only                        (row 14 label: "Truck Only")
  OV-Catering   -> Overland Catering                      (row 14 label: "OV Catering")
  State         -> State Street                           (row 14 label: "State St")
  Rapido        -> Rapido in-store                        (row 14 label: "Rapido In-store")
                   Rapido catering written to row 15      (row 15 label: "Catering")

Month columns (B=Jan, C=Feb, D=Mar, E=Apr, F=May, G=Jun,
               H=Jul, I=Aug, J=Sep, K=Oct, L=Nov, M=Dec)
"""

import json
import os
import datetime
import gspread
from google.oauth2.service_account import Credentials

SHEET_ID = "1VnoDL-kWSP1XGXlRo69YNbNtyMc8FaUKio3oMhurPUw"

# Column index (1-based) for each month
MONTH_COL = {1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 7,
             7: 8, 8: 9, 9: 10, 10: 11, 11: 12, 12: 13}

# Tab names in the sheet
TAB_OVERLAND    = "Overland"       # combined Overland + Truck
TAB_OV_TRUCK    = "OV-Truck"       # Food Truck only
TAB_OV_CATERING = "OV-Catering"    # Overland Catering
TAB_STATE       = "State"
TAB_RAPIDO      = "Rapido"

ROW_DAYS   = 13   # "Current # Days Complete"
ROW_ACTUAL = 14   # actual MTD sales
ROW_RAPIDO_CATERING = 15  # Rapido catering row


def _get_client():
    """Return an authenticated gspread client using service account credentials."""
    creds_json = os.environ.get("GOOGLE_SHEETS_CREDENTIALS")
    if creds_json:
        info = json.loads(creds_json)
    else:
        # Fall back to local file for testing
        local = os.path.join(os.path.dirname(__file__), "..", "service_account.json")
        with open(local) as f:
            info = json.load(f)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(info, scopes=scopes)
    return gspread.authorize(creds)


def _col_letter(col_index):
    """Convert 1-based column index to letter (1->A, 2->B, ...)."""
    return chr(ord("A") + col_index - 1)


def _write_cell(ws, row, col_index, value):
    """Write a single value to a cell identified by row number and 1-based column index."""
    cell = f"{_col_letter(col_index)}{row}"
    ws.update(cell, [[value]])


def update_sales_goals(scorecard_data: dict):
    """
    Main entry point.  scorecard_data is the dict produced by collect_data.py.
    Expected keys (MTD totals):
        overland_retail_mtd, overland_catering_mtd, food_truck_mtd,
        state_mtd, rapido_mtd, rapido_catering_mtd (optional)
    Also needs: days_elapsed (int) for the current month.
    """
    today = datetime.date.today()
    # Data is for yesterday (the last complete day)
    report_date = today - datetime.timedelta(days=1)
    month = report_date.month
    col = MONTH_COL[month]

    # Days elapsed = day-of-month of report_date
    days_elapsed = report_date.day

    try:
        client = _get_client()
        sh = client.open_by_key(SHEET_ID)
    except Exception as e:
        print(f"[sheets_writer] Could not connect to Google Sheets: {e}")
        return

    def _ws(tab_name):
        try:
            return sh.worksheet(tab_name)
        except Exception as e:
            print(f"[sheets_writer] Tab '{tab_name}' not found: {e}")
            return None

    # ── Overland (combined Overland Retail + Food Truck) ──────────────────────
    overland_retail = scorecard_data.get("overland_retail_mtd", 0) or 0
    food_truck      = scorecard_data.get("food_truck_mtd", 0) or 0
    combined        = round(overland_retail + food_truck, 2)
    ws = _ws(TAB_OVERLAND)
    if ws:
        _write_cell(ws, ROW_DAYS,   col, days_elapsed)
        _write_cell(ws, ROW_ACTUAL, col, combined)
        print(f"[sheets_writer] Overland tab updated: days={days_elapsed}, sales={combined}")

    # ── OV-Truck (Food Truck only) ────────────────────────────────────────────
    ws = _ws(TAB_OV_TRUCK)
    if ws:
        _write_cell(ws, ROW_DAYS,   col, days_elapsed)
        _write_cell(ws, ROW_ACTUAL, col, round(food_truck, 2))
        print(f"[sheets_writer] OV-Truck tab updated: sales={food_truck}")

    # ── OV-Catering ───────────────────────────────────────────────────────────
    ov_catering = scorecard_data.get("overland_catering_mtd", 0) or 0
    ws = _ws(TAB_OV_CATERING)
    if ws:
        _write_cell(ws, ROW_DAYS,   col, days_elapsed)
        _write_cell(ws, ROW_ACTUAL, col, round(ov_catering, 2))
        print(f"[sheets_writer] OV-Catering tab updated: sales={ov_catering}")

    # ── State Street ──────────────────────────────────────────────────────────
    state = scorecard_data.get("state_mtd", 0) or 0
    ws = _ws(TAB_STATE)
    if ws:
        _write_cell(ws, ROW_DAYS,   col, days_elapsed)
        _write_cell(ws, ROW_ACTUAL, col, round(state, 2))
        print(f"[sheets_writer] State tab updated: sales={state}")

    # ── Rapido ────────────────────────────────────────────────────────────────
    rapido_instore  = scorecard_data.get("rapido_mtd", 0) or 0
    rapido_catering = scorecard_data.get("rapido_catering_mtd", 0) or 0
    ws = _ws(TAB_RAPIDO)
    if ws:
        _write_cell(ws, ROW_DAYS,   col, days_elapsed)
        _write_cell(ws, ROW_ACTUAL, col, round(rapido_instore, 2))
        if rapido_catering:
            _write_cell(ws, ROW_RAPIDO_CATERING, col, round(rapido_catering, 2))
        print(f"[sheets_writer] Rapido tab updated: in-store={rapido_instore}, catering={rapido_catering}")

    print("[sheets_writer] All tabs updated successfully.")
