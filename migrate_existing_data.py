"""
One-time migration: loads the already-parsed data.json (built from your
5 Excel files) into the database, including the corrected Std Chartered
TA Global contribution history.

Run this ONCE after the database is set up:
    python migrate_existing_data.py
"""
import json
from db import (
    get_client, init_schema, get_or_create_agency, get_or_create_account,
    get_or_create_fund, upsert_entry, add_contribution,
)

def main():
    with open("data.json") as f:
        data = json.load(f)

    client = get_client()
    init_schema(client)

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
                    for c in fund.get("contributions", []):
                        add_contribution(client, fund_id, c["date"], c["amount"])
            else:
                # account-level only (IFAST-style)
                for point in account["totalSeries"]:
                    upsert_entry(client, "account", account_id, point["date"], point["value"])

    print("Migration complete.")
    client.close()

if __name__ == "__main__":
    main()
