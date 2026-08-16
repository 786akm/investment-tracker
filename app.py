import datetime
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from db import (
    get_client, init_schema, fetch_all_data, upsert_entry, add_contribution,
    get_or_create_fund, log_backup, last_backup_time,
)

st.set_page_config(page_title="Unit Trust Portfolio Tracker", layout="wide")

# ---------- data helpers ----------

@st.cache_resource
def _client():
    c = get_client()
    init_schema(c)
    return c

@st.cache_data(ttl=30)
def load_data():
    return fetch_all_data(_client())

def fund_cost_basis_at(fund, date):
    basis = fund["costBasis"] or 0
    for c in fund.get("contributions", []):
        if c["date"] <= date:
            basis += c["amount"]
    return basis

def account_cost_basis_at(account, date):
    if account["funds"]:
        return sum(fund_cost_basis_at(f, date) for f in account["funds"])
    return account["costBasis"] or 0

def merge_valued_series(series_list):
    """series_list: list of [{date,value,cost}, ...] (each already sorted).
    Forward-fills each series and sums value/cost across all of them per date."""
    all_dates = sorted({p["date"] for s in series_list for p in s})
    out = []
    for d in all_dates:
        total, cost, any_ = 0.0, 0.0, False
        for s in series_list:
            last = None
            for p in s:
                if p["date"] <= d:
                    last = p
                else:
                    break
            if last:
                total += last["value"]
                cost += last["cost"]
                any_ = True
        if any_:
            out.append({"date": d, "value": total, "cost": cost})
    return out

def fund_series(fund):
    pts = sorted(fund["series"], key=lambda p: p["date"])
    return [{"date": p["date"], "value": p["value"], "cost": fund_cost_basis_at(fund, p["date"])} for p in pts]

def account_series(acc):
    if acc["funds"]:
        return merge_valued_series([fund_series(f) for f in acc["funds"]])
    pts = sorted(acc["totalSeries"], key=lambda p: p["date"])
    return [{"date": p["date"], "value": p["value"], "cost": account_cost_basis_at(acc, p["date"])} for p in pts]

RANGES = {"1W": 7, "1M": 30, "3M": 90, "1Y": 365, "YTD": None, "All": None}

def filter_range(series, key):
    if not series:
        return series
    last_date = datetime.date.fromisoformat(series[-1]["date"])
    if key == "All":
        return series
    if key == "YTD":
        cutoff = datetime.date(last_date.year, 1, 1)
    else:
        cutoff = last_date - datetime.timedelta(days=RANGES[key])
    return [p for p in series if datetime.date.fromisoformat(p["date"]) >= cutoff]

def rm(n):
    return f"RM {n:,.0f}"

def pct(n):
    sign = "+" if n >= 0 else ""
    return f"{sign}{n:.1f}%"

# ---------- sidebar navigation ----------

data = load_data()

if "sel" not in st.session_state:
    st.session_state.sel = {"level": "overview"}

st.sidebar.title("Portfolio tracker")
page = st.sidebar.radio("Page", ["Dashboard", "Weekly entry"], label_visibility="collapsed")

if page == "Dashboard":
    if st.sidebar.button("🏠 All agencies", use_container_width=True):
        st.session_state.sel = {"level": "overview"}
    for ai, agency in enumerate(data["agencies"]):
        with st.sidebar.expander(agency["name"], expanded=False):
            if st.button("This agency — overview", key=f"ag{ai}"):
                st.session_state.sel = {"level": "agency", "a": ai}
            for bi, acc in enumerate(agency["accounts"]):
                if st.button(f"📁 {acc['name']}", key=f"acc{ai}_{bi}"):
                    st.session_state.sel = {"level": "account", "a": ai, "b": bi}
                for ci, fund in enumerate(acc["funds"]):
                    if st.button(f"    · {fund['name']}", key=f"fund{ai}_{bi}_{ci}"):
                        st.session_state.sel = {"level": "fund", "a": ai, "b": bi, "c": ci}

