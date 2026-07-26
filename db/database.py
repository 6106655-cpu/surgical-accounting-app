"""SQLite database connection and schema management."""

from __future__ import annotations

import sqlite3
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
DB_PATH = DATA_DIR / "accounting.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS vendors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    contact TEXT,
    address TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime'))
);

CREATE TABLE IF NOT EXISTS counters (
    name TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS bills (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_no TEXT NOT NULL UNIQUE,
    bill_date TEXT NOT NULL,
    vendor_id INTEGER NOT NULL,
    total_amount REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'unpaid',
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (vendor_id) REFERENCES vendors(id)
);

CREATE TABLE IF NOT EXISTS inward_receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    receipt_no TEXT NOT NULL UNIQUE,
    receipt_date TEXT NOT NULL,
    vendor_id INTEGER NOT NULL,
    item_name TEXT NOT NULL,
    quantity REAL NOT NULL,
    rate REAL NOT NULL,
    total REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    bill_id INTEGER,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (vendor_id) REFERENCES vendors(id),
    FOREIGN KEY (bill_id) REFERENCES bills(id)
);

CREATE TABLE IF NOT EXISTS bill_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bill_id INTEGER NOT NULL,
    inward_id INTEGER NOT NULL,
    FOREIGN KEY (bill_id) REFERENCES bills(id),
    FOREIGN KEY (inward_id) REFERENCES inward_receipts(id),
    UNIQUE(inward_id)
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_no TEXT NOT NULL UNIQUE,
    payment_date TEXT NOT NULL,
    vendor_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    mode TEXT NOT NULL,
    remarks TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (vendor_id) REFERENCES vendors(id)
);

CREATE TABLE IF NOT EXISTS ledger_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id INTEGER NOT NULL,
    entry_date TEXT NOT NULL,
    entry_type TEXT NOT NULL CHECK (entry_type IN ('debit', 'credit')),
    reference_type TEXT NOT NULL,
    reference_id INTEGER NOT NULL,
    amount REAL NOT NULL,
    description TEXT,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (vendor_id) REFERENCES vendors(id)
);

CREATE INDEX IF NOT EXISTS idx_inward_vendor ON inward_receipts(vendor_id);
CREATE INDEX IF NOT EXISTS idx_inward_status ON inward_receipts(status);
CREATE INDEX IF NOT EXISTS idx_bills_vendor ON bills(vendor_id);
CREATE INDEX IF NOT EXISTS idx_payments_vendor ON payments(vendor_id);
CREATE INDEX IF NOT EXISTS idx_ledger_vendor ON ledger_entries(vendor_id);
"""


DEFAULT_COUNTERS = {
    "inward": 1000,
    "bill": 1000,
    "payment": 1000,
}


def init_database(db_path: Path | None = None) -> Path:
    """Create database file, tables, and default counters."""
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(path) as conn:
        conn.executescript(SCHEMA)
        for name, value in DEFAULT_COUNTERS.items():
            conn.execute(
                "INSERT OR IGNORE INTO counters (name, value) VALUES (?, ?)",
                (name, value),
            )
        conn.commit()

    return path


def get_connection(db_path: Path | None = None) -> sqlite3.Connection:
    """Return a SQLite connection with row factory enabled."""
    path = db_path or DB_PATH
    if not path.exists():
        init_database(path)

    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
