"""
Gyro Shack Store Scoreboard
Shows performance vs. targets without revealing dollar figures.
Data Sources: Square API (Food Truck) + QU POS (all other locations)
"""

import streamlit as st
import json
import os
from datetime import datetime, date, timedelta

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Store Scoreboard",
    page_icon="🥙",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  .stApp { background-color: #0d1117; color: #e6edf3; }

  .dashboard-header {
    background: linear-gradient(135deg, #1a1f2e 0%, #2d1b69 100%);
    border-radius: 12px;
    padding: 20px 30px;
    margin-bottom: 20px;
    border: 1px solid #30363d;
    text-align: center;
  }
  .dashboard-header h1 {
    font-size: 2.4rem; font-weight: 800; color: #f0f6fc;
    margin: 0; letter-spacing: 2px;
  }
  .dashboard-header .subtitle {
    font-size: 1.1rem; color: #8b949e; margin-top: 6px;
  }

  .location-card {
    background: #161b22; border-radius: 10px; padding: 18px;
    border: 1px solid #30363d; margin-bottom: 10px;
  }
  .location-title {
    font-size: 1.15rem; font-weight: 700; color: #f0f6fc;
    margin-bottom: 12px; padding-bottom: 8px;
    border-bottom: 1px solid #30363d;
    text-transform: uppercase; letter-spacing: 1px;
  }

  /* Status comparison box — two halves side by side */
  .sales-compare {
    display: flex; gap: 8px; margin-bottom: 10px;
  }
  .sales-half {
    flex: 1; border-radius: 8px; padding: 14px 8px;
    text-align: center; border: 2px solid;
  }
  .sales-half-label {
    font-size: 0.6rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1px; opacity: 0.75; margin-bottom: 6px;
  }
  .sales-half-pct {
    font-size: 2rem; font-weight: 900; line-height: 1.1;
  }
  .sales-half-sub {
    font-size: 0.7rem; opacity: 0.65; margin-top: 4px;
  }

  /* Checks delta box */
  .checks-delta {
    border-radius: 8px; padding: 12px 8px;
    text-align: center; border: 2px solid;
    margin-bottom: 10px;
  }
  .checks-delta-label {
    font-size: 0.6rem; font-weight: 700; text-transform: uppercase;
    letter-spacing: 1px; opacity: 0.75; margin-bottom: 4px;
  }
  .checks-delta-value {
    font-size: 2rem; font-weight: 900; line-height: 1.1;
  }
  .checks-delta-sub {
    font-size: 0.7rem; opacity: 0.65; margin-top: 4px;
  }

  /* KPI metric row */
  .kpi-row {
    display: flex; justify-content: space-between;
    gap: 8px; margin-bottom: 8px;
  }
  .kpi-box {
    flex: 1; border-radius: 8px; padding: 10px 8px;
    text-align: center; border: 1px solid rgba(255,255,255,0.08);
  }
  .kpi-label {
    font-size: 0.65rem; font-weight: 600; text-transform: uppercase;
    letter-spacing: 0.8px; opacity: 0.75; margin-bottom: 4px;
  }
  .kpi-value { font-size: 1.35rem; font-weight: 800; line-height: 1.1; }
  .kpi-sub   { font-size: 0.7rem; opacity: 0.65; margin-top: 2px; }

  /* Color states */
  .green  { background: rgba(35,134,54,0.25);   color: #3fb950; border-color: #238636 !important; }
  .yellow { background: rgba(187,128,9,0.25);   color: #e3b341; border-color: #bb8009 !important; }
  .red    { background: rgba(218,54,51,0.25);   color: #f85149; border-color: #da3633 !important; }
  .gray   { background: rgba(110,118,129,0.15); color: #8b949e; border-color: #30363d !important; }
  .blue   { background: rgba(56,139,253,0.15);  color: #79c0ff; border-color: #388bfd !important; }

  .section-divider {
    background: #21262d; border-radius: 6px;
    padding: 6px 14px; margin: 14px 0 10px 0;
    font-size: 0.75rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 1.5px;
    color: #8b949e; border-left: 3px solid #388bfd;
  }
  .last-updated {
    text-align: center; font-size: 0.8rem; color: #6e7681;
    padding: 10px; border-top: 1px solid #21262d; margin-top: 10px;
  }

  .block-container { padding: 1rem 1.5rem !important; max-width: 100% !important; }
  div[data-testid="column"] { padding: 0 6px !important; }
  .stButton button { width: 100%; }
</style>
""", unsafe_allow_html=True)


# ── Helper functions ──────────────────────────────────────────────────────────

AVG_CHECK_TARGET = 18.00  # $18 target used to calculate goal transaction count

def net_sales_color(pct):
    if pct is None: return "gray"
    if pct >= 100:  return "green"
    if pct >= 90:   return "yellow"
    return "red"

def labor_color(pct):
    if pct is None: return "gray"
    if pct <= 20:   return "green"
    if pct <= 23:   return "yellow"
    return "red"

def avg_check_color(val):
    if val is None: return "gray"
    if val > 18:    return "green"
    if val >= 15:   return "yellow"
    return "red"

def sos_color(minutes):
    if minutes is None: return "gray"
    if minutes < 4.0:   return "green"
    if minutes <= 5.0:  return "yellow"
    return "red"

def checks_delta_color(delta):
    if delta is None: return "gray"
    if delta >= 0:    return "green"
    if delta >= -3:   return "yellow"
    return "red"

def fmt_pct(val):
    if val is None: return "—"
    return f"{val:.1f}%"

def fmt_time(minutes):
    if minutes is None: return "—"
    m = int(minutes)
    s = int((minutes - m) * 60)
    return f"{m}:{s:02d}"

def fmt_cur(val):
    if val is None: return "—"
    return f"${val:,.2f}"


def render_location_card(name, data):
    """Render a store-level location card: % of goal (no dollars) + checks over/under."""

    net_sales       = data.get("net_sales")
    target          = data.get("target")
    mtd_net_sales   = data.get("mtd_net_sales")
    mtd_target      = data.get("mtd_target")
    labor_pct       = data.get("labor_pct")
    avg_check       = data.get("avg_check")
    sos             = data.get("sos")
    trans_count     = data.get("trans_count")

    # Daily % of target
    daily_pct = (net_sales / target * 100) if (net_sales is not None and target and target > 0) else None
    # MTD % of target
    mtd_pct   = (mtd_net_sales / mtd_target * 100) if (mtd_net_sales is not None and mtd_target and mtd_target > 0) else None

    daily_color = net_sales_color(daily_pct)
    mtd_color   = net_sales_color(mtd_pct)
    lb_color    = labor_color(labor_pct)
    ac_color    = avg_check_color(avg_check)
    ss_color    = sos_color(sos)

    # ── Checks over/under goal ──
    # Goal transactions = daily sales target ÷ avg check target ($18)
    # Delta = actual transactions − goal transactions
    if target and target > 0 and trans_count is not None:
        goal_trans = round(target / AVG_CHECK_TARGET)
        delta      = trans_count - goal_trans
        delta_color = checks_delta_color(delta)
        delta_sign  = "+" if delta >= 0 else ""
        delta_label = f"{delta_sign}{delta} checks vs. goal ({goal_trans} needed)"
        delta_sub   = f"Actual: {trans_count} &nbsp;|&nbsp; Goal: {goal_trans}"
    else:
        delta       = None
        delta_color = "gray"
        delta_label = "—"
        delta_sub   = "No data"

    # ── Status boxes (% of goal — no dollar amounts) ──
    status_html = f"""
    <div class="sales-compare">
      <div class="sales-half {daily_color}">
        <div class="sales-half-label">Today</div>
        <div class="sales-half-pct">{fmt_pct(daily_pct) if daily_pct is not None else '—'}</div>
        <div class="sales-half-sub">of daily goal</div>
      </div>
      <div class="sales-half {mtd_color}">
        <div class="sales-half-label">MTD</div>
        <div class="sales-half-pct">{fmt_pct(mtd_pct) if mtd_pct is not None else '—'}</div>
        <div class="sales-half-sub">of monthly goal</div>
      </div>
    </div>
    """

    # ── Checks delta box ──
    checks_html = f"""
    <div class="checks-delta {delta_color}">
      <div class="checks-delta-label">Checks vs. Goal</div>
      <div class="checks-delta-value">{delta_label}</div>
      <div class="checks-delta-sub">{delta_sub}</div>
    </div>
    """

    # ── KPI boxes ──
    kpi_html = f"""
    <div class="kpi-row">
      <div class="kpi-box {lb_color}">
        <div class="kpi-label">Labor %</div>
        <div class="kpi-value">{fmt_pct(labor_pct)}</div>
        <div class="kpi-sub">≤20% target</div>
      </div>
      <div class="kpi-box {ac_color}">
        <div class="kpi-label">Avg Check</div>
        <div class="kpi-value">{fmt_cur(avg_check)}</div>
        <div class="kpi-sub">&gt;$18 target</div>
      </div>
      <div class="kpi-box {ss_color}">
        <div class="kpi-label">SOS</div>
        <div class="kpi-value">{fmt_time(sos)}</div>
        <div class="kpi-sub">&lt;4:00 target</div>
      </div>
    </div>
    """

    card_html = f"""
    <div class="location-card">
      <div class="location-title">{name}</div>
      {status_html}
      {checks_html}
      {kpi_html}
    </div>
    """
    st.markdown(card_html, unsafe_allow_html=True)


# ── Data loading ──────────────────────────────────────────────────────────────

@st.cache_data(ttl=300)
def load_scorecard_data():
    data_file = os.path.join(os.path.dirname(__file__), "data", "scorecard_data.json")
    if os.path.exists(data_file):
        with open(data_file, "r") as f:
            return json.load(f)
    return get_demo_data()


def get_demo_data():
    today = date.today()
    month = today.month
    days  = today.day

    DAILY_TARGETS = {
        "overland_retail":    [1980, 2027, 2515, 2706, 2783, 2733, 2789, 2692, 2884, 2912, 2542, 2893],
        "overland_catering":  [498,  738,  475,  969,  547,  499,  415,  667,  658,  660,  367,  157],
        "food_truck":         [339,  624,  1474, 606,  1035, 1051, 1102, 1168, 554,  388,  723,  838],
        "state":              [1694, 1607, 2298, 2198, 2177, 2000, 2177, 2177, 2000, 2177, 2069, 1750],
        "eubank":             [2145, 2036, 2911, 3276, 2758, 2533, 2758, 2758, 2533, 2758, 2621, 2533],
        "rapido":             [1694, 1607, 2298, 2198, 2177, 2000, 2177, 2177, 2000, 2177, 2069, 1750],
    }
    idx = month - 1

    def loc(name, key):
        dt = float(DAILY_TARGETS[key][idx])
        return {
            "name": name, "net_sales": None, "target": dt,
            "labor_pct": None, "avg_check": None, "sos": None, "trans_count": None,
            "mtd_net_sales": None, "mtd_target": round(dt * days, 2),
            "mtd_labor_pct": None, "mtd_avg_check": None, "mtd_trans_count": None,
        }

    return {
        "last_updated": datetime.now().isoformat(),
        "report_date":  today.isoformat(),
        "data_source":  "demo",
        "locations": {
            "overland_retail":   loc("Overland — Retail",      "overland_retail"),
            "overland_catering": loc("Overland — Catering",    "overland_catering"),
            "food_truck":        loc("Overland — Food Truck",  "food_truck"),
            "state":             loc("State Street",           "state"),
            "eubank":            loc("Eubank",                 "eubank"),
            "rapido":            loc("Rapido",                 "rapido"),
        }
    }


# ── Main dashboard ────────────────────────────────────────────────────────────

def main():
    scorecard   = load_scorecard_data()
    locations   = scorecard.get("locations", {})
    report_date = scorecard.get("report_date", date.today().isoformat())
    last_updated = scorecard.get("last_updated", "Unknown")
    data_source  = scorecard.get("data_source", "demo")

    try:
        lu_str = datetime.fromisoformat(last_updated).strftime("%B %d, %Y at %I:%M %p")
    except Exception:
        lu_str = last_updated

    try:
        rd_str = datetime.strptime(report_date, "%Y-%m-%d").strftime("%A, %B %d, %Y")
    except Exception:
        rd_str = report_date

    source_badge = "🔴 DEMO MODE" if data_source == "demo" else "🟢 LIVE DATA"

    # ── Header ──
    st.markdown(f"""
    <div class="dashboard-header">
      <h1>🥙 STORE SCOREBOARD</h1>
      <div class="subtitle">
        {rd_str} &nbsp;|&nbsp; {source_badge} &nbsp;|&nbsp; Updated: {lu_str}
      </div>
    </div>
    """, unsafe_allow_html=True)

    # ── Color Legend ──
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        st.markdown('<div class="kpi-box green" style="padding:6px;text-align:center;border-radius:6px;font-size:0.75rem;font-weight:700;">🟢 GREEN = On/Above Target</div>', unsafe_allow_html=True)
    with c2:
        st.markdown('<div class="kpi-box yellow" style="padding:6px;text-align:center;border-radius:6px;font-size:0.75rem;font-weight:700;">🟡 YELLOW = 90–99% of Target</div>', unsafe_allow_html=True)
    with c3:
        st.markdown('<div class="kpi-box red" style="padding:6px;text-align:center;border-radius:6px;font-size:0.75rem;font-weight:700;">🔴 RED = Below 90% of Target</div>', unsafe_allow_html=True)
    with c4:
        st.markdown('<div class="kpi-box gray" style="padding:6px;text-align:center;border-radius:6px;font-size:0.75rem;font-weight:700;">⚪ GRAY = No Data Available</div>', unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Row 1: Overland Retail | Overland Catering | Food Truck ──
    st.markdown('<div class="section-divider">📍 Overland Location</div>', unsafe_allow_html=True)
    r1c1, r1c2, r1c3 = st.columns(3)

    with r1c1:
        loc = locations.get("overland_retail", {})
        render_location_card(loc.get("name", "Overland — Retail"), loc)

    with r1c2:
        loc = locations.get("overland_catering", {})
        render_location_card(loc.get("name", "Overland — Catering"), loc)

    with r1c3:
        loc = locations.get("food_truck", {})
        render_location_card(loc.get("name", "Overland — Food Truck"), loc)

    # ── Row 2: State | Eubank | Rapido ──
    st.markdown('<div class="section-divider">📍 State Street · Eubank · Rapido</div>', unsafe_allow_html=True)
    r2c1, r2c2, r2c3 = st.columns(3)

    with r2c1:
        loc = locations.get("state", {})
        render_location_card(loc.get("name", "State Street"), loc)

    with r2c2:
        loc = locations.get("eubank", {})
        render_location_card(loc.get("name", "Eubank"), loc)

    with r2c3:
        loc = locations.get("rapido", {})
        render_location_card(loc.get("name", "Rapido"), loc)

    # ── Company Totals ──
    st.markdown('<div class="section-divider">📊 Company Totals</div>', unsafe_allow_html=True)

    active = [l for l in locations.values() if l.get("net_sales") is not None]
    total_daily   = sum(l.get("net_sales", 0) or 0 for l in locations.values())
    total_target  = sum(l.get("target", 0) or 0 for l in locations.values())
    total_mtd     = sum(l.get("mtd_net_sales", 0) or 0 for l in locations.values())
    total_mtd_tgt = sum(l.get("mtd_target", 0) or 0 for l in locations.values())
    total_daily_pct = (total_daily / total_target * 100) if total_target > 0 and total_daily > 0 else None
    total_mtd_pct   = (total_mtd / total_mtd_tgt * 100) if total_mtd_tgt > 0 and total_mtd > 0 else None

    avg_labor = (sum(l.get("labor_pct", 0) or 0 for l in active) / len(active)) if active else None
    avg_check_all = (sum(l.get("avg_check", 0) or 0 for l in active) / len(active)) if active else None
    total_trans = sum(l.get("trans_count", 0) or 0 for l in locations.values())

    # Company-level checks delta
    total_goal_trans = round(total_target / AVG_CHECK_TARGET) if total_target > 0 else None
    total_delta = (total_trans - total_goal_trans) if (total_goal_trans and total_trans > 0) else None

    tc1, tc2, tc3, tc4 = st.columns(4)

    with tc1:
        st.markdown(f"""
        <div class="sales-compare">
          <div class="sales-half {net_sales_color(total_daily_pct)}">
            <div class="sales-half-label">Today — All Locations</div>
            <div class="sales-half-pct">{fmt_pct(total_daily_pct) if total_daily_pct else '—'}</div>
            <div class="sales-half-sub">of daily goal</div>
          </div>
          <div class="sales-half {net_sales_color(total_mtd_pct)}">
            <div class="sales-half-label">MTD — All Locations</div>
            <div class="sales-half-pct">{fmt_pct(total_mtd_pct) if total_mtd_pct else '—'}</div>
            <div class="sales-half-sub">of monthly goal</div>
          </div>
        </div>
        """, unsafe_allow_html=True)

    with tc2:
        st.markdown(f"""
        <div class="kpi-box {labor_color(avg_labor)}" style="padding:18px;border-radius:8px;text-align:center;">
          <div class="kpi-label">Avg Labor %</div>
          <div class="kpi-value" style="font-size:1.8rem;">{fmt_pct(avg_labor)}</div>
          <div class="kpi-sub">across all locations</div>
        </div>
        """, unsafe_allow_html=True)

    with tc3:
        st.markdown(f"""
        <div class="kpi-box {avg_check_color(avg_check_all)}" style="padding:18px;border-radius:8px;text-align:center;">
          <div class="kpi-label">Avg Check</div>
          <div class="kpi-value" style="font-size:1.8rem;">{fmt_cur(avg_check_all)}</div>
          <div class="kpi-sub">across all locations</div>
        </div>
        """, unsafe_allow_html=True)

    with tc4:
        delta_sign = "+" if (total_delta is not None and total_delta >= 0) else ""
        delta_str  = f"{delta_sign}{total_delta}" if total_delta is not None else "—"
        st.markdown(f"""
        <div class="kpi-box {checks_delta_color(total_delta)}" style="padding:18px;border-radius:8px;text-align:center;">
          <div class="kpi-label">Total Checks vs. Goal</div>
          <div class="kpi-value" style="font-size:1.8rem;">{delta_str}</div>
          <div class="kpi-sub">{total_trans} actual &nbsp;|&nbsp; {total_goal_trans or '—'} needed</div>
        </div>
        """, unsafe_allow_html=True)

    # ── Refresh ──
    st.markdown("<br>", unsafe_allow_html=True)
    _, rc, _ = st.columns([1, 1, 1])
    with rc:
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    # ── Footer ──
    st.markdown(f"""
    <div class="last-updated">
      Data auto-refreshes every 5 minutes &nbsp;|&nbsp;
      Daily scrape runs at 4:00 AM MST via GitHub Actions &nbsp;|&nbsp;
      Sources: Square API (Food Truck) + QU Beyond API (All Other Locations)
    </div>
    """, unsafe_allow_html=True)


if __name__ == "__main__":
    main()