# ---------- dashboard page ----------

if page == "Dashboard":
    sel = st.session_state.sel

    if sel["level"] == "overview":
        parts = [account_series(acc) for ag in data["agencies"] for acc in ag["accounts"]]
        title, crumb = "All agencies", "Overview"
    elif sel["level"] == "agency":
        ag = data["agencies"][sel["a"]]
        parts = [account_series(acc) for acc in ag["accounts"]]
        title, crumb = ag["name"], f"Overview / {ag['name']}"
    elif sel["level"] == "account":
        ag = data["agencies"][sel["a"]]; acc = ag["accounts"][sel["b"]]
        parts = [account_series(acc)]
        title, crumb = acc["name"], f"Overview / {ag['name']} / {acc['name']}"
    else:
        ag = data["agencies"][sel["a"]]; acc = ag["accounts"][sel["b"]]; fund = acc["funds"][sel["c"]]
        parts = [fund_series(fund)]
        title, crumb = fund["name"], f"Overview / {ag['name']} / {acc['name']} / {fund['name']}"

    full_series = merge_valued_series(parts)

    st.caption(crumb)
    st.subheader(title)

    range_key = st.radio("Time range", list(RANGES.keys()), index=5, horizontal=True, label_visibility="collapsed")
    series = filter_range(full_series, range_key)

    if series:
        last, first = series[-1], series[0]
        total_gain = last["value"] - last["cost"]
        total_gain_pct = (total_gain / last["cost"] * 100) if last["cost"] else 0
        period_change = last["value"] - first["value"]
        period_change_pct = (period_change / first["value"] * 100) if first["value"] else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Invested", rm(last["cost"]))
        c2.metric("Current value", rm(last["value"]))
        c3.metric("Gain since start", rm(total_gain), pct(total_gain_pct))
        c4.metric(f"Change ({range_key})", rm(period_change), pct(period_change_pct))

        df = pd.DataFrame(series)
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df["date"], y=df["value"], name="Market value",
                                  line=dict(color="#4f8cff", width=2), fill="tozeroy",
                                  fillcolor="rgba(79,140,255,0.08)"))
        fig.add_trace(go.Scatter(x=df["date"], y=df["cost"], name="Invested (cost basis)",
                                  line=dict(color="#6b7280", width=1.5, dash="dash")))
        fig.update_layout(height=340, margin=dict(l=10, r=10, t=10, b=10),
                           paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                           font_color="#e8eaed", legend=dict(orientation="h", y=1.1),
                           yaxis=dict(gridcolor="#23262f"), xaxis=dict(gridcolor="#23262f"))
        st.plotly_chart(fig, use_container_width=True)

        # breakdown of children
        breakdown_items = []
        if sel["level"] == "overview":
            for ag in data["agencies"]:
                s = filter_range(merge_valued_series([account_series(a) for a in ag["accounts"]]), range_key)
                if s: breakdown_items.append((ag["name"], s))
            heading = "By agency"
        elif sel["level"] == "agency":
            ag = data["agencies"][sel["a"]]
            for acc in ag["accounts"]:
                s = filter_range(account_series(acc), range_key)
                if s: breakdown_items.append((acc["name"], s))
            heading = f"Accounts in {ag['name']}"
        elif sel["level"] == "account":
            acc = data["agencies"][sel["a"]]["accounts"][sel["b"]]
            for fund in acc["funds"]:
                s = filter_range(fund_series(fund), range_key)
                if s: breakdown_items.append((fund["name"], s))
            heading = f"Funds in {acc['name']}" if acc["funds"] else None
        else:
            heading = None

        if breakdown_items and heading:
            st.markdown(f"**{heading} · change over {range_key}**")
            rows = []
            for name, s in breakdown_items:
                l, f = s[-1], s[0]
                chg_pct = (l["value"] - f["value"]) / f["value"] * 100 if f["value"] else 0
                rows.append({"Name": name, "Invested": rm(l["cost"]), "Value": rm(l["value"]),
                             f"Change ({range_key})": pct(chg_pct)})
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

        st.markdown("**History**")
        table_df = pd.DataFrame(series[::-1]).rename(columns={"date": "Date", "cost": "Invested", "value": "Value"})
        table_df["Invested"] = table_df["Invested"].map(rm)
        table_df["Value"] = table_df["Value"].map(rm)
        st.dataframe(table_df, use_container_width=True, hide_index=True)
    else:
        st.info("No data yet for this selection.")

