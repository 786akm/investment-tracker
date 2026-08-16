-- Investment Tracker schema (Turso / libSQL)

CREATE TABLE IF NOT EXISTS agencies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agency_id INTEGER NOT NULL REFERENCES agencies(id),
    name TEXT NOT NULL,
    -- used only for accounts with no per-fund breakdown (e.g. IFAST wrap accounts)
    cost_basis REAL,
    UNIQUE(agency_id, name)
);

CREATE TABLE IF NOT EXISTS funds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    name TEXT NOT NULL,
    initial_cost_basis REAL NOT NULL DEFAULT 0,
    UNIQUE(account_id, name)
);

-- top-up / additional investment events, logged separately from market value
CREATE TABLE IF NOT EXISTS contributions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    fund_id INTEGER NOT NULL REFERENCES funds(id),
    date TEXT NOT NULL,          -- YYYY-MM-DD
    amount REAL NOT NULL,
    note TEXT
);

-- weekly value entries. entity_type = 'fund' (normal) or 'account' (IFAST-style, no fund breakdown)
CREATE TABLE IF NOT EXISTS entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type TEXT NOT NULL CHECK(entity_type IN ('fund','account')),
    entity_id INTEGER NOT NULL,
    date TEXT NOT NULL,          -- YYYY-MM-DD
    value REAL NOT NULL,
    UNIQUE(entity_type, entity_id, date)
);

-- tracks when the user last downloaded a backup, to drive the reminder banner
CREATE TABLE IF NOT EXISTS backup_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    downloaded_at TEXT NOT NULL   -- ISO timestamp
);

CREATE INDEX IF NOT EXISTS idx_entries_entity ON entries(entity_type, entity_id, date);
CREATE INDEX IF NOT EXISTS idx_contrib_fund ON contributions(fund_id, date);
