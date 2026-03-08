"""
QU POS Fetcher — Net Sales for Overland (Retail + Catering), State, Eubank, Rapido
Uses the QU Enterprise Intelligence web dashboard (admin.qubeyond.com)

Key findings from diagnostics:
- Login: page.locator().fill() + force=True click works
- Navigate home first, then to report URL (SPA routing)
- Date filter: native <select> inside hidden panel, set via JS
- Filter panel: HIDDEN by default, must click "Show Filters" first
- Store List radio: click via JS after Show Filters
- Select Store input: autocomplete searches by STORE NAME, not ID
  - Must type store name keyword (e.g. "Overland", "State", "Eubank", "Rapido")
  - Then click the matching dropdown option
- Run Report button: click via JS (not visible to Playwright)
- Table: split into 17+ separate <table> elements by section
  - Must read ALL tables to find Net Sales, Labor %, Avg Check, etc.
- Date column: table has multiple date columns, find by matching report_date

Store search keywords (confirmed from admin.qubeyond.com store list):
  overland [810]  → search "Overland"
  state    [811]  → search "State"
  eubank   [5645] → search "Eubank"
  rapido   [7209] → search "Rapido"
"""

import os
import logging
import time
import re
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Map location keys to search keywords for the store autocomplete
# These must match the store names as they appear in QU Beyond's store list
# Rapido = "7201 - Meridian, ID - Fairview [814]" (search by "Fairview")
STORE_SEARCH = {
    "overland": "Overland",
    "state":    "State St",
    "eubank":   "Eubank",
    "rapido":   "Fairview",
}

QU_BASE_URL = "https://admin.qubeyond.com"
QU_REPORT_URL = f"{QU_BASE_URL}/reports/overview/summary-by-date"


def get_qu_credentials():
    username = os.environ.get("QU_USERNAME", "seth.brink")
    password = os.environ.get("QU_PASSWORD", "")
    if not password:
        raise ValueError("QU_PASSWORD environment variable not set")
    return username, password


def fetch_all_locations(report_date: date = None) -> dict:
    if report_date is None:
        report_date = date.today() - timedelta(days=1)

    empty = {k: _empty_result() for k in
             ["overland_retail", "overland_catering", "state", "eubank", "rapido"]}

    try:
        username, password = get_qu_credentials()
    except ValueError as e:
        logger.warning(f"QU POS credentials not configured: {e}")
        return empty

    try:
        return _fetch_via_playwright(report_date, username, password)
    except Exception as e:
        logger.error(f"Playwright fetch failed: {e}", exc_info=True)

    return empty