# ---------- weekly entry page ----------

else:
    st.subheader("Weekly entry")

    last_bk = last_backup_time(_client())
    show_reminder = True
    if last_bk:
        days_since = (datetime.datetime.utcnow() - datetime.datetime.fromisoformat(last_bk)).days
        show_reminder = days_since >= 8
    if show_reminder:
        st.warning("It's been a while since your last backup download. Remember to back up after saving today.")

    entry_date = st.date_input("Date", value=datetime.date.today())

    st.markdown("Enter the **current value** for each fund you're updating today. Leave blank to skip.")

    values = {}
    for ai, agency in enumerate(data["agencies"]):
        st.markdown(f"#### {agency['name']}")
        for acc in agency["accounts"]:
            if acc["funds"]:
                st.markdown(f"**{acc['name']}**")
                cols = st.columns(2)
                for i, fund in enumerate(acc["funds"]):
                    with cols[i % 2]:
                        v = st.number_input(fund["name"], min_value=0.0, step=100.0,
                                             key=f"val_{fund['id']}", value=0.0)
                        if v > 0:
                            values[("fund", fund["id"])] = v
            else:
                v = st.number_input(f"{acc['name']} (total)", min_value=0.0, step=100.0,
                                     key=f"val_acc_{acc['id']}", value=0.0)
                if v > 0:
                    values[("account", acc["id"])] = v

    st.markdown("---")
    st.markdown("**Did you top up any fund today?** (log separately so it doesn't distort your gain %)")
    contrib_col1, contrib_col2, contrib_col3 = st.columns(3)
    all_funds = [(f["id"], f"{ag['name']} / {acc['name']} / {f['name']}")
                 for ag in data["agencies"] for acc in ag["accounts"] for f in acc["funds"]]
    with contrib_col1:
        contrib_fund = st.selectbox("Fund", ["(none)"] + [n for _, n in all_funds])
    with contrib_col2:
        contrib_amount = st.number_input("Additional amount (RM)", min_value=0.0, step=100.0, value=0.0)
    with contrib_col3:
        contrib_note = st.text_input("Note (optional)")

    if st.button("Save today's entry", type="primary"):
        client = _client()
        for (etype, eid), v in values.items():
            upsert_entry(client, etype, eid, entry_date.isoformat(), v)
        if contrib_fund != "(none)" and contrib_amount > 0:
            fund_id = next(fid for fid, n in all_funds if n == contrib_fund)
            add_contribution(client, fund_id, entry_date.isoformat(), contrib_amount, contrib_note or None)
        load_data.clear()
        st.success(f"Saved {len(values)} fund value(s) for {entry_date.isoformat()}.")

    st.markdown("---")
    st.markdown("**Backup**")
    if st.button("⬇️ Download backup (CSV)"):
        client = _client()
        rows = client.execute(
            "SELECT entity_type, entity_id, date, value FROM entries ORDER BY date"
        ).rows
        df = pd.DataFrame(rows, columns=["entity_type", "entity_id", "date", "value"])
        csv = df.to_csv(index=False).encode("utf-8")
        log_backup(client)
        st.download_button("Save CSV to your computer", csv, file_name=f"portfolio_backup_{entry_date.isoformat()}.csv",
                            mime="text/csv")
        st.info("Drag the downloaded file into your OneDrive folder to sync it.")
