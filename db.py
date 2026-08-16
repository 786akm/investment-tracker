"""
Shared database helpers for the Investment Tracker app.
Connects to Turso via the 'libsql' package (HTTP-based, current
Turso-recommended driver) when TURSO_DATABASE_URL / TURSO_AUTH_TOKEN
are set (via Streamlit secrets), otherwise falls back to a local
SQLite file at ./local_dev.db for local testing.
"""
import os
import libsql

def get_client():
    try:
        import streamlit as st
        url = st.secrets.get("TURSO_DATABASE_URL", None)
        token = st.secrets.get("TURSO_AUTH_TOKEN", None)
    except Exception:
        url = os.environ.get("TURSO_DATABASE_URL")
        token = os.environ.get("TURSO_AUTH_TOKEN")

    if url:
        return libsql.connect(database=url, auth_token=token)
    # local fallback for dev/testing
    return libsql.connect("local_dev.db")


def init_schema(client):
    with open(os.path.join(os.path.dirname(__file__), "schema.sql")) as f:
        sql = f.read()
    for stmt in [s.strip() for s in sql.split(";") if s.strip()]:
        client.execute(stmt)
    client.commit()


def get_or_create_agency(client, name):
    rows = client.execute("SELECT id FROM agencies WHERE name = ?", [name]).fetchall()
    if rows:
        return rows[0][0]
    client.execute("INSERT INTO agencies (name) VALUES (?)", [name])
    client.commit()
    rows = client.execute("SELECT id FROM agencies WHERE name = ?", [name]).fetchall()
    return rows[0][0]


def get_or_create_account(client, agency_id, name, cost_basis=None):
    rows = client.execute(
        "SELECT id FROM accounts WHERE agency_id = ? AND name = ?", [agency_id, name]
    ).fetchall()
    if rows:
        return rows[0][0]
    client.execute(
        "INSERT INTO accounts (agency_id, name, cost_basis) VALUES (?, ?, ?)",
        [agency_id, name, cost_basis],
    )
    client.commit()
    rows = client.execute(
        "SELECT id FROM accounts WHERE agency_id = ? AND name = ?", [agency_id, name]
    ).fetchall()
    return rows[0][0]


def get_or_create_fund(client, account_id, name, initial_cost_basis=0):
    rows = client.execute(
        "SELECT id FROM funds WHERE account_id = ? AND name = ?", [account_id, name]
    ).fetchall()
    if rows:
        return rows[0][0]
    client.execute(
        "INSERT INTO funds (account_id, name, initial_cost_basis) VALUES (?, ?, ?)",
        [account_id, name, initial_cost_basis],
    )
    client.commit()
    rows = client.execute(
        "SELECT id FROM funds WHERE account_id = ? AND name = ?", [account_id, name]
    ).fetchall()
    return rows[0][0]


def upsert_entry(client, entity_type, entity_id, date, value):
    client.execute(
        """INSERT INTO entries (entity_type, entity_id, date, value)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(entity_type, entity_id, date) DO UPDATE SET value = excluded.value""",
        [entity_type, entity_id, date, value],
    )
    client.commit()


def add_contribution(client, fund_id, date, amount, note=None):
    client.execute(
        "INSERT INTO contributions (fund_id, date, amount, note) VALUES (?, ?, ?, ?)",
        [fund_id, date, amount, note],
    )
    client.commit()


def migrate_data(client, data):
    """Load a consolidated data.json-shaped dict into the database.
    Used both by the CLI migration script and the in-app uploader."""
    count = 0
    for agency in data["agencies"]:
        agency_id = get_or_create_agency(client, agency["name"])
        for account in agency["accounts"]:
            account_id = get_or_create_account(
                client, agency_id, account["name"], account.get("costBasis")
            )
            if account["funds"]:
                for fund in account["funds"]:
                    fund_id = get_or_create_fund(
                        client, account_id, fund["name"], fund.get("costBasis") or 0
                    )
                    for point in fund["series"]:
                        upsert_entry(client, "fund", fund_id, point["date"], point["value"])
                        count += 1
                    for c in fund.get("contributions", []):
                        add_contribution(client, fund_id, c["date"], c["amount"])
            else:
                for point in account["totalSeries"]:
                    upsert_entry(client, "account", account_id, point["date"], point["value"])
                    count += 1
    return count


def fetch_all_data(client):
    """Return the full portfolio as a nested dict, same shape the dashboard expects.
    Uses a handful of bulk queries instead of one query per fund/account, so this
    scales well regardless of how many funds you're tracking."""
    agencies = client.execute("SELECT id, name FROM agencies ORDER BY name").fetchall()
    accounts = client.execute("SELECT id, agency_id, name, cost_basis FROM accounts ORDER BY name").fetchall()
    funds = client.execute("SELECT id, account_id, name, initial_cost_basis FROM funds ORDER BY name").fetchall()
    entries = client.execute("SELECT entity_type, entity_id, date, value FROM entries ORDER BY date").fetchall()
    contribs = client.execute("SELECT fund_id, date, amount FROM contributions ORDER BY date").fetchall()

    # group entries by (type, id), contributions by fund_id
    fund_entries, account_entries = {}, {}
    for etype, eid, date, value in entries:
        bucket = fund_entries if etype == "fund" else account_entries
        bucket.setdefault(eid, []).append({"date": date, "value": value})
    fund_contribs = {}
    for fund_id, date, amount in contribs:
        fund_contribs.setdefault(fund_id, []).append({"date": date, "amount": amount})

    accounts_by_agency = {}
    for acc_id, agency_id, acc_name, acc_cost in accounts:
        accounts_by_agency.setdefault(agency_id, []).append((acc_id, acc_name, acc_cost))
    funds_by_account = {}
    for f_id, account_id, f_name, f_cost in funds:
        funds_by_account.setdefault(account_id, []).append((f_id, f_name, f_cost))

    result = {"agencies": []}
    for a_id, a_name in agencies:
        acc_list = []
        for acc_id, acc_name, acc_cost_basis in accounts_by_agency.get(a_id, []):
            fund_list = []
            for f_id, f_name, f_cost in funds_by_account.get(acc_id, []):
                fund_list.append({
                    "id": f_id, "name": f_name, "costBasis": f_cost,
                    "series": fund_entries.get(f_id, []),
                    "contributions": fund_contribs.get(f_id, []),
                })
            acc_list.append({
                "id": acc_id, "name": acc_name, "costBasis": acc_cost_basis,
                "funds": fund_list,
                "totalSeries": account_entries.get(acc_id, []),
            })
        result["agencies"].append({"id": a_id, "name": a_name, "accounts": acc_list})
    return result


def log_backup(client):
    import datetime
    client.execute(
        "INSERT INTO backup_log (downloaded_at) VALUES (?)",
        [datetime.datetime.utcnow().isoformat()],
    )
    client.commit()


def last_backup_time(client):
    rows = client.execute("SELECT downloaded_at FROM backup_log ORDER BY downloaded_at DESC LIMIT 1").fetchall()
    return rows[0][0] if rows else None