def _fetch_via_playwright(report_date: date, username: str, password: str) -> dict:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

    results = {k: _empty_result() for k in
               ["overland_retail", "overland_catering", "state", "eubank", "rapido"]}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        try:
            # ── Login ────────────────────────────────────────────────────────
            logger.info("Navigating to QU Beyond login...")
            page.goto(f"{QU_BASE_URL}/login", wait_until="networkidle", timeout=30000)
            time.sleep(2)

            page.locator("input").first.fill(username)
            time.sleep(0.3)
            page.locator("input[type='password']").fill(password)
            time.sleep(0.3)
            page.locator("button[type='submit'], button:has-text('LOGIN')").first.click(force=True)

            try:
                page.wait_for_url(lambda url: "login" not in url.lower(), timeout=25000)
                logger.info(f"Logged in. URL: {page.url}")
            except PWTimeout:
                logger.error("Login timed out — check credentials")
                return results

            time.sleep(2)

            # ── Navigate to home first to bootstrap SPA, then to report ─────
            page.goto(QU_BASE_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            page.goto(QU_REPORT_URL, wait_until="domcontentloaded", timeout=30000)
            time.sleep(4)
            logger.info(f"Report loaded. URL: {page.url}")

            # ── Set date to "Yesterday" via JS ────────────────────────────────
            date_result = page.evaluate("""
                () => {
                    const sel = document.querySelector('select');
                    if (!sel) return 'no_select';
                    for (const opt of sel.options) {
                        if (opt.text === 'Yesterday') {
                            sel.value = opt.value;
                            sel.dispatchEvent(new Event('change', {bubbles: true}));
                            return 'set_yesterday';
                        }
                    }
                    return 'yesterday_not_found';
                }
            """)
            logger.info(f"Date filter: {date_result}")
            time.sleep(0.5)

            # ── Click "Show Filters" to expand the filter panel ───────────────
            show_filters_clicked = page.evaluate("""
                () => {
                    const elements = document.querySelectorAll('strong, span, button, a');
                    for (const el of elements) {
                        if (el.textContent.trim() === 'Show Filters') {
                            el.click();
                            if (el.parentElement) el.parentElement.click();
                            return 'clicked: ' + el.tagName;
                        }
                    }
                    const expandBtn = document.querySelector('.expand-filters');
                    if (expandBtn) { expandBtn.click(); return 'clicked by class'; }
                    return 'not_found';
                }
            """)
            logger.info(f"Show Filters: {show_filters_clicked}")
            time.sleep(1.5)

            # Force show the panel if still hidden
            filter_visible = page.evaluate("""
                () => {
                    const panel = document.querySelector('.vertical');
                    if (!panel) return 'panel_not_found';
                    const display = window.getComputedStyle(panel).display;
                    if (display === 'none') {
                        panel.style.display = 'block';
                        return 'forced_visible';
                    }
                    return display;
                }
            """)
            logger.info(f"Filter panel: {filter_visible}")

            # ── Click "Store List" radio ──────────────────────────────────────
            store_list_clicked = page.evaluate("""
                () => {
                    const labels = document.querySelectorAll('label');
                    for (const label of labels) {
                        if (label.textContent.trim() === 'Store List') {
                            const radio = label.querySelector('input[type="radio"]');
                            if (radio) {
                                radio.click();
                                radio.checked = true;
                                radio.dispatchEvent(new Event('change', {bubbles: true}));
                            }
                            label.click();
                            return 'clicked Store List';
                        }
                    }
                    return 'Store List not found';
                }
            """)
            logger.info(f"Store List radio: {store_list_clicked}")
            time.sleep(1.5)

            # ── Fetch data for each location ─────────────────────────────────
            for location_key, search_term in STORE_SEARCH.items():
                logger.info(f"\n{'='*50}")
                logger.info(f"Fetching {location_key} (search: '{search_term}')...")
                try:
                    data = _run_report_for_store(page, search_term, report_date)
                    logger.info(f"  net_sales={data.get('net_sales')}, "
                                f"labor_pct={data.get('labor_pct')}, "
                                f"avg_check={data.get('avg_check')}")

                    if location_key == "overland":
                        results["overland_retail"] = {
                            "net_sales": data.get("net_sales"),
                            "labor_pct": data.get("labor_pct"),
                            "avg_check": data.get("avg_check"),
                            "sos": None,
                            "trans_count": data.get("trans_count"),
                        }
                        results["overland_catering"] = {
                            "net_sales": data.get("catering_sales"),
                            "labor_pct": None,
                            "avg_check": None,
                            "sos": None,
                            "trans_count": None,
                        }
                    else:
                        results[location_key] = {
                            "net_sales": data.get("net_sales"),
                            "labor_pct": data.get("labor_pct"),
                            "avg_check": data.get("avg_check"),
                            "sos": None,
                            "trans_count": data.get("trans_count"),
                        }

                except Exception as e:
                    logger.error(f"Error fetching {location_key}: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Playwright session error: {e}", exc_info=True)
        finally:
            browser.close()

    return results


def _run_report_for_store(page, search_term: str, report_date: date) -> dict:
    """Select a store by name and run the report, then parse the results."""
    from playwright.sync_api import TimeoutError as PWTimeout

    # ── Remove any previously selected store tags ────────────────────────────
    page.evaluate("""
        () => {
            const removeBtns = document.querySelectorAll(
                '.o-inputit__item-delete, .multiselect__tag-icon, [aria-label="Remove"]'
            );
            removeBtns.forEach(btn => btn.click());
        }
    """)
    time.sleep(0.5)

    # ── Focus the Select Store input via JS ──────────────────────────────────
    focused = page.evaluate("""
        () => {
            const inp = document.querySelector("input[placeholder='Select Store']");
            if (!inp) return 'not_found';
            inp.value = '';
            inp.dispatchEvent(new Event('input', {bubbles: true}));
            inp.focus();
            inp.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
            inp.dispatchEvent(new MouseEvent('click', {bubbles: true}));
            return 'focused';
        }
    """)
    logger.info(f"  Input focus: {focused}")

    if focused != 'focused':
        logger.warning(f"  Could not focus store input")
        return _empty_result()

    time.sleep(0.3)

    # ── Type the search term using keyboard ──────────────────────────────────
    page.keyboard.press('Control+a')
    page.keyboard.press('Delete')
    time.sleep(0.2)
    page.keyboard.type(search_term, delay=100)
    logger.info(f"  Typed '{search_term}'")
    time.sleep(2)

    # ── Check what dropdown options appeared ─────────────────────────────────
    dropdown_items = page.evaluate("""
        () => {
            // Check the autocomplete dropdown
            const menuItems = document.querySelectorAll('.o-acp__item:not(.o-acp__item--empty)');
            if (menuItems.length > 0) {
                return {
                    found: true,
                    items: Array.from(menuItems).map(i => i.innerText.trim()).slice(0, 10)
                };
            }
            // Check for empty message
            const emptyMsg = document.querySelector('.o-acp__item--empty');
            if (emptyMsg) return {found: false, message: emptyMsg.innerText.trim()};
            return {found: false, message: 'no dropdown visible'};
        }
    """)
    logger.info(f"  Dropdown: {dropdown_items}")

    if not dropdown_items.get("found"):
        logger.warning(f"  No dropdown options for '{search_term}': {dropdown_items.get('message')}")
        # Try pressing Enter anyway (might select first match)
        page.keyboard.press("Enter")
        time.sleep(0.5)
    else:
        # Click the option that contains the search term in its text
        # (don't just click the first item — the list may not be filtered)
        option_clicked = page.evaluate(f"""
            () => {{
                const items = document.querySelectorAll('.o-acp__item:not(.o-acp__item--empty)');
                const searchLower = '{search_term}'.toLowerCase();
                // First try to find an item containing the search term
                for (const item of items) {{
                    if (item.innerText.toLowerCase().includes(searchLower)) {{
                        item.click();
                        return 'clicked match: ' + item.innerText.trim().substring(0, 60);
                    }}
                }}
                // If no match found, click first item as fallback
                if (items.length > 0) {{
                    items[0].click();
                    return 'clicked first (no match): ' + items[0].innerText.trim().substring(0, 60);
                }}
                return 'no_items';
            }}
        """)
        logger.info(f"  Option click: {option_clicked}")
        time.sleep(0.5)

    # ── Re-apply date filter to "Yesterday" (selecting a store can reset it) ──
    date_reapply = page.evaluate("""
        () => {
            const sel = document.querySelector('select');
            if (!sel) return 'no_select';
            for (const opt of sel.options) {
                if (opt.text === 'Yesterday') {
                    sel.value = opt.value;
                    sel.dispatchEvent(new Event('change', {bubbles: true}));
                    return 'reapplied_yesterday';
                }
            }
            return 'yesterday_not_found';
        }
    """)
    logger.info(f"  Date re-apply: {date_reapply}")
    time.sleep(0.5)

    # ── Click Run Report via JS ──────────────────────────────────────────────
    run_clicked = page.evaluate("""
        () => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                if (/run.?report/i.test(btn.textContent)) {
                    btn.click();
                    return 'clicked: ' + btn.textContent.trim();
                }
            }
            return 'not_found';
        }
    """)
    logger.info(f"  Run Report: {run_clicked}")

    # ── Wait for report to refresh ───────────────────────────────────────────
    try:
        page.wait_for_function(
            "() => document.querySelectorAll('table').length > 5",
            timeout=20000
        )
        time.sleep(2)
        logger.info("  Report data loaded")
    except PWTimeout:
        logger.warning("  Timed out waiting for report refresh")
        time.sleep(2)

    return _parse_all_tables(page, report_date)


def _parse_all_tables(page, report_date: date = None) -> dict:
    """
    Extract KPI values from ALL tables on the page.
    The report splits data into multiple <table> elements by section.
    """
    result = _empty_result()

    try:
        # Get all tables and their row data
        all_tables = page.evaluate("""
            () => {
                const tables = document.querySelectorAll('table');
                const result = [];
                tables.forEach((table, idx) => {
                    const headerRow = table.querySelector('thead tr, tr:first-child');
                    const headers = headerRow
                        ? Array.from(headerRow.querySelectorAll('th, td')).map(c => c.innerText.trim())
                        : [];

                    const rows = {};
                    const dataRows = table.querySelectorAll('tbody tr, tr');
                    dataRows.forEach(row => {
                        const cells = row.querySelectorAll('td, th');
                        if (cells.length >= 2) {
                            const label = cells[0].innerText.trim();
                            const values = Array.from(cells).slice(1).map(c => c.innerText.trim());
                            if (label && label !== 'Metric') rows[label] = values;
                        }
                    });

                    if (Object.keys(rows).length > 0) {
                        result.push({idx, headers, rows});
                    }
                });
                return result;
            }
        """)

        logger.info(f"  Found {len(all_tables)} non-empty tables")

        # Build a unified row lookup from all tables
        # Use the first table's headers for date column detection
        all_rows = {}
        main_headers = []
        for table in all_tables:
            if not main_headers and table.get("headers"):
                main_headers = table["headers"]
            for label, values in table.get("rows", {}).items():
                if label not in all_rows:
                    all_rows[label] = values

        logger.info(f"  Total unique rows: {len(all_rows)}")
        logger.info(f"  Headers: {main_headers}")

        # Find the correct date column
        col_idx = _find_date_column(main_headers, report_date)
        logger.info(f"  Using column index: {col_idx} (for date {report_date})")

        def get_val(row_name):
            vals = all_rows.get(row_name, [])
            if not vals:
                return None
            if col_idx < len(vals):
                return vals[col_idx]
            return vals[0] if vals else None

        # Log key rows
        for key in ["Net Sales", "Total Labor %", "Check Average (Net)",
                    "Total Checks Count", "Catering"]:
            val = get_val(key)
            logger.info(f"    [{key}] = [{val}] (from {all_rows.get(key, [])})")

        result["net_sales"] = _parse_currency(get_val("Net Sales"))
        result["labor_pct"] = _parse_float(get_val("Total Labor %"))
        result["avg_check"] = _parse_currency(get_val("Check Average (Net)"))
        result["trans_count"] = _parse_int(get_val("Total Checks Count"))
        result["catering_sales"] = _parse_currency(get_val("Catering"))
        result["sos"] = None

    except Exception as e:
        logger.error(f"Error parsing tables: {e}", exc_info=True)

    return result


def _find_date_column(headers: list, report_date: date) -> int:
    """Find the column index matching the report date."""
    if not headers or not report_date:
        return 0

    # Format the date in various ways QU Beyond might display it
    date_formats = [
        report_date.strftime("%m/%d/%Y"),    # 03/06/2026
        report_date.strftime("%-m/%-d/%Y"),  # 3/6/2026
        report_date.strftime("%m/%d/%y"),    # 03/06/26
        report_date.strftime("%-m/%-d/%y"),  # 3/6/26
    ]

    for i, header in enumerate(headers[1:], 0):  # Skip first "Metric" column
        for fmt in date_formats:
            if fmt in header:
                return i

    logger.warning(f"  Date {report_date} not found in headers {headers}, using column 0")
    return 0


def _parse_currency(text) -> float | None:
    if not text:
        return None
    try:
        cleaned = re.sub(r"[,$\s]", "", str(text))
        val = float(cleaned)
        return round(val, 2) if val > 0 else None
    except (ValueError, TypeError):
        return None


def _parse_float(text) -> float | None:
    if not text:
        return None
    try:
        cleaned = re.sub(r"[%,\s]", "", str(text))
        return round(float(cleaned), 2)
    except (ValueError, TypeError):
        return None


def _parse_int(text) -> int | None:
    if not text:
        return None
    try:
        cleaned = re.sub(r"[,\s]", "", str(text))
        return int(float(cleaned))
    except (ValueError, TypeError):
        return None


def _empty_result() -> dict:
    return {
        "net_sales": None,
        "labor_pct": None,
        "avg_check": None,
        "sos": None,
        "trans_count": None,
        "catering_sales": None,
    }
