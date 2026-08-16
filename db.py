"""
Shared database helpers for the Investment Tracker app.
Connects to Turso when TURSO_DATABASE_URL / TURSO_AUTH_TOKEN are set
(via Streamlit secrets), otherwise falls back to a local SQLite file
at ./local_dev.db for local testing.
"""
import os
import libsql_client

def get_client():
    try:
        import streamlit as st
        url = st.secrets.get("TURSO_DATABASE_URL", None)
        token = st.secrets.get("TURSO_AUTH_TOKEN", None)
    except Exception:
        url = os.environ.get("TURSO_DATABASE_URL")
        token = os.environ.get("TURSO_AUTH_TOKEN")

    if url:
        return libsql_client.create_client_sync(url=url, auth_token=token)
    # local fallback for dev/testing
    return libsql_client.create_client_sync(url="file:local_dev.db")


def init_schema(client):
    with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
        sql = f.read()
    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
        client.execute(stmt)


def get_or_create_agency(client, name):
    rs = client.execute("SELECT id FROM agencies WHERE name = ?", [name])
    if rs.rows:
        return rs.rows[0][0]
    client.execute("INSERT INTO agencies (name) VALUES (?)", [name])
    rs = client.execute("SELECT id FROM agencies WHERE name = ?", [name])
    return rs.rows[0][0]


def get_or_create_account(client, agency_id, name, cost_basis=None):
    rs = client.execute(
        "SELECT id FROM accounts WHERE agency_id = ? AND name = ?", [agency_id, name]
    )
    if rs.rows:
        return rs.rows[0][0]
    client.execute(
        "INSERT INTO accounts (agency_id, name, cost_basis) VALUES (?, ?, ?)",
        [agency_id, name, cost_basis],
    )
    rs = client.execute(
        "SELECT id FROM accounts WHERE agency_id = ? AND name = ?", [agency_id, name]
    )
    return rs.rows[0][0]


def get_or_create_fund(client, account_id, name, initial_cost_basis=0):
    rs = client.execute(
        "SELECT id FROM funds WHERE account_id = ? AND name = ?", [account_id, name]
    )
    if rs.rows:
        return rs.rows[0][0]
    client.execute(
        "INSERT INTO funds (account_id, name, initial_cost_basis) VALUES (?, ?, ?)",
        [account_id, name, initial_cost_basis],
    )
    rs = client.execute(
        "SELECT id FROM funds WHERE account_id = ? AND name = ?", [account_id, name]
    )
    return rs.rows[0][0]


def upsert_entry(client, entity_type, entity_id, date, value):
    client.execute(
        """INSERT INTO entries (entity_type, entity_id, date, value)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(entity_type, entity_id, date) DO UPDATE SET value = excluded.value""",
        [entity_type, entity_id, date, value],
    )


def add_contribution(client, fund_id, date, amount, note=None):
    client.execute(
        "INSERT INTO contributions (fund_id, date, amount, note) VALUES (?, ?, ?, ?)",
        [fund_id, date, amount, note],
    )


def fetch_all_data(client):
    """Return the full portfolio as a nested dict, same shape the dashboard expects."""
    agencies = client.execute("SELECT id, name FROM agencies ORDER BY name").rows
    result = {"agencies": []}
    for a_id, a_name in agencies:
        accounts = client.execute(
            "SELECT id, name, cost_basis FROM accounts WHERE agency_id = ? ORDER BY name",
            [a_id],
        ).rows
        acc_list = []
        for acc_id, acc_name, acc_cost_basis in accounts:
            funds = client.execute(
                "SELECT id, name, initial_cost_basis FROM funds WHERE account_id = ? ORDER BY name",
                [acc_id],
            ).rows
            fund_list = []
            for f_id, f_name, f_cost in funds:
                series = client.execute(
                    "SELECT date, value FROM entries WHERE entity_type='fund' AND entity_id=? ORDER BY date",
                    [f_id],
                ).rows
                contribs = client.execute(
                    "SELECT date, amount FROM contributions WHERE fund_id=? ORDER BY date",
                    [f_id],
                ).rows
                fund_list.append({
                    "id": f_id, "name": f_name, "costBasis": f_cost,
                    "series": [{"date": d, "value": v} for d, v in series],
                    "contributions": [{"date": d, "amount": v} for d, v in contribs],
                })
            total_series = client.execute(
                "SELECT date, value FROM entries WHERE entity_type='account' AND entity_id=? ORDER BY date",
                [acc_id],
            ).rows
            acc_list.append({
                "id": acc_id, "name": acc_name, "costBasis": acc_cost_basis,
                "funds": fund_list,
                "totalSeries": [{"date": d, "value": v} for d, v in total_series],
            })
        result["agencies"].append({"id": a_id, "name": a_name, "accounts": acc_list})
    return result


def log_backup(client):
    import datetime
    client.execute(
        "INSERT INTO backup_log (downloaded_at) VALUES (?)",
        [datetime.datetime.utcnow().isoformat()],
    )


def last_backup_time(client):
    rs = client.execute("SELECT downloaded_at FROM backup_log ORDER BY downloaded_at DESC LIMIT 1")
    return rs.rows[0][0] if rs.rows else None
