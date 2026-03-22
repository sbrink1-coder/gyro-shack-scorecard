"""
Gyro Shack Business Scorecard Dashboard
Compares Net Sales actuals vs. targets from Google Sheets
Data Sources: Square API (Food Truck) + QU POS (all other locations)
"""

import streamlit as st
import pandas as pd
import json
import os
from datetime import datetime, date, timedelta
import pytz

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Gyro Shack Scorecard",
    page_icon="🥙",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS for high-visibility external monitor display ──────────────────
st.markdown("""
<style>
  /* Dark background for high-contrast external monitor */
  .stApp { background-color: #0d1117; color: #e6edf3; }
  
  /* Header */
  .dashboard-header {
    background: linear-gradient(135deg, #1a1f2e 0%, #2d1b69 100%);
    border-radius: 12px;
    padding: 20px 30px;
    margin-bottom: 20px;
    border: 1px solid #30363d;
    text-align: center;
  }
  .dashboard-header h1 {
    font-size: 2.4rem;
    font-weight: 800;
    color: #f0f6fc;
    margin: 0;
    letter-spacing: 2px;
  }
  .dashboard-header .subtitle {
    font-size: 1.1rem;
    color: #8b949e;
    margin-top: 6px;
  }
  
  /* Location card */
  .location-card {
    background: #161b22;
    border-radius: 10px;
    padding: 18px;
    border: 1px solid #30363d;
    margin-bottom: 10px;
    height: 100%;
  }
  .location-title {
    font-size: 1.15rem;
    font-weight: 700;
    color: #f0f6fc;
    margin-bottom: 12px;
    padding-bottom: 8px;
    border-bottom: 1px solid #30363d;
    text-transform: uppercase;
    letter-spacing: 1px;
  }
  
  /* KPI metric row */
  .kpi-row {
    display: flex;
    justify-content: space-between;
    gap: 8px;
    margin-bottom: 8px;
  }
  .kpi-box {
    flex: 1;
    border-radius: 8px;
    padding: 10px 8px;
    text-align: center;
    border: 1px solid rgba(255,255,255,0.08);
  }
  .kpi-label {
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    opacity: 0.75;
    margin-bottom: 4px;
  }
  .kpi-value {
    font-size: 1.35rem;
    font-weight: 800;
    line-height: 1.1;
  }
  .kpi-sub {
    font-size: 0.7rem;
    opacity: 0.65;
    margin-top: 2px;
  }
  
  /* Color states */
  .green  { background: rgba(35, 134, 54, 0.25); color: #3fb950; border-color: #238636 !important; }
  .yellow { background: rgba(187, 128, 9, 0.25);  color: #e3b341; border-color: #bb8009 !important; }
  .red    { background: rgba(218, 54, 51, 0.25);  color: #f85149; border-color: #da3633 !important; }
  .gray   { background: rgba(110, 118, 129, 0.15); color: #8b949e; border-color: #30363d !important; }
  
  /* Net Sales main metric */
  .net-sales-main {
    border-radius: 8px;
    padding: 14px 10px;
    text-align: center;
    margin-bottom: 10px;
    border: 2px solid;
  }
  .net-sales-label { font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; opacity: 0.8; }
  .net-sales-actual { font-size: 2rem; font-weight: 900; line-height: 1.1; }
  .net-sales-target { font-size: 0.8rem; opacity: 0.7; margin-top: 2px; }
  .net-sales-pct { font-size: 1.1rem; font-weight: 700; margin-top: 4px; }
  
  /* Section divider */
  .section-divider {
    background: #21262d;
    border-radius: 6px;
    padding: 6px 14px;
    margin: 14px 0 10px 0;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    color: #8b949e;
    border-left: 3px solid #388bfd;
  }
  
  /* Last updated */
  .last-updated {
    text-align: center;
    font-size: 0.8rem;
    color: #6e7681;
    padding: 10px;
    border-top: 1px solid #21262d;
    margin-top: 10px;
  }
  
  /* Streamlit overrides */
  .block-container { padding: 1rem 1.5rem 1rem 1.5rem !important; max-width: 100% !important; }
  div[data-testid="column"] { padding: 0 6px !important; }
  .stButton button { width: 100%; }
  
  /* Row label */
  .row-label {
    font-size: 0.85rem;
    font-weight: 700;
    color: #8b949e;
    text-transform: uppercase;
    letter-spacing: 1.5px;
    padding: 4px 0 8px 0;
  }
</style>
""", unsafe_allow_html=True)


# ── Helper functions ──────────────────────────────────────────────────────────

