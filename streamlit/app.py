"""
LegalLens — Outside Counsel Intelligence Platform
==================================================
Streamlit dashboard connecting to Snowflake.
Tabs:
    1. Spend vs. Budget   — outside counsel spend by firm and practice area
    2. Matter Backlog     — open matter volume, age, and attorney workload
    3. Contract Risk      — expiry windows + Cortex sentiment flags
    4. Ask LegalLens      — Snowflake Cortex COMPLETE natural language Q&A

Setup:
    pip install streamlit snowflake-connector-python pandas plotly python-dotenv
    streamlit run app.py
"""

import os
import platform
import textwrap

# ── Patch: fix Snowflake connector bug on Windows Microsoft Store Python ──────
original_libc_ver = platform.libc_ver
def _safe_libc_ver(executable=None):
    try:
        return original_libc_ver(executable)
    except OSError:
        return ('', '')
platform.libc_ver = _safe_libc_ver

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import snowflake.connector
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# ── Page config ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="LegalLens",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Custom CSS ────────────────────────────────────────────────────────────────

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display:ital@0;1&family=DM+Sans:wght@300;400;500;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'DM Sans', sans-serif;
        font-size: 16px;
    }

    /* Larger base text throughout */
    p, li, span, div, label {
        font-size: 1rem;
    }

    /* Tab labels bigger */
    button[data-baseweb="tab"] {
        font-size: 1.05rem !important;
        font-weight: 500 !important;
    }

    /* Dataframe text */
    .stDataFrame td, .stDataFrame th {
        font-size: 0.95rem !important;
    }

    /* Multiselect tags */
    span[data-baseweb="tag"] {
        font-size: 0.9rem !important;
    }

    /* Header */
    .main-title {
        font-family: 'DM Serif Display', serif;
        font-size: 2.4rem;
        color: #0f1923;
        letter-spacing: -0.5px;
        margin-bottom: 0;
    }
    .main-subtitle {
        font-family: 'DM Sans', sans-serif;
        font-size: 0.95rem;
        color: #6b7280;
        font-weight: 300;
        margin-top: 2px;
    }

    /* KPI cards */
    .kpi-card {
        background: #ffffff;
        border: 1px solid #e5e7eb;
        border-radius: 10px;
        padding: 18px 22px;
        margin-bottom: 6px;
    }
    .kpi-label {
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        color: #9ca3af;
        margin-bottom: 4px;
    }
    .kpi-value {
        font-family: 'DM Serif Display', serif;
        font-size: 2rem;
        color: #0f1923;
        line-height: 1.1;
    }
    .kpi-delta-up   { color: #ef4444; font-size: 0.8rem; }
    .kpi-delta-down { color: #10b981; font-size: 0.8rem; }

    /* Status badges */
    .badge-over   { background: #fee2e2; color: #b91c1c; padding: 2px 8px; border-radius: 4px; font-size: 0.78rem; font-weight: 600; }
    .badge-risk   { background: #fef3c7; color: #92400e; padding: 2px 8px; border-radius: 4px; font-size: 0.78rem; font-weight: 600; }
    .badge-ok     { background: #d1fae5; color: #065f46; padding: 2px 8px; border-radius: 4px; font-size: 0.78rem; font-weight: 600; }
    .badge-under  { background: #dbeafe; color: #1e40af; padding: 2px 8px; border-radius: 4px; font-size: 0.78rem; font-weight: 600; }

    /* Cortex answer box */
    .cortex-answer {
        background: #f8fafc;
        border-left: 4px solid #6366f1;
        border-radius: 0 8px 8px 0;
        padding: 18px 22px;
        font-size: 1rem;
        color: #1e293b;
        line-height: 1.65;
        margin-top: 12px;
    }

    /* Tab summary insight box */
    .summary-box {
        background: #f0f9ff;
        border: 1px solid #bae6fd;
        border-left: 4px solid #0284c7;
        border-radius: 0 8px 8px 0;
        padding: 14px 20px;
        margin: 12px 0 20px 0;
        font-size: 1rem;
        color: #0c4a6e;
        line-height: 1.7;
    }
    .summary-box strong {
        color: #0369a1;
        font-weight: 600;
    }
    .summary-box.warn {
        background: #fff7ed;
        border-color: #fed7aa;
        border-left-color: #ea580c;
        color: #7c2d12;
    }
    .summary-box.warn strong {
        color: #c2410c;
    }

    /* Sidebar */
    section[data-testid="stSidebar"] {
        background: #0f1923;
    }
    section[data-testid="stSidebar"] * {
        color: #e5e7eb !important;
    }

    div[data-testid="stMetricValue"] {
        font-family: 'DM Serif Display', serif;
    }
</style>
""", unsafe_allow_html=True)


# ── Snowflake connection ───────────────────────────────────────────────────────

@st.cache_resource(show_spinner=False)
def get_connection():
    # Use Streamlit secrets when deployed, .env locally
    try:
        creds = st.secrets["snowflake"]
        return snowflake.connector.connect(
            account=creds["account"],
            user=creds["user"],
            password=creds["password"],
            warehouse=creds.get("warehouse", "LEGALLENS_WH"),
            database="LEGALLENS_DB",
            schema="STAGING_MARTS",
        )
    except (KeyError, FileNotFoundError):
        return snowflake.connector.connect(
            account=os.environ["SNOWFLAKE_ACCOUNT"],
            user=os.environ["SNOWFLAKE_USER"],
            password=os.environ["SNOWFLAKE_PASSWORD"],
            warehouse=os.environ.get("SNOWFLAKE_WAREHOUSE", "LEGALLENS_WH"),
            database="LEGALLENS_DB",
            schema="STAGING_MARTS",
        )


@st.cache_data(ttl=300, show_spinner=False)
def query(_conn, sql):
    cur = _conn.cursor()
    cur.execute(sql)
    rows = cur.fetchall()
    cols = [d[0].upper() for d in cur.description]
    cur.close()
    return pd.DataFrame(rows, columns=cols)


# ── Helpers ───────────────────────────────────────────────────────────────────

def fmt_currency(val):
    if val >= 1_000_000:
        return f"${val/1_000_000:.1f}M"
    elif val >= 1_000:
        return f"${val/1_000:.0f}K"
    return f"${val:.0f}"


STATUS_COLORS = {
    "Over Budget":  "#ef4444",
    "At Risk":      "#f59e0b",
    "On Track":     "#10b981",
    "Under Budget": "#3b82f6",
}

EXPIRY_COLORS = {
    "Expired":           "#7f1d1d",
    "Critical (< 30 days)": "#ef4444",
    "High (30-60 days)": "#f59e0b",
    "Medium (60-90 days)": "#fbbf24",
    "Low (> 90 days)":   "#10b981",
}


# ── Header ────────────────────────────────────────────────────────────────────

col_logo, col_title = st.columns([1, 11])
with col_logo:
    st.markdown("<div style='font-size:2.8rem;margin-top:8px'>⚖️</div>", unsafe_allow_html=True)
with col_title:
    st.markdown('<p class="main-title">LegalLens</p>', unsafe_allow_html=True)
    st.markdown('<p class="main-subtitle">Outside Counsel Intelligence Platform &nbsp;·&nbsp; Powered by Snowflake Cortex</p>', unsafe_allow_html=True)

st.markdown("<hr style='border:none;border-top:1px solid #e5e7eb;margin:10px 0 20px 0'>", unsafe_allow_html=True)


# ── Sidebar filters ───────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ⚙️ Filters")
    st.markdown("---")

    conn = get_connection()

    practice_areas = query(conn, "SELECT DISTINCT practice_area FROM LEGALLENS_DB.STAGING_MARTS.fct_outside_counsel_spend ORDER BY 1")["PRACTICE_AREA"].tolist()
    selected_areas = st.multiselect("Practice Area", options=practice_areas, default=practice_areas)

    vendors = query(conn, "SELECT DISTINCT vendor FROM LEGALLENS_DB.STAGING_MARTS.fct_outside_counsel_spend ORDER BY 1")["VENDOR"].tolist()
    selected_vendors = st.multiselect("Law Firm", options=vendors, default=vendors)

    st.markdown("---")
    st.markdown("**Data freshness**")
    freshness = query(conn, "SELECT CURRENT_DATE as last_loaded")
    st.caption(f"Last loaded: {freshness['LAST_LOADED'].iloc[0]}")

    st.markdown("---")
    st.markdown(
        "<div style='font-size:0.72rem;color:#6b7280;line-height:1.5'>"
        "Access governed by Snowflake row-level security policies. "
        "Sensitive billing data restricted to authorized practice areas only."
        "</div>",
        unsafe_allow_html=True,
    )

area_filter = f"({', '.join(repr(a) for a in selected_areas)})" if selected_areas else "('')"
vendor_filter = f"({', '.join(repr(v) for v in selected_vendors)})" if selected_vendors else "('')"


# ── Tabs ──────────────────────────────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    "💰 Spend vs. Budget",
    "📋 Matter Backlog",
    "📄 Contract Risk",
    "🤖 Ask LegalLens",
])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — Spend vs. Budget
# ═══════════════════════════════════════════════════════════════════════════════

with tab1:
    spend_df = query(conn, f"""
        SELECT vendor, practice_area, invoice_count, matter_count,
               total_spend, total_budget, total_budget_variance,
               over_budget_invoice_count, pct_invoices_over_budget,
               disputed_invoice_count, disputed_amount, avg_spend_per_matter,
               latest_invoice_date, spend_budget_ratio, budget_status,
               spend_rank_in_practice_area
        FROM LEGALLENS_DB.STAGING_MARTS.fct_outside_counsel_spend
        WHERE practice_area IN {area_filter}
          AND vendor IN {vendor_filter}
        ORDER BY total_spend DESC
    """)

    if spend_df.empty:
        st.warning("No spend data for current filters.")
    else:
        # KPI row
        total_spend  = spend_df["TOTAL_SPEND"].sum()
        total_budget = spend_df["TOTAL_BUDGET"].sum()
        over_budget  = (spend_df["BUDGET_STATUS"] == "Over Budget").sum()
        disputed     = spend_df["DISPUTED_AMOUNT"].sum()

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Spend",        fmt_currency(total_spend))
        k2.metric("Total Budget",       fmt_currency(total_budget))
        k3.metric("Firms Over Budget",  f"{over_budget} firms",
                  delta=f"↑ {over_budget}" if over_budget > 0 else "✓ None",
                  delta_color="inverse")
        k4.metric("Disputed Amount",    fmt_currency(disputed))

        # Summary insight
        top_firm = spend_df.loc[spend_df["TOTAL_SPEND"].idxmax(), "VENDOR"] if not spend_df.empty else "N/A"
        over_pct = round(100 * over_budget / len(spend_df), 0) if len(spend_df) > 0 else 0
        box_class = "summary-box warn" if over_budget > 3 else "summary-box"
        st.markdown(f"""
        <div class="{box_class}">
            <strong>📊 Spend Summary:</strong> Total outside counsel spend is <strong>{fmt_currency(total_spend)}</strong>
            against a budget of <strong>{fmt_currency(total_budget)}</strong>.
            <strong>{over_budget} firm(s) ({int(over_pct)}%)</strong> are over budget.
            Highest spend firm: <strong>{top_firm}</strong>.
            Disputed invoices total <strong>{fmt_currency(disputed)}</strong> and require review.
        </div>
        """, unsafe_allow_html=True)
        col_left, col_right = st.columns([3, 2])

        with col_left:
            st.markdown("#### Outside Counsel Spend vs. Budget by Firm")
            firm_summary = (
                spend_df.groupby("VENDOR")
                .agg(total_spend=("TOTAL_SPEND", "sum"),
                     total_budget=("TOTAL_BUDGET", "sum"))
                .reset_index()
                .sort_values("total_spend", ascending=True)
            )
            firm_summary["variance_pct"] = (
                (firm_summary["total_spend"] / firm_summary["total_budget"]) - 1
            ) * 100

            fig = go.Figure()
            fig.add_bar(
                y=firm_summary["VENDOR"],
                x=firm_summary["total_budget"],
                name="Budget",
                orientation="h",
                marker_color="#e5e7eb",
            )
            fig.add_bar(
                y=firm_summary["VENDOR"],
                x=firm_summary["total_spend"],
                name="Actual Spend",
                orientation="h",
                marker_color=[
                    "#ef4444" if v > 0 else "#10b981"
                    for v in firm_summary["variance_pct"]
                ],
            )
            fig.update_layout(
                barmode="overlay",
                height=420,
                margin=dict(l=0, r=0, t=0, b=0),
                legend=dict(orientation="h", y=1.05),
                xaxis_title="USD",
                plot_bgcolor="#ffffff",
                paper_bgcolor="#ffffff",
                font=dict(family="DM Sans"),
            )
            st.plotly_chart(fig, use_container_width=True)

        with col_right:
            st.markdown("#### Budget Status Breakdown")
            status_counts = spend_df["BUDGET_STATUS"].value_counts().reset_index()
            status_counts.columns = ["status", "count"]
            fig2 = px.pie(
                status_counts,
                values="count",
                names="status",
                color="status",
                color_discrete_map=STATUS_COLORS,
                hole=0.55,
            )
            fig2.update_layout(
                height=280,
                margin=dict(l=0, r=0, t=0, b=0),
                showlegend=True,
                legend=dict(orientation="v"),
                paper_bgcolor="#ffffff",
                font=dict(family="DM Sans"),
            )
            st.plotly_chart(fig2, use_container_width=True)

            st.markdown("#### Spend by Practice Area")
            area_summary = (
                spend_df.groupby("PRACTICE_AREA")["TOTAL_SPEND"]
                .sum()
                .sort_values(ascending=False)
                .reset_index()
            )
            area_summary.columns = ["Practice Area", "Total Spend"]
            area_summary["Total Spend"] = area_summary["Total Spend"].apply(fmt_currency)
            st.dataframe(area_summary, hide_index=True, use_container_width=True)

        # Detailed table
        st.markdown("#### Full Breakdown")
        display_cols = {
            "VENDOR": "Law Firm",
            "PRACTICE_AREA": "Practice Area",
            "TOTAL_SPEND": "Spend",
            "TOTAL_BUDGET": "Budget",
            "BUDGET_STATUS": "Status",
            "PCT_INVOICES_OVER_BUDGET": "% Over Budget",
            "DISPUTED_AMOUNT": "Disputed",
            "MATTER_COUNT": "Matters",
        }
        tbl = spend_df[list(display_cols.keys())].copy()
        tbl.rename(columns=display_cols, inplace=True)
        tbl["Spend"]    = tbl["Spend"].apply(fmt_currency)
        tbl["Budget"]   = tbl["Budget"].apply(fmt_currency)
        tbl["Disputed"] = tbl["Disputed"].apply(fmt_currency)
        st.dataframe(tbl, hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — Matter Backlog
# ═══════════════════════════════════════════════════════════════════════════════

with tab2:
    backlog_df = query(conn, f"""
        SELECT practice_area, status, priority, lead_attorney,
               matter_count, active_matter_count,
               matters_over_1yr, matters_6mo_to_1yr, matters_under_6mo,
               avg_days_open, max_days_open, total_invoiced,
               avg_invoiced_per_matter, workload_score, flag_stale, is_active
        FROM LEGALLENS_DB.STAGING_MARTS.fct_matter_backlog
        WHERE practice_area IN {area_filter}
        ORDER BY workload_score DESC
    """)

    if backlog_df.empty:
        st.warning("No backlog data for current filters.")
    else:
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Total Active Matters",  int(backlog_df["ACTIVE_MATTER_COUNT"].sum()))
        k2.metric("Avg Days Open",         int(backlog_df["AVG_DAYS_OPEN"].mean()))
        k3.metric("Matters > 1 Year",      int(backlog_df["MATTERS_OVER_1YR"].sum()),
                  delta_color="inverse")
        k4.metric("Flagged Stale",         int(backlog_df["FLAG_STALE"].sum()),
                  delta_color="inverse")

        # Summary insight
        busiest_area = backlog_df.groupby("PRACTICE_AREA")["ACTIVE_MATTER_COUNT"].sum().idxmax() if not backlog_df.empty else "N/A"
        busiest_atty = backlog_df.groupby("LEAD_ATTORNEY")["WORKLOAD_SCORE"].sum().idxmax() if not backlog_df.empty else "N/A"
        stale_count  = int(backlog_df["FLAG_STALE"].sum())
        avg_age      = int(backlog_df["AVG_DAYS_OPEN"].mean()) if not backlog_df.empty else 0
        box_class    = "summary-box warn" if stale_count > 5 else "summary-box"
        st.markdown(f"""
        <div class="{box_class}">
            <strong>📋 Backlog Summary:</strong> <strong>{int(backlog_df["ACTIVE_MATTER_COUNT"].sum())} active matters</strong>
            with an average age of <strong>{avg_age} days</strong>.
            Busiest practice area: <strong>{busiest_area}</strong>.
            Most loaded attorney: <strong>{busiest_atty}</strong>.
            <strong>{stale_count} matter(s)</strong> flagged as stale (open &gt; 270 days) — recommend partner review.
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")
        col_l, col_r = st.columns([2, 3])

        with col_l:
            st.markdown("#### Open Matters by Practice Area")
            by_area = (
                backlog_df.groupby("PRACTICE_AREA")
                .agg(active=("ACTIVE_MATTER_COUNT", "sum"),
                     avg_age=("AVG_DAYS_OPEN", "mean"))
                .reset_index()
                .sort_values("active", ascending=False)
            )
            fig3 = px.bar(
                by_area,
                x="PRACTICE_AREA",
                y="active",
                color="avg_age",
                color_continuous_scale=["#10b981", "#f59e0b", "#ef4444"],
                labels={"active": "Active Matters", "avg_age": "Avg Days Open", "PRACTICE_AREA": ""},
            )
            fig3.update_layout(
                height=320,
                margin=dict(l=0, r=0, t=0, b=0),
                coloraxis_colorbar=dict(title="Avg Days"),
                plot_bgcolor="#ffffff",
                paper_bgcolor="#ffffff",
                font=dict(family="DM Sans"),
            )
            st.plotly_chart(fig3, use_container_width=True)

        with col_r:
            st.markdown("#### Attorney Workload Score")
            atty = (
                backlog_df.groupby("LEAD_ATTORNEY")
                .agg(
                    workload=("WORKLOAD_SCORE", "sum"),
                    active=("ACTIVE_MATTER_COUNT", "sum"),
                    avg_age=("AVG_DAYS_OPEN", "mean"),
                )
                .reset_index()
                .sort_values("workload", ascending=True)
            )
            fig4 = px.bar(
                atty,
                y="LEAD_ATTORNEY",
                x="workload",
                orientation="h",
                color="avg_age",
                color_continuous_scale=["#10b981", "#f59e0b", "#ef4444"],
                labels={"workload": "Workload Score", "avg_age": "Avg Days Open", "LEAD_ATTORNEY": ""},
            )
            fig4.update_layout(
                height=320,
                margin=dict(l=0, r=0, t=0, b=0),
                plot_bgcolor="#ffffff",
                paper_bgcolor="#ffffff",
                font=dict(family="DM Sans"),
            )
            st.plotly_chart(fig4, use_container_width=True)

        # Age distribution heatmap
        st.markdown("#### Matter Age Distribution by Practice Area")
        age_df = backlog_df.groupby("PRACTICE_AREA").agg(
            under_6mo=("MATTERS_UNDER_6MO", "sum"),
            six_to_1yr=("MATTERS_6MO_TO_1YR", "sum"),
            over_1yr=("MATTERS_OVER_1YR", "sum"),
        ).reset_index()

        fig5 = go.Figure(data=go.Heatmap(
            z=[age_df["under_6mo"], age_df["six_to_1yr"], age_df["over_1yr"]],
            x=age_df["PRACTICE_AREA"],
            y=["< 6 months", "6mo to 1yr", "> 1 year"],
            colorscale=[[0, "#f0fdf4"], [0.5, "#fef9c3"], [1, "#fef2f2"]],
            text=[age_df["under_6mo"], age_df["six_to_1yr"], age_df["over_1yr"]],
            texttemplate="%{text}",
            showscale=False,
        ))
        fig5.update_layout(
            height=200,
            margin=dict(l=0, r=0, t=0, b=0),
            paper_bgcolor="#ffffff",
            font=dict(family="DM Sans"),
        )
        st.plotly_chart(fig5, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — Contract Risk
# ═══════════════════════════════════════════════════════════════════════════════

with tab3:
    contracts_df = query(conn, f"""
        SELECT contract_id, vendor, practice_area,
               start_date, end_date, annual_value, renewal_flag, notes,
               days_until_expiry, expiry_risk,
               notes_sentiment_score, flag_for_gc_review
        FROM LEGALLENS_DB.STAGING_STAGING.stg_contracts
        WHERE vendor IN {vendor_filter}
        ORDER BY days_until_expiry ASC
    """)

    if contracts_df.empty:
        st.warning("No contract data for current filters.")
    else:
        expiring_30  = (contracts_df["EXPIRY_RISK"] == "Critical (< 30 days)").sum()
        expiring_60  = (contracts_df["EXPIRY_RISK"] == "High (30-60 days)").sum()
        flagged_gc   = contracts_df["FLAG_FOR_GC_REVIEW"].sum()
        no_renewal   = (contracts_df["RENEWAL_FLAG"] == "NO").sum()

        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Expiring < 30 Days",  expiring_30,  delta_color="inverse")
        k2.metric("Expiring 30-60 Days", expiring_60,  delta_color="inverse")
        k3.metric("Flagged for GC Review", int(flagged_gc), delta_color="inverse")
        k4.metric("No Renewal Signal",   no_renewal,   delta_color="inverse")

        # Summary insight
        critical_firms = contracts_df[contracts_df["EXPIRY_RISK"] == "Critical (< 30 days)"]["VENDOR"].unique().tolist()
        neg_sentiment  = contracts_df[contracts_df["FLAG_FOR_GC_REVIEW"] == True]["VENDOR"].unique().tolist()
        critical_str   = ", ".join(critical_firms[:3]) + (" +more" if len(critical_firms) > 3 else "") if critical_firms else "None"
        neg_str        = ", ".join(neg_sentiment[:3]) + (" +more" if len(neg_sentiment) > 3 else "") if neg_sentiment else "None"
        box_class      = "summary-box warn" if expiring_30 > 0 else "summary-box"
        st.markdown(f"""
        <div class="{box_class}">
            <strong>📄 Contract Risk Summary:</strong>
            <strong>{expiring_30} contract(s)</strong> expiring in &lt;30 days — firms: <strong>{critical_str}</strong>.
            <strong>{expiring_60}</strong> more expiring in 30–60 days.
            <strong>{int(flagged_gc)} contract(s)</strong> flagged for GC review based on negative Cortex sentiment — firms: <strong>{neg_str}</strong>.
            <strong>{no_renewal}</strong> active contracts have no renewal signal.
        </div>
        """, unsafe_allow_html=True)

        st.markdown("---")
        col_l, col_r = st.columns([2, 3])

        with col_l:
            st.markdown("#### Expiry Risk Distribution")
            risk_counts = contracts_df["EXPIRY_RISK"].value_counts().reset_index()
            risk_counts.columns = ["risk", "count"]
            fig6 = px.pie(
                risk_counts,
                values="count",
                names="risk",
                color="risk",
                color_discrete_map=EXPIRY_COLORS,
                hole=0.5,
            )
            fig6.update_layout(
                height=280,
                margin=dict(l=0, r=0, t=0, b=0),
                paper_bgcolor="#ffffff",
                font=dict(family="DM Sans"),
            )
            st.plotly_chart(fig6, use_container_width=True)

        with col_r:
            st.markdown("#### Cortex Sentiment Score by Vendor")
            sentiment_df = (
                contracts_df.groupby("VENDOR")
                .agg(avg_sentiment=("NOTES_SENTIMENT_SCORE", "mean"),
                     flagged=("FLAG_FOR_GC_REVIEW", "sum"))
                .reset_index()
                .sort_values("avg_sentiment")
            )
            fig7 = px.bar(
                sentiment_df,
                y="VENDOR",
                x="avg_sentiment",
                orientation="h",
                color="avg_sentiment",
                color_continuous_scale=["#ef4444", "#fef9c3", "#10b981"],
                range_color=[-1, 1],
                labels={"avg_sentiment": "Avg Sentiment Score", "VENDOR": ""},
            )
            fig7.add_vline(x=0, line_dash="dash", line_color="#9ca3af")
            fig7.update_layout(
                height=280,
                margin=dict(l=0, r=0, t=0, b=0),
                plot_bgcolor="#ffffff",
                paper_bgcolor="#ffffff",
                font=dict(family="DM Sans"),
                coloraxis_showscale=False,
            )
            st.plotly_chart(fig7, use_container_width=True)

        # Critical contracts table
        st.markdown("#### Contracts Requiring Immediate Attention")
        critical = contracts_df[
            contracts_df["EXPIRY_RISK"].isin(["Critical (< 30 days)", "Expired"])
            | (contracts_df["FLAG_FOR_GC_REVIEW"] == True)
        ].copy()

        if critical.empty:
            st.success("No contracts requiring immediate attention.")
        else:
            display = critical[[
                "VENDOR", "PRACTICE_AREA", "END_DATE",
                "DAYS_UNTIL_EXPIRY", "EXPIRY_RISK",
                "RENEWAL_FLAG", "NOTES_SENTIMENT_SCORE", "FLAG_FOR_GC_REVIEW",
            ]].copy()
            display["NOTES_SENTIMENT_SCORE"] = display["NOTES_SENTIMENT_SCORE"].round(3)
            display["FLAG_FOR_GC_REVIEW"] = display["FLAG_FOR_GC_REVIEW"].map({True: "🚨 Yes", False: "—"})
            display.columns = [
                "Firm", "Practice Area", "Expiry Date",
                "Days Until Expiry", "Risk Level",
                "Auto-Renew", "Sentiment Score", "GC Flag",
            ]
            st.dataframe(display, hide_index=True, use_container_width=True)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — Ask LegalLens (Snowflake Cortex COMPLETE)
# ═══════════════════════════════════════════════════════════════════════════════

with tab4:
    st.markdown("#### 🤖 Ask LegalLens — AI-Powered Q&A on Your Legal Operations Data")
    st.caption(
        "Powered by Snowflake Cortex COMPLETE (mistral-large). "
        "Ask questions in plain English — LegalLens pulls live data from Snowflake and answers with grounded facts."
    )

    EXAMPLE_QUESTIONS = [
        "Which law firms are over budget and by how much?",
        "Which practice area has the highest average matter age?",
        "Which firms have contracts expiring in the next 30 days with no renewal signal?",
        "Who are the most overloaded attorneys right now?",
        "Which firms have negative contract sentiment scores?",
        "How does M&A spend compare to Litigation spend?",
        "Flag any outside counsel where both spend and sentiment are negative signals.",
    ]

    st.markdown("**Try an example:**")
    cols = st.columns(3)
    prefill = ""
    for i, q in enumerate(EXAMPLE_QUESTIONS[:6]):
        if cols[i % 3].button(q, key=f"eg_{i}", use_container_width=True):
            prefill = q

    user_question = st.text_input(
        "Your question:",
        value=prefill,
        placeholder="Which firms are over budget across all practice areas?",
    )

    if st.button("Ask LegalLens ⚡", type="primary") and user_question:
        with st.spinner("Querying Snowflake Cortex..."):

            # Pull relevant context from the mart tables
            context_spend = query(conn, """
                SELECT vendor, practice_area, total_spend, total_budget,
                       budget_status, pct_invoices_over_budget, disputed_amount,
                       matter_count, avg_spend_per_matter
                FROM LEGALLENS_DB.STAGING_MARTS.fct_outside_counsel_spend
                ORDER BY total_spend DESC
                LIMIT 50
            """).to_string(index=False)

            context_backlog = query(conn, """
                SELECT practice_area, lead_attorney, active_matter_count,
                       avg_days_open, matters_over_1yr, workload_score, flag_stale
                FROM LEGALLENS_DB.STAGING_MARTS.fct_matter_backlog
                WHERE is_active = TRUE OR status = 'Open'
                ORDER BY workload_score DESC
                LIMIT 30
            """).to_string(index=False)

            context_contracts = query(conn, """
                SELECT vendor, practice_area, end_date, days_until_expiry,
                       expiry_risk, renewal_flag, notes_sentiment_score, flag_for_gc_review
                FROM LEGALLENS_DB.STAGING_STAGING.stg_contracts
                ORDER BY days_until_expiry ASC
                LIMIT 30
            """).to_string(index=False)

            # Build the prompt
            prompt = textwrap.dedent(f"""
                You are LegalLens, an AI analyst embedded in a Legal Operations intelligence platform.
                You have access to real-time data from Snowflake about outside counsel spend,
                matter backlogs, and contract risk.

                Answer the user's question using ONLY the data provided below.
                Be specific with numbers. If a firm or attorney is flagged, say why.
                Format your answer clearly with bullet points where appropriate.
                Do not make up data that is not in the context.

                === OUTSIDE COUNSEL SPEND DATA ===
                {context_spend}

                === MATTER BACKLOG DATA ===
                {context_backlog}

                === CONTRACT RISK DATA ===
                {context_contracts}

                === USER QUESTION ===
                {user_question}

                === YOUR ANSWER ===
            """).strip()

            # Call Snowflake Cortex COMPLETE
            # Use parameterised cursor to avoid escaping issues with apostrophes in data
            cortex_sql = """
                SELECT SNOWFLAKE.CORTEX.COMPLETE(
                    'mistral-large',
                    %s
                ) AS answer
            """

            try:
                cur = conn.cursor()
                cur.execute(cortex_sql, (prompt,))
                answer = cur.fetchone()[0]
                cur.close()
                st.markdown(
                    f'<div class="cortex-answer">{answer}</div>',
                    unsafe_allow_html=True,
                )
                st.caption("⚠️ LegalLens answers are grounded in your Snowflake data but should be reviewed before acting on.")
            except Exception as e:
                st.error(f"Cortex query failed: {e}")
                st.info(
                    "Make sure your Snowflake region supports Cortex COMPLETE "
                    "and that the LEGALLENS_WH warehouse is running."
                )

    st.markdown("---")
    with st.expander("🔒 Data Access & Security Architecture"):
        st.markdown("""
        **Row-Level Security** is enforced at the Snowflake layer, not the application layer.
        The following policies are active:

        | Policy | Description |
        |--------|-------------|
        | `practice_area_rls_policy` | Employment counsel only sees Employment matters |
        | `invoice_secure_view` | Billing amounts masked for read-only analyst role |
        | `contract_notes_policy` | Contract notes restricted to GC and above |

        Access is controlled via Snowflake roles (`LEGALLENS_GC_ROLE`, `LEGALLENS_ANALYST_ROLE`,
        `LEGALLENS_READONLY_ROLE`). This dashboard connects as `LEGALLENS_GC_ROLE` by default.

        See `setup_access_controls.sql` for full policy definitions.
        """)
