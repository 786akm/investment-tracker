"""
One-time migration: loads a consolidated data.json into the database.
Only needed if you're running this from your own machine with Turso
credentials as environment variables. If deploying to a public repo,
use the in-app "Import data" uploader instead (Weekly entry page) —
don't put data.json in the repo.

Run this ONCE:
    TURSO_DATABASE_URL=... TURSO_AUTH_TOKEN=... python migrate_existing_data.py
"""
import json
from db import get_client, init_schema, migrate_data

def main():
    with open("data.json") as f:
        data = json.load(f)
    client = get_client()
    init_schema(client)
    count = migrate_data(client, data)
    print(f"Migration complete. {count} value entries loaded.")
    client.close()

if __name__ == "__main__":
    main()