def color_class(value, thresholds, higher_is_better=True):
    """Return CSS class based on value vs thresholds."""
    if value is None:
        return "gray"
    if higher_is_better:
        if value >= thresholds[0]:
            return "green"
        elif value >= thresholds[1]:
            return "yellow"
        else:
            return "red"
    else:
        if value <= thresholds[0]:
            return "green"
        elif value <= thresholds[1]:
            return "yellow"
        else:
            return "red"


def net_sales_color(pct):
    """Color for Net Sales % of target."""
    if pct is None:
        return "gray"
    if pct >= 100:
        return "green"
    elif pct >= 90:
        return "yellow"
    else:
        return "red"


def format_currency(val):
    if val is None:
        return "—"
    return f"${val:,.2f}"


def format_pct(val):
    if val is None:
        return "—"
    return f"{val:.1f}%"


def format_time(minutes):
    """Format minutes as M:SS."""
    if minutes is None:
        return "—"
    m = int(minutes)
    s = int((minutes - m) * 60)
    return f"{m}:{s:02d}"


def sos_color(minutes):
    """Speed of Service color: Green <4:00, Yellow 4:00-5:00, Red >5:00."""
    if minutes is None:
        return "gray"
    if minutes < 4.0:
        return "green"
    elif minutes <= 5.0:
        return "yellow"
    else:
        return "red"


def labor_color(pct):
    """Labor % color: Green ≤20%, Yellow 21-23%, Red >24%."""
    if pct is None:
        return "gray"
    if pct <= 20:
        return "green"
    elif pct <= 23:
        return "yellow"
    else:
        return "red"


def avg_check_color(val):
    """Avg Check color: Green >$18, Yellow $15-$18, Red <$15."""
    if val is None:
        return "gray"
    if val > 18:
        return "green"
    elif val >= 15:
        return "yellow"
    else:
        return "red"


def render_location_card(name, data, target):
    """Render a single location scorecard card."""
    net_sales = data.get("net_sales")
    labor_pct = data.get("labor_pct")
    avg_check = data.get("avg_check")
    sos = data.get("sos")
    trans_count = data.get("trans_count")

    # Net Sales % of target
    ns_pct = None
    if net_sales is not None and target and target > 0:
        ns_pct = (net_sales / target) * 100

    ns_color = net_sales_color(ns_pct)
    lb_color = labor_color(labor_pct)
    ac_color = avg_check_color(avg_check)
    ss_color = sos_color(sos)

    # Net Sales main block
    ns_html = f"""
    <div class="net-sales-main {ns_color}">
      <div class="net-sales-label">Net Sales</div>
      <div class="net-sales-actual">{format_currency(net_sales)}</div>
      <div class="net-sales-target">Target: {format_currency(target)}</div>
      <div class="net-sales-pct">{format_pct(ns_pct) if ns_pct else '—'} of goal</div>
    </div>
    """

    # KPI boxes
    kpi_html = f"""
    <div class="kpi-row">
      <div class="kpi-box {lb_color}">
        <div class="kpi-label">Labor %</div>
        <div class="kpi-value">{format_pct(labor_pct)}</div>
        <div class="kpi-sub">≤20% target</div>
      </div>
      <div class="kpi-box {ac_color}">
        <div class="kpi-label">Avg Check</div>
        <div class="kpi-value">{format_currency(avg_check)}</div>
        <div class="kpi-sub">&gt;$18 target</div>
      </div>
      <div class="kpi-box {ss_color}">
        <div class="kpi-label">SOS</div>
        <div class="kpi-value">{format_time(sos)}</div>
        <div class="kpi-sub">&lt;4:00 target</div>
      </div>
    </div>
    <div class="kpi-row">
      <div class="kpi-box gray">
        <div class="kpi-label">Transactions</div>
        <div class="kpi-value">{trans_count if trans_count is not None else '—'}</div>
        <div class="kpi-sub">today</div>
      </div>
    </div>
    """

    card_html = f"""
    <div class="location-card">
      <div class="location-title">{name}</div>
      {ns_html}
      {kpi_html}
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)


# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_scorecard_data():
    """Load the latest scorecard data from the JSON cache file."""
    data_file = os.path.join(os.path.dirname(__file__), "data", "scorecard_data.json")
    if os.path.exists(data_file):
        with open(data_file, "r") as f:
            return json.load(f)
    # Return empty/demo data if no cache exists
    return get_demo_data()


def get_demo_data():
    """Return demo/placeholder data when live data is unavailable."""
    today = date.today()
    month = today.month
    
    # Monthly daily targets by location (from Google Sheet)
    monthly_targets = {
        "overland_retail": [1980, 2027, 2515, 2706, 2783, 2733, 2789, 2692, 2884, 2912, 2542, 2893],
        "overland_catering": [498, 738, 475, 969, 547, 499, 415, 667, 658, 660, 367, 157],
        "food_truck": [339, 624, 1474, 606, 1035, 1051, 1102, 1168, 554, 388, 723, 838],
        "state": [1694, 1607, 2298, 2198, 2177, 2000, 2177, 2177, 2000, 2177, 2069, 1750],
        "eubank": [2145, 2036, 2911, 3276, 2758, 2533, 2758, 2758, 2533, 2758, 2621, 2533],
        "rapido": [1694, 1607, 2298, 2198, 2177, 2000, 2177, 2177, 2000, 2177, 2069, 1750],
    }
    
    target_idx = month - 1
    
    return {
        "last_updated": datetime.now().isoformat(),
        "report_date": today.isoformat(),
        "data_source": "demo",
        "locations": {
            "overland_retail": {
                "name": "Overland — Retail",
                "net_sales": None,
                "target": monthly_targets["overland_retail"][target_idx],
                "labor_pct": None,
                "avg_check": None,
                "sos": None,
                "trans_count": None,
            },
            "overland_catering": {
                "name": "Overland — Catering",
                "net_sales": None,
                "target": monthly_targets["overland_catering"][target_idx],
                "labor_pct": None,
                "avg_check": None,
                "sos": None,
                "trans_count": None,
            },
            "food_truck": {
                "name": "Overland — Food Truck",
                "net_sales": None,
                "target": monthly_targets["food_truck"][target_idx],
                "labor_pct": None,
                "avg_check": None,
                "sos": None,
                "trans_count": None,
            },
            "state": {
                "name": "State Street",
                "net_sales": None,
                "target": monthly_targets["state"][target_idx],
                "labor_pct": None,
                "avg_check": None,
                "sos": None,
                "trans_count": None,
            },
            "eubank": {
                "name": "Eubank",
                "net_sales": None,
                "target": monthly_targets["eubank"][target_idx],
                "labor_pct": None,
                "avg_check": None,
                "sos": None,
                "trans_count": None,
            },
            "rapido": {
                "name": "Rapido (San Mateo)",
                "net_sales": None,
                "target": monthly_targets["rapido"][target_idx],
                "labor_pct": None,
                "avg_check": None,
                "sos": None,
                "trans_count": None,
            },
        }
    }


# ── Main dashboard ────────────────────────────────────────────────────────────

def main():
    # Load data
    scorecard = load_scorecard_data()
    locations = scorecard.get("locations", {})
    report_date = scorecard.get("report_date", date.today().isoformat())
    last_updated = scorecard.get("last_updated", "Unknown")
    data_source = scorecard.get("data_source", "demo")

    # Parse last_updated
    try:
        lu_dt = datetime.fromisoformat(last_updated)
        lu_str = lu_dt.strftime("%B %d, %Y at %I:%M %p")
    except Exception:
        lu_str = last_updated

    # Parse report date
    try:
        rd_dt = datetime.strptime(report_date, "%Y-%m-%d")
        rd_str = rd_dt.strftime("%A, %B %d, %Y")
    except Exception:
        rd_str = report_date

    # ── Header ──
    source_badge = "🔴 DEMO MODE" if data_source == "demo" else "🟢 LIVE DATA"
    st.markdown(f"""
    <div class="dashboard-header">
      <h1>🥙 GYRO SHACK SCORECARD</h1>
      <div class="subtitle">
        {rd_str} &nbsp;|&nbsp; {source_badge} &nbsp;|&nbsp; Updated: {lu_str}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Color Legend ──
    col_l1, col_l2, col_l3, col_l4 = st.columns(4)
    with col_l1:
        st.markdown('<div class="kpi-box green" style="padding:6px;text-align:center;border-radius:6px;font-size:0.75rem;font-weight:700;">🟢 GREEN = On/Above Target</div>', unsafe_allow_html=True)
    with col_l2:
        st.markdown('<div class="kpi-box yellow" style="padding:6px;text-align:center;border-radius:6px;font-size:0.75rem;font-weight:700;">🟡 YELLOW = 90–99% of Target</div>', unsafe_allow_html=True)
    with col_l3:
        st.markdown('<div class="kpi-box red" style="padding:6px;text-align:center;border-radius:6px;font-size:0.75rem;font-weight:700;">🔴 RED = Below 90% of Target</div>', unsafe_allow_html=True)
    with col_l4:
        st.markdown('<div class="kpi-box gray" style="padding:6px;text-align:center;border-radius:6px;font-size:0.75rem;font-weight:700;">⚪ GRAY = No Data Available</div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Row 1: Overland Retail | Overland Catering | Food Truck ──
    st.markdown('<div class="section-divider">📍 Overland Location</div>', unsafe_allow_html=True)
    row1_col1, row1_col2, row1_col3 = st.columns(3)

    with row1_col1:
        loc = locations.get("overland_retail", {})
        render_location_card(
            loc.get("name", "Overland — Retail"),
            loc,
            loc.get("target")
        )

    with row1_col2:
        loc = locations.get("overland_catering", {})
        render_location_card(
            loc.get("name", "Overland — Catering"),
            loc,
            loc.get("target")
        )

    with row1_col3:
        loc = locations.get("food_truck", {})
        render_location_card(
            loc.get("name", "Overland — Food Truck"),
            loc,
            loc.get("target")
        )

    # ── Row 2: State | Eubank | Rapido ──
    st.markdown('<div class="section-divider">📍 New Mexico & State Street</div>', unsafe_allow_html=True)
    row2_col1, row2_col2, row2_col3 = st.columns(3)

    with row2_col1:
        loc = locations.get("state", {})
        render_location_card(
            loc.get("name", "State Street"),
            loc,
            loc.get("target")
        )

    with row2_col2:
        loc = locations.get("eubank", {})
        render_location_card(
            loc.get("name", "Eubank"),
            loc,
            loc.get("target")
        )

    with row2_col3:
        loc = locations.get("rapido", {})
        render_location_card(
            loc.get("name", "Rapido (San Mateo)"),
            loc,
            loc.get("target")
        )

    # ── Company Total Summary ──
    st.markdown('<div class="section-divider">📊 Company Totals</div>', unsafe_allow_html=True)
    
    total_sales = sum(
        loc.get("net_sales", 0) or 0
        for loc in locations.values()
    )
    total_target = sum(
        loc.get("target", 0) or 0
        for loc in locations.values()
    )
    total_pct = (total_sales / total_target * 100) if total_target > 0 and total_sales > 0 else None
    total_color = net_sales_color(total_pct)

    t_col1, t_col2, t_col3, t_col4 = st.columns(4)
    with t_col1:
        st.markdown(f"""
        <div class="net-sales-main {total_color}">
          <div class="net-sales-label">Total Net Sales</div>
          <div class="net-sales-actual">{format_currency(total_sales if total_sales > 0 else None)}</div>
          <div class="net-sales-target">Target: {format_currency(total_target)}</div>
          <div class="net-sales-pct">{format_pct(total_pct) if total_pct else '—'} of goal</div>
        </div>
        """, unsafe_allow_html=True)
    with t_col2:
        active_locs = [l for l in locations.values() if l.get("net_sales") is not None]
        avg_labor = (
            sum(l.get("labor_pct", 0) or 0 for l in active_locs) / len(active_locs)
            if active_locs else None
        )
        st.markdown(f"""
        <div class="kpi-box {labor_color(avg_labor)}" style="padding:18px;border-radius:8px;text-align:center;">
          <div class="kpi-label">Avg Labor %</div>
          <div class="kpi-value" style="font-size:1.8rem;">{format_pct(avg_labor)}</div>
          <div class="kpi-sub">across all locations</div>
        </div>
        """, unsafe_allow_html=True)
    with t_col3:
        avg_check_all = (
            sum(l.get("avg_check", 0) or 0 for l in active_locs) / len(active_locs)
            if active_locs else None
        )
        st.markdown(f"""
        <div class="kpi-box {avg_check_color(avg_check_all)}" style="padding:18px;border-radius:8px;text-align:center;">
          <div class="kpi-label">Avg Check</div>
          <div class="kpi-value" style="font-size:1.8rem;">{format_currency(avg_check_all)}</div>
          <div class="kpi-sub">across all locations</div>
        </div>
        """, unsafe_allow_html=True)
    with t_col4:
        total_trans = sum(l.get("trans_count", 0) or 0 for l in locations.values())
        st.markdown(f"""
        <div class="kpi-box gray" style="padding:18px;border-radius:8px;text-align:center;">
          <div class="kpi-label">Total Transactions</div>
          <div class="kpi-value" style="font-size:1.8rem;">{total_trans if total_trans > 0 else '—'}</div>
          <div class="kpi-sub">all locations today</div>
        </div>
        """, unsafe_allow_html=True)

    # ── Refresh button ──
    st.markdown("<br>", unsafe_allow_html=True)
    col_r1, col_r2, col_r3 = st.columns([1, 1, 1])
    with col_r2:
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # ── Footer ──
    st.markdown(f"""
    <div class="last-updated">
      Data auto-refreshes every 5 minutes &nbsp;|&nbsp; 
      Daily scrape runs at 4:00 AM MST via GitHub Actions &nbsp;|&nbsp;
      Sources: Square API (Food Truck) + QU POS (All Other Locations)
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
