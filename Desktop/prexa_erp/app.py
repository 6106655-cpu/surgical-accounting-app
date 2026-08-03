import hashlib
import io
import os
import re
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import streamlit as st

if TYPE_CHECKING:
    from supabase import Client as SupabaseClient
else:
    SupabaseClient = Any

try:
    from supabase import create_client
except Exception:
    create_client = None


SECTION_CONFIG = {
    "dashboard": {
        "label": "Command Center",
        "caption": "Live view of sourcing, stock, and export receiving activity.",
        "group": "Operations",
    },
    "vendors": {
        "label": "Vendor Master",
        "caption": "Approved supply partners for surgical manufacturing inputs.",
        "group": "Master Data",
    },
    "items": {
        "label": "Item Register",
        "caption": "Raw materials and finished SKUs used in production and export orders.",
        "group": "Master Data",
    },
    "receipts": {
        "label": "Simplified Inward",
        "caption": "Select vendor, pick assigned item, and enter quantity. Total amount is auto-calculated in the background.",
        "group": "Execution",
    },
    "inward_summary": {
        "label": "Inward Summary",
        "caption": "Management view of inward totals by vendor and item without invoice complexity.",
        "group": "Operations",
    },
    "vendor_ledger": {
        "label": "Vendor Ledger",
        "caption": "Per-vendor inward lot ledger with quantities, calculated amounts, and running balance totals.",
        "group": "Operations",
    },
    "payment_slips": {
        "label": "Payment Slips",
        "caption": "Record simple payment slips with payee name, cash amount, description, and signature confirmation.",
        "group": "Finance",
    },
    "users": {
        "label": "Access Control",
        "caption": "Role-based users for procurement, warehouse, and admin teams.",
        "group": "Administration",
    },
}

ROLE_PERMISSIONS = {
    "admin": {
        "dashboard",
        "vendors",
        "items",
        "receipts",
        "inward_summary",
        "vendor_ledger",
        "payment_slips",
        "users",
    },
    "procurement": {
        "dashboard",
        "vendors",
        "items",
        "receipts",
        "inward_summary",
        "vendor_ledger",
        "payment_slips",
    },
    "warehouse": {"dashboard", "items", "receipts", "inward_summary", "vendor_ledger"},
    "viewer": {"dashboard", "inward_summary", "vendor_ledger", "payment_slips"},
    "store_ops": {"receipts", "inward_summary"},
}

SEED_USERS = [
    ("admin", "Administrator", "admin", "admin123"),
    ("buyer", "Procurement Lead", "procurement", "buyer123"),
    ("clerk", "Warehouse Clerk", "warehouse", "clerk123"),
    ("viewer", "Finance Viewer", "viewer", "viewer123"),
    ("store_ops", "Store Operations", "store_ops", "store123"),
]

RETIRED_USERNAMES = ["store_worker"]
FORCE_RESET_USERNAMES = ["store_ops"]

REQUIRED_TABLES = [
    "users",
    "vendors",
    "items",
    "vendor_item_rates",
    "receipts",
    "inward_lots",
    "packing_payment_vouchers",
]

# Keep physical table/column names for historical data compatibility.
PAYMENT_SLIPS_TABLE = "packing_payment_vouchers"
PAYMENT_SLIP_TYPE_COLUMN = "packing_reference"

APP_ROOT = Path(__file__).resolve().parent
LOCAL_DB_PATH = APP_ROOT / "prexa_erp.db"
LEGACY_LOCAL_DB_PATH = APP_ROOT / "prexa_erp_local.db"
LOCAL_SCHEMA_REBUILD_TOKEN = "2026-08-03-live-rebuild-1"

LOCAL_TABLE_SCHEMAS: dict[str, str] = {
    "users": """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            full_name TEXT NOT NULL,
            role TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """,
    "vendors": """
        CREATE TABLE IF NOT EXISTS vendors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_code TEXT UNIQUE,
            vendor_name TEXT NOT NULL,
            contact_person TEXT,
            email TEXT,
            phone TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """,
    "items": """
        CREATE TABLE IF NOT EXISTS items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT UNIQUE,
            item_name TEXT NOT NULL,
            unit TEXT,
            unit_price REAL,
            stock_on_hand REAL,
            vendor_id INTEGER,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """,
    "vendor_item_rates": """
        CREATE TABLE IF NOT EXISTS vendor_item_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_id INTEGER NOT NULL,
            item_id INTEGER NOT NULL,
            unit_rate REAL NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(vendor_id, item_id)
        )
    """,
    "receipts": """
        CREATE TABLE IF NOT EXISTS receipts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_number TEXT,
            receipt_date TEXT,
            vendor_id INTEGER,
            item_id INTEGER,
            quantity REAL,
            unit_cost REAL,
            received_by TEXT,
            notes TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """,
    "inward_lots": """
        CREATE TABLE IF NOT EXISTS inward_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lot_number TEXT,
            receipt_id INTEGER,
            vendor_id INTEGER,
            item_id INTEGER,
            quantity_received REAL,
            manufacturing_date TEXT,
            expiry_date TEXT,
            qc_status TEXT,
            warehouse_bin TEXT,
            notes TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """,
    PAYMENT_SLIPS_TABLE: """
        CREATE TABLE IF NOT EXISTS packing_payment_vouchers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            voucher_number TEXT,
            voucher_date TEXT,
            vendor_id INTEGER,
            amount REAL,
            tracking_number TEXT,
            tracking_status TEXT,
            packing_reference TEXT,
            operation_notes TEXT,
            vendor_signature_name TEXT,
            vendor_signature_date TEXT,
            approved_by TEXT,
            remarks TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """,
}


def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def ensure_session_state() -> None:
    st.session_state.setdefault("user", None)
    st.session_state.setdefault("supabase_url_input", "")
    st.session_state.setdefault("supabase_key_input", "")


def require_role(section: str) -> bool:
    user = st.session_state.get("user")
    if not user:
        return False
    return section in ROLE_PERMISSIONS.get(user["role"], set())


def resolve_supabase_credentials() -> tuple[str, str]:
    env_url = os.getenv("SUPABASE_URL", "").strip()
    env_key = os.getenv("SUPABASE_ANON_KEY", "").strip()

    secret_url = ""
    secret_key = ""
    try:
        # Access to st.secrets can raise StreamlitSecretNotFoundError when
        # secrets.toml is absent; fall through to other credential sources.
        secrets_obj = st.secrets
        secret_url = str(secrets_obj.get("SUPABASE_URL", "")).strip()
        secret_key = str(secrets_obj.get("SUPABASE_ANON_KEY", "")).strip()
    except Exception:
        secret_url = ""
        secret_key = ""

    input_url = st.session_state.get("supabase_url_input", "").strip()
    input_key = st.session_state.get("supabase_key_input", "").strip()

    url = input_url or env_url or secret_url
    key = input_key or env_key or secret_key
    return url, key


class LocalResult:
    def __init__(self, data: list[dict[str, Any]]):
        self.data = data


class LocalQuery:
    def __init__(self, client: "LocalClient", table_name: str):
        self.client = client
        self.table_name = table_name
        self.operation = "select"
        self.selected_columns: list[str] | None = None
        self.filters: list[tuple[str, Any]] = []
        self.orders: list[tuple[str, bool]] = []
        self.limit_count: int | None = None
        self.payload: Any = None
        self.on_conflict: str | None = None

    def select(self, columns: str = "*", count: str | None = None) -> "LocalQuery":
        _ = count
        self.operation = "select"
        if columns and columns != "*":
            self.selected_columns = [col.strip() for col in columns.split(",")]
        else:
            self.selected_columns = None
        return self

    def insert(self, payload: dict[str, Any] | list[dict[str, Any]]) -> "LocalQuery":
        self.operation = "insert"
        self.payload = payload
        return self

    def upsert(self, payload: list[dict[str, Any]], on_conflict: str) -> "LocalQuery":
        self.operation = "upsert"
        self.payload = payload
        self.on_conflict = on_conflict
        return self

    def update(self, payload: dict[str, Any]) -> "LocalQuery":
        self.operation = "update"
        self.payload = payload
        return self

    def delete(self) -> "LocalQuery":
        self.operation = "delete"
        return self

    def eq(self, column: str, value: Any) -> "LocalQuery":
        self.filters.append((column, value))
        return self

    def order(self, column: str, desc: bool = False) -> "LocalQuery":
        self.orders.append((column, desc))
        return self

    def limit(self, count: int) -> "LocalQuery":
        self.limit_count = count
        return self

    def _match(self, row: dict[str, Any]) -> bool:
        for column, value in self.filters:
            if row.get(column) != value:
                return False
        return True

    def _apply_select_shape(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not self.selected_columns:
            return [dict(row) for row in rows]
        shaped: list[dict[str, Any]] = []
        for row in rows:
            shaped.append({column: row.get(column) for column in self.selected_columns})
        return shaped

    def _select_sql(self) -> tuple[str, list[Any]]:
        columns = "*" if not self.selected_columns else ", ".join(self.selected_columns)
        sql = f"SELECT {columns} FROM {self.table_name}"
        params: list[Any] = []
        if self.filters:
            where_parts = []
            for column, value in self.filters:
                where_parts.append(f"{column} = ?")
                params.append(value)
            sql += " WHERE " + " AND ".join(where_parts)
        if self.orders:
            order_parts = [f"{column} {'DESC' if desc else 'ASC'}" for column, desc in self.orders]
            sql += " ORDER BY " + ", ".join(order_parts)
        if self.limit_count is not None:
            sql += " LIMIT ?"
            params.append(self.limit_count)
        return sql, params

    def _insert_sql(self, row: dict[str, Any]) -> tuple[str, list[Any]]:
        payload = dict(row)
        if "created_at" not in payload:
            payload["created_at"] = datetime.now().isoformat(timespec="seconds")
        columns = list(payload.keys())
        placeholders = ", ".join(["?" for _ in columns])
        sql = f"INSERT INTO {self.table_name} ({', '.join(columns)}) VALUES ({placeholders})"
        params = [payload[column] for column in columns]
        return sql, params

    def _upsert_sql(self, row: dict[str, Any], conflict_col: str) -> tuple[str, list[Any]]:
        payload = dict(row)
        if "created_at" not in payload:
            payload["created_at"] = datetime.now().isoformat(timespec="seconds")
        columns = list(payload.keys())
        placeholders = ", ".join(["?" for _ in columns])
        update_cols = [column for column in columns if column != conflict_col]
        update_expr = ", ".join([f"{column}=excluded.{column}" for column in update_cols])
        sql = (
            f"INSERT INTO {self.table_name} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT({conflict_col}) DO UPDATE SET {update_expr}"
        )
        params = [payload[column] for column in columns]
        return sql, params

    def _update_sql(self) -> tuple[str, list[Any]]:
        payload = dict(self.payload)
        set_columns = list(payload.keys())
        sql = f"UPDATE {self.table_name} SET " + ", ".join([f"{column} = ?" for column in set_columns])
        params: list[Any] = [payload[column] for column in set_columns]
        if self.filters:
            where_parts = []
            for column, value in self.filters:
                where_parts.append(f"{column} = ?")
                params.append(value)
            sql += " WHERE " + " AND ".join(where_parts)
        return sql, params

    def _delete_sql(self) -> tuple[str, list[Any]]:
        sql = f"DELETE FROM {self.table_name}"
        params: list[Any] = []
        if self.filters:
            where_parts = []
            for column, value in self.filters:
                where_parts.append(f"{column} = ?")
                params.append(value)
            sql += " WHERE " + " AND ".join(where_parts)
        return sql, params

    def execute(self) -> LocalResult:
        with self.client.get_connection() as conn:
            cursor = conn.cursor()

            if self.operation == "insert":
                payload_rows = self.payload if isinstance(self.payload, list) else [self.payload]
                inserted: list[dict[str, Any]] = []
                for payload_row in payload_rows:
                    sql, params = self._insert_sql(payload_row)
                    cursor.execute(sql, params)
                    row_id = cursor.lastrowid
                    selected = conn.execute(f"SELECT * FROM {self.table_name} WHERE id = ?", (row_id,)).fetchone()
                    inserted.append(dict(selected) if selected else {})
                conn.commit()
                return LocalResult(inserted)

            if self.operation == "upsert":
                conflict_col = self.on_conflict or "id"
                upserted: list[dict[str, Any]] = []
                for payload_row in self.payload:
                    sql, params = self._upsert_sql(payload_row, conflict_col)
                    cursor.execute(sql, params)
                    selected = conn.execute(
                        f"SELECT * FROM {self.table_name} WHERE {conflict_col} = ? LIMIT 1",
                        (payload_row.get(conflict_col),),
                    ).fetchone()
                    upserted.append(dict(selected) if selected else {})
                conn.commit()
                return LocalResult(upserted)

            if self.operation == "update":
                before_sql, before_params = self._select_sql()
                rows_before = [dict(row) for row in conn.execute(before_sql, before_params).fetchall()]
                update_sql, update_params = self._update_sql()
                cursor.execute(update_sql, update_params)
                conn.commit()
                return LocalResult(rows_before)

            if self.operation == "delete":
                before_sql, before_params = self._select_sql()
                rows_before = [dict(row) for row in conn.execute(before_sql, before_params).fetchall()]
                delete_sql, delete_params = self._delete_sql()
                cursor.execute(delete_sql, delete_params)
                conn.commit()
                return LocalResult(rows_before)

            select_sql, select_params = self._select_sql()
            selected = [dict(row) for row in conn.execute(select_sql, select_params).fetchall()]
            return LocalResult(selected)


class LocalClient:
    backend_name = "local"

    def __init__(self) -> None:
        self.db_path = LOCAL_DB_PATH
        self._migrate_legacy_db_if_needed()
        self._rebuild_schema_if_needed()
        self._ensure_schema()

    def table(self, table_name: str) -> LocalQuery:
        if table_name not in REQUIRED_TABLES:
            raise ValueError(f"Unknown table requested: {table_name}")
        return LocalQuery(self, table_name)

    def _ensure_schema(self) -> None:
        with self.get_connection() as conn:
            for ddl in LOCAL_TABLE_SCHEMAS.values():
                conn.execute(ddl)
            conn.commit()

    def _migrate_legacy_db_if_needed(self) -> None:
        # One-time safety migration so existing local data is retained.
        if not self.db_path.exists() and LEGACY_LOCAL_DB_PATH.exists():
            shutil.copy2(LEGACY_LOCAL_DB_PATH, self.db_path)

    def _rebuild_schema_if_needed(self) -> None:
        with self.get_connection() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            current_row = conn.execute(
                "SELECT value FROM app_meta WHERE key = ? LIMIT 1",
                ("local_schema_rebuild_token",),
            ).fetchone()
            current_token = str(current_row["value"]) if current_row else ""
            if current_token == LOCAL_SCHEMA_REBUILD_TOKEN:
                return

            conn.execute("PRAGMA foreign_keys=OFF")
            for table_name in REQUIRED_TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {table_name}")
            for ddl in LOCAL_TABLE_SCHEMAS.values():
                conn.execute(ddl)
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute(
                """
                INSERT INTO app_meta (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                ("local_schema_rebuild_token", LOCAL_SCHEMA_REBUILD_TOKEN),
            )
            conn.commit()

    def get_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path), timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection


@st.cache_resource(show_spinner=False)
def build_supabase_client(url: str, key: str) -> SupabaseClient:
    if create_client is None:
        raise RuntimeError("supabase package is not installed")
    return create_client(url, key)


def get_supabase_client() -> tuple[SupabaseClient, str]:
    url, key = resolve_supabase_credentials()
    if not url or not key:
        return LocalClient(), "Local mode (no Supabase credentials configured)"

    if create_client is None:
        return LocalClient(), "Local mode (supabase package unavailable)"

    try:
        client = build_supabase_client(url, key)
        return client, "Connected to Supabase"
    except Exception as exc:
        return LocalClient(), f"Local mode (Supabase connection failed: {exc})"


def check_supabase_schema(client: SupabaseClient) -> tuple[bool, str]:
    missing: list[str] = []
    for table_name in REQUIRED_TABLES:
        try:
            client.table(table_name).select("id", count="exact").limit(1).execute()
        except Exception:
            missing.append(table_name)

    if missing:
        return False, f"Missing or inaccessible Supabase tables: {', '.join(missing)}"
    return True, "Supabase schema is ready."


def seed_users(client: SupabaseClient) -> None:
    for reset_username in FORCE_RESET_USERNAMES:
        try:
            client.table("users").delete().eq("username", reset_username).execute()
        except Exception:
            # Ignore permission issues in restricted hosted setups.
            pass

    for retired_username in RETIRED_USERNAMES:
        try:
            client.table("users").delete().eq("username", retired_username).execute()
        except Exception:
            # Ignore permission issues in restricted hosted setups.
            pass

    payload = [
        {
            "username": username,
            "full_name": full_name,
            "role": role,
            "password_hash": hash_password(password),
        }
        for username, full_name, role, password in SEED_USERS
    ]

    try:
        client.table("users").upsert(payload, on_conflict="username").execute()
    except Exception:
        # In some Supabase setups, anon keys with RLS enabled may block this.
        pass


def initialize_data_layer(client: SupabaseClient) -> tuple[bool, str]:
    ok, message = check_supabase_schema(client)
    if not ok:
        return False, message

    seed_users(client)
    backend_name = getattr(client, "backend_name", "supabase")
    if backend_name == "local":
        return True, "Connected to local deployment datastore"
    return True, "Connected to Supabase"


def find_row_by_id(rows: list[dict[str, Any]], record_id: int) -> dict[str, Any] | None:
    for row in rows:
        if row.get("id") == record_id:
            return row
    return None


def parse_iso_date(value: str | None) -> date:
    if value:
        return date.fromisoformat(value)
    return date.today()


def format_pkr(amount: float) -> str:
    return f"PKR {amount:,.2f}"


def parse_row_date(value: Any) -> date:
    text = str(value or "").strip()
    if not text:
        return date.today()
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return date.today()


def generate_vendor_statement_pdf(
    vendor_name: str,
    start_date: date,
    end_date: date,
    ledger_rows: list[dict[str, Any]],
    opening_balance: float,
    closing_balance: float,
) -> io.BytesIO:
    # Lazy import keeps the app running even when reportlab is not installed.
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements: list[Any] = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#1E3A8A"),
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "DocSubTitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#4B5563"),
        spaceAfter=15,
    )
    cell_style = ParagraphStyle(
        "CellText",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#1F2937"),
    )

    elements.append(Paragraph("PREXA INDUSTRIES", title_style))
    elements.append(Paragraph("Surgical Instruments Manufacturing & Export<br/><b>Vendor Statement of Account</b>", subtitle_style))

    meta_data = [
        [
            Paragraph(f"<b>Vendor Name:</b> {vendor_name}", cell_style),
            Paragraph(f"<b>Period:</b> {start_date.isoformat()} to {end_date.isoformat()}", cell_style),
        ],
        [
            Paragraph(f"<b>Opening Balance:</b> {format_pkr(opening_balance)}", cell_style),
            Paragraph(f"<b>Closing Balance:</b> {format_pkr(closing_balance)}", cell_style),
        ],
    ]
    meta_table = Table(meta_data, colWidths=[250, 250])
    meta_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F4F6")),
                ("PADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    elements.append(meta_table)
    elements.append(Spacer(1, 15))

    table_data = [["Date", "Type", "Reference / Lot", "Description / Item", "Qty", "Amount (PKR)", "Balance (PKR)"]]
    for row in ledger_rows:
        table_data.append(
            [
                str(row.get("date") or ""),
                str(row.get("entry_type") or ""),
                str(row.get("reference_number") or ""),
                str(row.get("item_name") or ""),
                f"{float(row.get('quantity') or 0.0):,.2f}",
                f"{float(row.get('amount') or 0.0):,.2f}",
                f"{float(row.get('running_balance') or 0.0):,.2f}",
            ]
        )

    # Total width is tuned for letter page with left/right margins (about 552 pts).
    col_widths = [55, 80, 95, 150, 32, 70, 70]
    ledger_table = Table(table_data, colWidths=col_widths)
    ledger_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 8),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 5),
                ("TOPPADDING", (0, 0), (-1, 0), 5),
                ("ALIGN", (4, 0), (-1, -1), "RIGHT"),
                ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#FFFFFF")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#FFFFFF"), colors.HexColor("#F9FAFB")]),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 1), (-1, -1), 7.5),
                ("PADDING", (0, 1), (-1, -1), 4),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    elements.append(ledger_table)
    doc.build(elements)
    buffer.seek(0)
    return buffer


def generate_inward_slip_pdf(inward_data: dict[str, Any]) -> io.BytesIO:
    """Create an official inward receipt slip for the latest saved inward lot."""
    # Lazy import keeps the app running even when reportlab is not installed.
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.platypus import Image as RLImage
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    def generate_qr_code(data: str) -> io.BytesIO:
        import qrcode

        qr_img = qrcode.make(data)
        qr_buffer = io.BytesIO()
        qr_img.save(qr_buffer, format="PNG")
        qr_buffer.seek(0)
        return qr_buffer

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    elements: list[Any] = []
    styles = getSampleStyleSheet()

    body_style = ParagraphStyle(
        "SlipBody",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        textColor=colors.HexColor("#1F2937"),
        spaceAfter=6,
    )

    qr_data = (
        f"Lot: {inward_data.get('lot_number', '')} | "
        f"Vendor: {inward_data.get('vendor_name', '')} | "
        f"Item: {inward_data.get('item', '')} | "
        f"Qty: {inward_data.get('quantity', 0)}"
    )
    qr_buffer = generate_qr_code(qr_data)
    qr_image = RLImage(qr_buffer, width=55, height=55)

    header_data = [
        [
            Paragraph(
                "<b>PREXA INDUSTRIES</b><br/>"
                "<font size='8' color='#4B5563'>"
                "Surgical Instruments Manufacturing & Export - Sialkot<br/>"
                "<b>INWARD RECEIPT / GATE PASS</b>"
                "</font>",
                body_style,
            ),
            qr_image,
        ]
    ]
    header_table = Table(header_data, colWidths=[440, 100])
    header_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                ("RIGHTPADDING", (1, 0), (1, 0), 0),
            ]
        )
    )
    elements.append(header_table)
    elements.append(Spacer(1, 10))

    info_data = [
        [
            Paragraph(f"<b>Lot Number:</b> {inward_data.get('lot_number', '')}", body_style),
            Paragraph(f"<b>Date:</b> {inward_data.get('date', '')}", body_style),
        ],
        [
            Paragraph(f"<b>Vendor / Worker Name:</b> {inward_data.get('vendor_name', '')}", body_style),
            Paragraph("<b>Status:</b> Received & Verified", body_style),
        ],
    ]
    info_table = Table(info_data, colWidths=[270, 270])
    info_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F4F6")),
                ("PADDING", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
            ]
        )
    )
    elements.append(info_table)
    elements.append(Spacer(1, 15))

    elements.append(Paragraph("<b>Received Items Details:</b>", body_style))
    items_data = [["Item Description", "Quantity", "Rate (PKR)", "Total Amount (PKR)"]]
    items_data.append(
        [
            str(inward_data.get("item", "")),
            f"{float(inward_data.get('quantity', 0.0)):,.2f}",
            f"{float(inward_data.get('rate', 0.0)):,.2f}",
            f"{float(inward_data.get('calculated_amount', 0.0)):,.2f}",
        ]
    )
    item_table = Table(items_data, colWidths=[220, 80, 110, 130])
    item_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 9),
                ("PADDING", (0, 0), (-1, -1), 6),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D1D5DB")),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("ALIGN", (0, 0), (0, -1), "LEFT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    elements.append(item_table)
    elements.append(Spacer(1, 30))

    sign_data = [[
        Paragraph("<b>Prepared By:</b> ___________________", body_style),
        Paragraph("<b>Receiver's Signature:</b> ___________________", body_style),
    ]]
    sign_table = Table(sign_data, colWidths=[270, 270])
    elements.append(sign_table)

    doc.build(elements)
    buffer.seek(0)
    return buffer


def render_delete_confirmation(state_key: str, record_id: int, label: str) -> bool:
    if st.button("Delete Selected Record", key=f"{state_key}_request"):
        st.session_state[state_key] = record_id
        st.rerun()

    if st.session_state.get(state_key) == record_id:
        st.warning(f"Confirm deletion for {label}. This action cannot be undone.")
        confirm_col, cancel_col = st.columns(2)
        if confirm_col.button("Confirm Delete", key=f"{state_key}_confirm"):
            st.session_state.pop(state_key, None)
            return True
        if cancel_col.button("Cancel", key=f"{state_key}_cancel"):
            st.session_state.pop(state_key, None)
            st.rerun()

    return False


def normalize_code_number(value: str, prefix: str) -> int:
    match = re.match(rf"^{prefix}-(\d+)$", value or "")
    if not match:
        return 0
    return int(match.group(1))


def next_numbered_code(existing_values: list[str], prefix: str) -> str:
    max_number = 0
    for value in existing_values:
        max_number = max(max_number, normalize_code_number(value, prefix))
    return f"{prefix}-{max_number + 1:03d}"


def is_unique_violation(exc: Exception) -> bool:
    message = str(exc).lower()
    return "duplicate key" in message or "unique" in message


def fetch_users(client: SupabaseClient) -> list[dict[str, Any]]:
    response = client.table("users").select("id, username, full_name, role, created_at").order("username").execute()
    return response.data or []


def authenticate(client: SupabaseClient, username: str, password: str) -> dict[str, Any] | None:
    response = (
        client.table("users")
        .select("id, username, full_name, role")
        .eq("username", username.strip())
        .eq("password_hash", hash_password(password))
        .limit(1)
        .execute()
    )
    rows = response.data or []
    return rows[0] if rows else None


def create_user(client: SupabaseClient, username: str, full_name: str, role: str, password: str) -> None:
    client.table("users").insert(
        {
            "username": username.strip(),
            "full_name": full_name.strip(),
            "role": role,
            "password_hash": hash_password(password),
        }
    ).execute()


def fetch_vendors(client: SupabaseClient) -> list[dict[str, Any]]:
    response = (
        client.table("vendors")
        .select("id, vendor_code, vendor_name, contact_person, email, phone, created_at")
        .order("vendor_name")
        .execute()
    )
    return response.data or []


def generate_vendor_code(client: SupabaseClient) -> str:
    vendor_rows = client.table("vendors").select("vendor_code").execute().data or []
    existing_codes = [row.get("vendor_code", "") for row in vendor_rows]
    return next_numbered_code(existing_codes, "VEND")


def create_vendor(client: SupabaseClient, vendor_name: str, contact_person: str, email: str, phone: str) -> str:
    vendor_code = generate_vendor_code(client)
    client.table("vendors").insert(
        {
            "vendor_code": vendor_code,
            "vendor_name": vendor_name.strip(),
            "contact_person": contact_person.strip(),
            "email": email.strip(),
            "phone": phone.strip(),
        }
    ).execute()
    return vendor_code


def update_vendor(client: SupabaseClient, vendor_id: int, payload: dict[str, Any]) -> None:
    client.table("vendors").update(payload).eq("id", vendor_id).execute()


def delete_vendor(client: SupabaseClient, vendor_id: int) -> None:
    client.table("vendors").delete().eq("id", vendor_id).execute()


def fetch_items(client: SupabaseClient) -> list[dict[str, Any]]:
    items = (
        client.table("items")
        .select("id, sku, item_name, unit, unit_price, stock_on_hand, vendor_id, created_at")
        .order("item_name")
        .execute()
        .data
        or []
    )

    vendors = fetch_vendors(client)
    vendor_names = {vendor["id"]: vendor["vendor_name"] for vendor in vendors}
    for item in items:
        item["vendor_name"] = vendor_names.get(item.get("vendor_id"), "Unassigned")
    return items


def generate_sku(client: SupabaseClient) -> str:
    item_rows = client.table("items").select("sku").order("id", desc=True).limit(200).execute().data or []
    existing_skus = [row.get("sku", "") for row in item_rows]
    return next_numbered_code(existing_skus, "SKU")


def create_item(
    client: SupabaseClient,
    item_name: str,
    unit: str,
    unit_price: float,
    stock_on_hand: float,
    vendor_id: int | None,
) -> str:
    # Retry a few times in case two users generate the same next SKU concurrently.
    for _ in range(5):
        sku = generate_sku(client)
        try:
            inserted_rows = client.table("items").insert(
                {
                    "sku": sku,
                    "item_name": item_name.strip(),
                    "unit": unit,
                    "unit_price": float(unit_price),
                    "stock_on_hand": float(stock_on_hand),
                    "vendor_id": vendor_id,
                }
            ).execute().data or []
            if vendor_id is not None and inserted_rows:
                upsert_vendor_item_rate(client, int(vendor_id), int(inserted_rows[0]["id"]), float(unit_price))
            return sku
        except Exception as exc:
            if not is_unique_violation(exc):
                raise

    raise RuntimeError("Could not generate a unique SKU after multiple attempts.")


def update_item(client: SupabaseClient, item_id: int, payload: dict[str, Any]) -> None:
    existing_rows = client.table("items").select("vendor_id").eq("id", item_id).limit(1).execute().data or []
    previous_vendor_id = existing_rows[0].get("vendor_id") if existing_rows else None
    client.table("items").update(payload).eq("id", item_id).execute()
    vendor_id = payload.get("vendor_id")
    unit_price = payload.get("unit_price")
    if previous_vendor_id is not None and previous_vendor_id != vendor_id:
        delete_vendor_item_rate_by_vendor_item(client, int(previous_vendor_id), int(item_id))
    if vendor_id is None:
        delete_vendor_item_rates_for_item(client, int(item_id))
    elif unit_price is not None:
        delete_vendor_item_rates_for_item(client, int(item_id))
        upsert_vendor_item_rate(client, int(vendor_id), int(item_id), float(unit_price))


def delete_item(client: SupabaseClient, item_id: int) -> None:
    delete_vendor_item_rates_for_item(client, int(item_id))
    client.table("items").delete().eq("id", item_id).execute()


def fetch_vendor_item_rates(client: SupabaseClient) -> list[dict[str, Any]]:
    mappings = (
        client.table("vendor_item_rates")
        .select("id, vendor_id, item_id, unit_rate, created_at")
        .order("id", desc=True)
        .execute()
        .data
        or []
    )

    vendors = fetch_vendors(client)
    items = fetch_items(client)
    vendor_names = {vendor["id"]: vendor["vendor_name"] for vendor in vendors}
    item_labels = {item["id"]: f"{item['item_name']} ({item['sku']})" for item in items}

    for mapping in mappings:
        mapping["vendor_name"] = vendor_names.get(mapping.get("vendor_id"), "Unknown")
        mapping["item_label"] = item_labels.get(mapping.get("item_id"), "Unknown")

    return mappings


def sync_vendor_item_rates_from_items(client: SupabaseClient, vendor_name: str | None = None) -> None:
    items = fetch_items(client)
    vendors = fetch_vendors(client)
    vendor_names = {vendor["id"]: vendor["vendor_name"] for vendor in vendors}

    for item in items:
        vendor_id = item.get("vendor_id")
        if vendor_id is None:
            continue
        mapped_vendor_name = vendor_names.get(vendor_id, "")
        if vendor_name and mapped_vendor_name.casefold() != vendor_name.strip().casefold():
            continue
        upsert_vendor_item_rate(client, int(vendor_id), int(item["id"]), float(item.get("unit_price") or 0.0))


def fetch_vendor_item_rates_for_vendor(client: SupabaseClient, vendor_id: int) -> list[dict[str, Any]]:
    mappings = (
        client.table("vendor_item_rates")
        .select("id, vendor_id, item_id, unit_rate, created_at")
        .eq("vendor_id", vendor_id)
        .order("id", desc=True)
        .execute()
        .data
        or []
    )

    item_ids = sorted({int(mapping["item_id"]) for mapping in mappings if mapping.get("item_id") is not None})
    item_labels: dict[int, str] = {}
    for item_id in item_ids:
        item_rows = (
            client.table("items")
            .select("id, sku, item_name")
            .eq("id", item_id)
            .limit(1)
            .execute()
            .data
            or []
        )
        if item_rows:
            item_row = item_rows[0]
            item_labels[int(item_row["id"])] = f"{item_row['item_name']} ({item_row['sku']})"

    unique_mappings: list[dict[str, Any]] = []
    seen_item_ids: set[int] = set()
    for mapping in mappings:
        item_id = int(mapping.get("item_id") or 0)
        if item_id in seen_item_ids:
            continue
        seen_item_ids.add(item_id)
        mapping["item_label"] = item_labels.get(item_id, "Unknown")
        unique_mappings.append(mapping)

    return unique_mappings


def fetch_vendor_item_rates_for_vendor_name(client: SupabaseClient, vendor_name: str) -> list[dict[str, Any]]:
    normalized_vendor_name = vendor_name.strip()
    sync_vendor_item_rates_from_items(client, normalized_vendor_name)

    if getattr(client, "backend_name", "") == "local" and isinstance(client, LocalClient):
        sql = """
            SELECT vir.id, vir.vendor_id, vir.item_id, vir.unit_rate, vir.created_at,
                   v.vendor_name, i.item_name, i.sku
            FROM vendor_item_rates vir
            INNER JOIN vendors v ON v.id = vir.vendor_id
            INNER JOIN items i ON i.id = vir.item_id
            WHERE TRIM(LOWER(v.vendor_name)) = TRIM(LOWER(?))
            ORDER BY i.item_name ASC, vir.id DESC
        """
        print("INWARD_VENDOR_QUERY_SQL:", " ".join(sql.split()))
        print("INWARD_VENDOR_QUERY_PARAMS:", [normalized_vendor_name])
        with client.get_connection() as conn:
            rows = [dict(row) for row in conn.execute(sql, (normalized_vendor_name,)).fetchall()]
        print("INWARD_VENDOR_QUERY_ROWS:", rows)

        unique_rows: list[dict[str, Any]] = []
        seen_item_ids: set[int] = set()
        for row in rows:
            item_id = int(row.get("item_id") or 0)
            if item_id in seen_item_ids:
                continue
            seen_item_ids.add(item_id)
            row["item_label"] = f"{row['item_name']} ({row['sku']})"
            unique_rows.append(row)
        return unique_rows

    vendor_rows = (
        client.table("vendors")
        .select("id, vendor_name")
        .eq("vendor_name", normalized_vendor_name)
        .limit(1)
        .execute()
        .data
        or []
    )
    print("INWARD_VENDOR_QUERY_FALLBACK_VENDOR:", vendor_rows)
    if not vendor_rows:
        print("INWARD_VENDOR_QUERY_FALLBACK_ROWS:", [])
        return []
    rows = fetch_vendor_item_rates_for_vendor(client, int(vendor_rows[0]["id"]))
    print("INWARD_VENDOR_QUERY_FALLBACK_ROWS:", rows)
    return rows


def upsert_vendor_item_rate(client: SupabaseClient, vendor_id: int, item_id: int, unit_rate: float) -> None:
    existing = (
        client.table("vendor_item_rates")
        .select("id")
        .eq("vendor_id", vendor_id)
        .eq("item_id", item_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if existing:
        client.table("vendor_item_rates").update({"unit_rate": float(unit_rate)}).eq("id", existing[0]["id"]).execute()
    else:
        client.table("vendor_item_rates").insert(
            {
                "vendor_id": vendor_id,
                "item_id": item_id,
                "unit_rate": float(unit_rate),
            }
        ).execute()


def delete_vendor_item_rate(client: SupabaseClient, mapping_id: int) -> None:
    client.table("vendor_item_rates").delete().eq("id", mapping_id).execute()


def delete_vendor_item_rate_by_vendor_item(client: SupabaseClient, vendor_id: int, item_id: int) -> None:
    client.table("vendor_item_rates").delete().eq("vendor_id", vendor_id).eq("item_id", item_id).execute()


def delete_vendor_item_rates_for_item(client: SupabaseClient, item_id: int) -> None:
    client.table("vendor_item_rates").delete().eq("item_id", item_id).execute()


def fetch_receipts(client: SupabaseClient) -> list[dict[str, Any]]:
    receipts = (
        client.table("receipts")
        .select(
            "id, receipt_number, receipt_date, vendor_id, item_id, quantity, unit_cost, received_by, notes, created_at"
        )
        .order("receipt_date", desc=True)
        .order("id", desc=True)
        .execute()
        .data
        or []
    )

    vendors = fetch_vendors(client)
    items = fetch_items(client)
    vendor_names = {vendor["id"]: vendor["vendor_name"] for vendor in vendors}
    item_names = {item["id"]: item["item_name"] for item in items}

    for receipt in receipts:
        receipt["vendor_name"] = vendor_names.get(receipt.get("vendor_id"), "Unknown")
        receipt["item_name"] = item_names.get(receipt.get("item_id"), "Unknown")

    return receipts


def create_receipt(
    client: SupabaseClient,
    receipt_number: str,
    receipt_date: date,
    vendor_id: int,
    item_id: int,
    quantity: float,
    unit_cost: float,
    received_by: str,
    notes: str,
) -> None:
    client.table("receipts").insert(
        {
            "receipt_number": receipt_number.strip().upper(),
            "receipt_date": receipt_date.isoformat(),
            "vendor_id": vendor_id,
            "item_id": item_id,
            "quantity": float(quantity),
            "unit_cost": float(unit_cost),
            "received_by": received_by,
            "notes": notes.strip(),
        }
    ).execute()

    item_row = client.table("items").select("stock_on_hand").eq("id", item_id).limit(1).execute().data
    current_stock = float(item_row[0]["stock_on_hand"]) if item_row else 0.0
    client.table("items").update(
        {
            "stock_on_hand": current_stock + float(quantity),
        }
    ).eq("id", item_id).execute()


def fetch_inward_lots(client: SupabaseClient) -> list[dict[str, Any]]:
    lots = (
        client.table("inward_lots")
        .select(
            "id, lot_number, receipt_id, vendor_id, item_id, quantity_received, manufacturing_date, expiry_date, qc_status, warehouse_bin, notes, created_by, created_at"
        )
        .order("created_at", desc=True)
        .order("id", desc=True)
        .execute()
        .data
        or []
    )

    vendors = fetch_vendors(client)
    items = fetch_items(client)
    receipts = fetch_receipts(client)
    vendor_names = {vendor["id"]: vendor["vendor_name"] for vendor in vendors}
    item_names = {item["id"]: item["item_name"] for item in items}
    receipt_numbers = {receipt["id"]: receipt["receipt_number"] for receipt in receipts}

    for lot in lots:
        lot["vendor_name"] = vendor_names.get(lot.get("vendor_id"), "Unknown")
        lot["item_name"] = item_names.get(lot.get("item_id"), "Unknown")
        lot["receipt_number"] = receipt_numbers.get(lot.get("receipt_id"), "Unknown")

    return lots


def create_inward_lot(client: SupabaseClient, payload: dict[str, Any]) -> None:
    client.table("inward_lots").insert(payload).execute()


def update_inward_lot(client: SupabaseClient, lot_id: int, payload: dict[str, Any]) -> None:
    client.table("inward_lots").update(payload).eq("id", lot_id).execute()


def delete_inward_lot(client: SupabaseClient, lot_id: int) -> None:
    client.table("inward_lots").delete().eq("id", lot_id).execute()


def fetch_payment_slips(client: SupabaseClient) -> list[dict[str, Any]]:
    vouchers = (
        client.table(PAYMENT_SLIPS_TABLE)
        .select(
            "id, voucher_number, voucher_date, vendor_id, amount, tracking_number, tracking_status, "
            "packing_reference, operation_notes, vendor_signature_name, vendor_signature_date, approved_by, remarks, created_at"
        )
        .order("voucher_date", desc=True)
        .order("id", desc=True)
        .execute()
        .data
        or []
    )

    vendors = fetch_vendors(client)
    vendor_names = {vendor["id"]: vendor["vendor_name"] for vendor in vendors}
    for voucher in vouchers:
        vendor_name = vendor_names.get(voucher.get("vendor_id"))
        remarks = str(voucher.get("remarks") or "")
        payee_name = remarks
        if remarks.startswith("PAYEE:"):
            payee_name = remarks.split("PAYEE:", 1)[1].strip()
        voucher["vendor_name"] = vendor_name or "Unlinked"
        voucher["payee_name"] = vendor_name or payee_name or "Unknown"
        voucher["payee_type"] = "Vendor" if voucher.get("vendor_id") else "Worker"
        voucher["description"] = voucher.get("operation_notes") or ""
    return vouchers


def generate_payment_slip_number(client: SupabaseClient) -> str:
    rows = client.table(PAYMENT_SLIPS_TABLE).select("voucher_number").order("id", desc=True).limit(200).execute().data or []
    existing = [row.get("voucher_number", "") for row in rows]
    # New records use PSV prefix; existing PPV records remain untouched.
    return next_numbered_code(existing, "PSV")


def create_payment_slip(client: SupabaseClient, payload: dict[str, Any]) -> None:
    client.table(PAYMENT_SLIPS_TABLE).insert(payload).execute()


def update_payment_slip(client: SupabaseClient, voucher_id: int, payload: dict[str, Any]) -> None:
    client.table(PAYMENT_SLIPS_TABLE).update(payload).eq("id", voucher_id).execute()


def delete_payment_slip(client: SupabaseClient, voucher_id: int) -> None:
    client.table(PAYMENT_SLIPS_TABLE).delete().eq("id", voucher_id).execute()


def fetch_vendor_ledger_rows(client: SupabaseClient) -> list[dict[str, Any]]:
    lots = fetch_inward_lots(client)
    receipts = fetch_receipts(client)
    payment_slips = fetch_payment_slips(client)
    receipt_by_id = {int(receipt["id"]): receipt for receipt in receipts}

    ledger_rows: list[dict[str, Any]] = []
    for lot in lots:
        receipt = receipt_by_id.get(int(lot.get("receipt_id") or 0))
        if not receipt:
            continue
        quantity = float(lot.get("quantity_received") or 0.0)
        unit_rate = float(receipt.get("unit_cost") or 0.0)
        amount = quantity * unit_rate
        ledger_rows.append(
            {
                "entry_id": f"lot-{lot.get('id')}",
                "date": receipt.get("receipt_date") or lot.get("created_at") or "",
                "vendor_id": lot.get("vendor_id"),
                "vendor_name": lot.get("vendor_name"),
                "entry_type": "Inward Lot",
                "item_name": lot.get("item_name"),
                "reference_number": lot.get("lot_number"),
                "quantity": quantity,
                "unit_rate": unit_rate,
                "amount": amount,
                "sort_id": int(lot.get("id") or 0),
            }
        )

    for slip in payment_slips:
        vendor_id = slip.get("vendor_id")
        payee_name = str(slip.get("payee_name") or "").strip()
        vendor_name = str(slip.get("vendor_name") or payee_name or "Unknown")
        amount = -abs(float(slip.get("amount") or 0.0))
        ledger_rows.append(
            {
                "entry_id": f"slip-{slip.get('id')}",
                "date": slip.get("voucher_date") or slip.get("created_at") or "",
                "vendor_id": vendor_id,
                "vendor_name": vendor_name,
                "entry_type": "Payment",
                "item_name": slip.get("description") or "Payment Slip",
                "reference_number": slip.get("voucher_number"),
                "quantity": 0.0,
                "unit_rate": 0.0,
                "amount": amount,
                "sort_id": int(slip.get("id") or 0),
                "payee_name": payee_name,
            }
        )

    # Combine inward and payment rows, then sort oldest to newest so running balance
    # follows the true ledger sequence.
    ledger_rows.sort(key=lambda row: (row.get("date") or "", row.get("sort_id") or 0))

    running_balance_by_vendor: dict[str, float] = {}
    enriched_rows: list[dict[str, Any]] = []
    for row in ledger_rows:
        vendor_balance_key = str(row.get("vendor_id") if row.get("vendor_id") is not None else row.get("vendor_name") or "")
        running_balance_by_vendor.setdefault(vendor_balance_key, 0.0)
        running_balance_by_vendor[vendor_balance_key] += float(row.get("amount") or 0.0)
        enriched = dict(row)
        enriched["running_balance"] = running_balance_by_vendor[vendor_balance_key]
        enriched_rows.append(enriched)

    return enriched_rows


def fetch_inward_summary_rows(client: SupabaseClient) -> list[dict[str, Any]]:
    receipts = fetch_receipts(client)
    summary_by_vendor_item: dict[tuple[str, str], dict[str, Any]] = {}

    for receipt in receipts:
        vendor_name = str(receipt.get("vendor_name") or "Unknown")
        item_name = str(receipt.get("item_name") or "Unknown")
        key = (vendor_name, item_name)
        quantity = float(receipt.get("quantity") or 0.0)
        unit_rate = float(receipt.get("unit_cost") or 0.0)
        amount = quantity * unit_rate
        if key not in summary_by_vendor_item:
            summary_by_vendor_item[key] = {
                "vendor_name": vendor_name,
                "item_name": item_name,
                "inward_entries": 0,
                "total_quantity": 0.0,
                "total_amount": 0.0,
            }
        summary_by_vendor_item[key]["inward_entries"] += 1
        summary_by_vendor_item[key]["total_quantity"] += quantity
        summary_by_vendor_item[key]["total_amount"] += amount

    rows = list(summary_by_vendor_item.values())
    rows.sort(key=lambda row: (row["vendor_name"], row["item_name"]))
    return rows




def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --bg-start: #f2f5fa;
            --bg-end: #e5ebf3;
            --panel: rgba(255, 255, 255, 0.96);
            --panel-strong: #ffffff;
            --line: rgba(17, 38, 66, 0.14);
            --line-soft: rgba(17, 38, 66, 0.08);
            --text: #132238;
            --muted: #50657d;
            --accent: #0e7490;
            --accent-deep: #0f3b57;
            --success: #1f7a5a;
            --warm: #ad6a1f;
            --shadow-sm: 0 6px 16px rgba(16, 30, 50, 0.06);
            --shadow-md: 0 10px 30px rgba(16, 30, 50, 0.08);
        }
        .stApp {
            background:
                radial-gradient(circle at top right, rgba(14, 116, 144, 0.08), transparent 24%),
                linear-gradient(180deg, var(--bg-start) 0%, var(--bg-end) 100%);
            color: var(--text);
        }
        .block-container {
            padding-top: 1.6rem;
            padding-bottom: 2rem;
            max-width: 1400px;
        }
        h1, h2, h3 { color: var(--text); letter-spacing: -0.02em; }
        p, li, label { color: var(--muted); }
        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, rgba(15, 35, 57, 0.98) 0%, rgba(9, 24, 41, 0.98) 100%);
            border-right: 1px solid rgba(255, 255, 255, 0.08);
        }
        [data-testid="stSidebar"] * { color: #f5f8fb; }
        [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: rgba(245, 248, 251, 0.74); }
        .hero-card,.panel-card,.nav-card,.metric-card,.workflow-card {
            background: var(--panel);
            border: 1px solid var(--line);
            border-radius: 10px;
            box-shadow: var(--shadow-md);
        }
        .hero-card { padding: 1.35rem 1.5rem; margin-bottom: 1rem; border-top: 2px solid rgba(14, 116, 144, 0.25); }
        .hero-eyebrow { color: var(--accent); text-transform: uppercase; letter-spacing: 0.14em; font-size: 0.74rem; font-weight: 700; margin-bottom: 0.45rem; }
        .hero-title { color: var(--text); font-size: 2rem; font-weight: 700; margin: 0; }
        .hero-copy { color: var(--muted); font-size: 0.98rem; line-height: 1.65; margin: 0.65rem 0 0; }
        .workflow-card,.panel-card { padding: 1.15rem 1.2rem; margin-bottom: 1rem; }
        .workflow-step { color: var(--text); font-size: 1rem; font-weight: 600; margin-bottom: 0.35rem; }
        .workflow-copy { color: var(--muted); font-size: 0.92rem; line-height: 1.55; margin: 0; }
        .section-kicker { color: var(--accent); text-transform: uppercase; letter-spacing: 0.12em; font-size: 0.72rem; font-weight: 700; margin-bottom: 0.25rem; }
        .section-title { color: var(--text); font-size: 1.55rem; font-weight: 700; margin-bottom: 0.2rem; }
        .section-copy { color: var(--muted); font-size: 0.95rem; margin-bottom: 0; }
        .nav-card {
            padding: 1rem 1rem 0.75rem;
            margin-bottom: 0.9rem;
            background: rgba(255, 255, 255, 0.05);
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 8px;
            box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.06);
        }
        .nav-label { color: #f8fbff; font-size: 0.94rem; font-weight: 700; margin: 0; }
        .nav-copy { color: rgba(248, 251, 255, 0.74); font-size: 0.82rem; margin: 0.25rem 0 0; line-height: 1.45; }
        .sidebar-group { color: rgba(248, 251, 255, 0.54); text-transform: uppercase; letter-spacing: 0.12em; font-size: 0.68rem; font-weight: 700; margin: 1rem 0 0.35rem; }
        .stRadio > div { gap: 0.5rem; }
        .stRadio label {
            width: 100%; min-height: 44px; display: flex; align-items: center;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid rgba(255, 255, 255, 0.12);
            border-radius: 8px;
            padding: 0.62rem 0.8rem; margin: 0; box-sizing: border-box; transition: 0.2s ease;
        }
        .stRadio label:hover { background: rgba(255, 255, 255, 0.08); border-color: rgba(255, 255, 255, 0.18); }
        .stRadio label p { margin: 0; font-size: 0.92rem; font-weight: 600; line-height: 1.2; }
        .stTextInput input,.stTextArea textarea,.stNumberInput input,.stDateInput input,.stSelectbox [data-baseweb="select"] > div {
            border-radius: 8px; border: 1px solid var(--line-soft); background: #ffffff;
        }
        .stForm { background: var(--panel-strong); border: 1px solid var(--line); border-radius: 10px; padding: 1rem 1rem 0.4rem; box-shadow: var(--shadow-sm); }
        .stButton > button,.stForm button,[data-testid="stFormSubmitButton"] > button {
            border-radius: 8px; border: 1px solid rgba(14, 116, 144, 0.45);
            background: linear-gradient(135deg, var(--accent), var(--accent-deep));
            color: #ffffff !important; font-weight: 700; min-height: 2.8rem; padding: 0.58rem 1.1rem;
        }
        .ledger-header {
            color: var(--accent);
            font-weight: 700;
            letter-spacing: -0.01em;
            margin: 0.1rem 0 0.75rem;
        }
        .stDataFrame,[data-testid="stDataFrame"] { border: 1px solid var(--line); border-radius: 10px; overflow: hidden; box-shadow: var(--shadow-sm); background: var(--panel-strong); }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_hero(title: str, copy: str, eyebrow: str) -> None:
    st.markdown(
        f"""
        <div class="hero-card">
            <div class="hero-eyebrow">{eyebrow}</div>
            <h1 class="hero-title">{title}</h1>
            <p class="hero-copy">{copy}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_section_intro(section: str) -> None:
    config = SECTION_CONFIG[section]
    st.markdown(
        f"""
        <div class="panel-card">
            <div class="section-kicker">{config['group']}</div>
            <div class="section-title">{config['label']}</div>
            <p class="section-copy">{config['caption']}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_metric_card(column, label: str, value: str, subtext: str) -> None:
    column.markdown(
        f"""
        <div class="metric-card">
            <div class="section-kicker">{label}</div>
            <div class="section-title" style="font-size:1.8rem;">{value}</div>
            <p class="section-copy">{subtext}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_sidebar_navigation(available_sections: list[str]) -> str:
    ordered_sections = [
        section
        for section in [
            "dashboard",
            "vendors",
            "items",
            "receipts",
            "inward_summary",
            "vendor_ledger",
            "payment_slips",
            "users",
        ]
        if section in available_sections
    ]

    with st.sidebar:
        st.markdown("### Prexa ERP Navigation")
        if st.button("Logout", use_container_width=True):
            st.session_state.clear()
            st.rerun()
        st.markdown("---")

        return st.radio(
            "Go to",
            options=ordered_sections,
            label_visibility="collapsed",
            format_func=lambda value: SECTION_CONFIG[value]["label"],
        )


def render_connection_controls() -> None:
    with st.sidebar.expander("Supabase Connection", expanded=False):
        st.caption("Optional: set SUPABASE_URL / SUPABASE_ANON_KEY or enter credentials here. Without these, the app runs in local mode.")
        url = st.text_input(
            "Supabase URL",
            value=st.session_state.get("supabase_url_input", ""),
            placeholder="https://your-project-ref.supabase.co",
        )
        key = st.text_input(
            "Supabase API Key",
            value=st.session_state.get("supabase_key_input", ""),
            type="password",
            placeholder="paste-anon-or-service-role-key",
        )
        if st.button("Apply Connection", use_container_width=True):
            st.session_state["supabase_url_input"] = url.strip()
            st.session_state["supabase_key_input"] = key.strip()
            build_supabase_client.clear()
            st.rerun()


def render_login(client: SupabaseClient) -> None:
    left, right = st.columns([1.15, 0.85])
    with left:
        render_hero(
            "Prexa Industries ERP",
            "Control the full inbound workflow for surgical manufacturing and export orders.",
            "Prexa Industries",
        )

    with right:
        with st.form("login_form", clear_on_submit=False):
            st.markdown("### Secure Sign In")
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login", use_container_width=True)

        if submitted:
            user = authenticate(client, username, password)
            if user:
                st.session_state["user"] = user
                st.success("Login successful.")
                st.rerun()
            else:
                st.error("Invalid username or password.")


def render_header() -> None:
    if st.sidebar.button("Logout", use_container_width=True):
        st.session_state["user"] = None
        st.rerun()


def render_dashboard(client: SupabaseClient) -> None:
    vendors = fetch_vendors(client)
    items = fetch_items(client)
    receipts = fetch_receipts(client)
    lots = fetch_inward_lots(client)
    payment_slips = fetch_payment_slips(client)

    stock_value = sum(float(item.get("stock_on_hand", 0)) * float(item.get("unit_price", 0)) for item in items)
    low_stock = sum(1 for item in items if float(item.get("stock_on_hand", 0)) <= 10)

    render_section_intro("dashboard")
    col1, col2, col3, col4 = st.columns(4)
    render_metric_card(col1, "Approved Vendors", str(len(vendors)), "Qualified sourcing base")
    render_metric_card(col2, "Active SKUs", str(len(items)), "Tracked for production")
    render_metric_card(col3, "Inward Entries", str(len(receipts)), "Auto-rated from item master")
    render_metric_card(col4, "Payment Slips", str(len(payment_slips)), f"Low stock items: {low_stock}")

    st.markdown("### Recent Goods Receipts")
    if receipts:
        st.dataframe(
            [
                {
                    "receipt_number": row["receipt_number"],
                    "receipt_date": row["receipt_date"],
                    "vendor_name": row["vendor_name"],
                    "item_name": row["item_name"],
                    "quantity": row["quantity"],
                    "unit_cost": row["unit_cost"],
                }
                for row in receipts[:8]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption(f"No receipts recorded yet. Inventory value: ${stock_value:,.2f}")


def render_vendors(client: SupabaseClient) -> None:
    render_section_intro("vendors")
    with st.form("vendor_form", clear_on_submit=True):
        st.markdown("### Add Approved Vendor")
        col1, col2 = st.columns(2)
        next_vendor_code = generate_vendor_code(client)
        col1.text_input("Vendor Code", value=next_vendor_code, disabled=True)
        vendor_name = col2.text_input("Vendor Name")
        contact_person = col1.text_input("Contact Person")
        email = col2.text_input("Email")
        phone = col1.text_input("Phone")
        submitted = st.form_submit_button("Save Vendor")

    if submitted:
        if not vendor_name.strip():
            st.error("Vendor name is required.")
        else:
            try:
                code = create_vendor(client, vendor_name, contact_person, email, phone)
                st.success(f"Vendor saved with code {code}.")
                st.rerun()
            except Exception as exc:
                st.error(f"Vendor could not be saved: {exc}")

    vendor_rows = fetch_vendors(client)
    st.markdown("### Approved Vendor Directory")
    st.dataframe(vendor_rows, use_container_width=True, hide_index=True)

    if vendor_rows:
        st.markdown("### Edit or Delete Vendor")
        options = {row["id"]: f"{row['vendor_code']} | {row['vendor_name']}" for row in vendor_rows}
        selected_id = st.selectbox("Select Vendor", options=list(options.keys()), format_func=lambda rid: options[rid])
        selected = find_row_by_id(vendor_rows, selected_id)
        if not selected:
            return

        with st.form("vendor_edit_form"):
            col1, col2 = st.columns(2)
            edit_vendor_code = col1.text_input("Vendor Code", value=selected["vendor_code"], key=f"vendor_code_{selected_id}")
            edit_vendor_name = col2.text_input("Vendor Name", value=selected["vendor_name"], key=f"vendor_name_{selected_id}")
            edit_contact_person = col1.text_input("Contact Person", value=selected.get("contact_person") or "", key=f"vendor_contact_{selected_id}")
            edit_email = col2.text_input("Email", value=selected.get("email") or "", key=f"vendor_email_{selected_id}")
            edit_phone = col1.text_input("Phone", value=selected.get("phone") or "", key=f"vendor_phone_{selected_id}")
            updated = st.form_submit_button("Update Vendor")

        if updated:
            try:
                update_vendor(
                    client,
                    selected_id,
                    {
                        "vendor_code": edit_vendor_code.strip().upper(),
                        "vendor_name": edit_vendor_name.strip(),
                        "contact_person": edit_contact_person.strip(),
                        "email": edit_email.strip(),
                        "phone": edit_phone.strip(),
                    },
                )
                st.success("Vendor updated.")
                st.rerun()
            except Exception as exc:
                st.error(f"Vendor update failed: {exc}")

        if render_delete_confirmation("confirm_delete_vendor", selected_id, selected["vendor_name"]):
            try:
                delete_vendor(client, selected_id)
                st.success("Vendor deleted.")
                st.rerun()
            except Exception as exc:
                st.error(f"Vendor cannot be deleted: {exc}")


def render_items(client: SupabaseClient) -> None:
    render_section_intro("items")
    vendors = fetch_vendors(client)
    vendor_options = {vendor["vendor_name"]: vendor["id"] for vendor in vendors}

    with st.form("item_form", clear_on_submit=True):
        st.markdown("### Register Material or Finished SKU")
        col1, col2 = st.columns(2)
        next_sku = generate_sku(client)
        col1.text_input("SKU", value=next_sku, disabled=True)
        item_name = col2.text_input("Item Name")
        unit = col1.selectbox("Unit", ["pcs", "box", "kg", "ltr", "set"])
        unit_price = col2.number_input("Unit Price", min_value=0.0, step=0.5)
        stock_on_hand = col1.number_input("Opening Stock", min_value=0.0, step=1.0)
        vendor_name = col2.selectbox("Preferred Vendor", options=["Unassigned", *vendor_options.keys()])
        submitted = st.form_submit_button("Save Item")

    if submitted:
        if not item_name.strip():
            st.error("Item name is required.")
        else:
            try:
                sku = create_item(
                    client,
                    item_name,
                    unit,
                    float(unit_price),
                    float(stock_on_hand),
                    vendor_options.get(vendor_name),
                )
                st.success(f"Item saved with SKU {sku}.")
                st.rerun()
            except Exception as exc:
                st.error(f"Item could not be saved: {exc}")

    item_rows = fetch_items(client)
    st.markdown("### Item Master")
    st.dataframe(item_rows, use_container_width=True, hide_index=True)

    if item_rows:
        st.markdown("### Edit or Delete Item")
        item_options = {row["id"]: f"{row['sku']} | {row['item_name']}" for row in item_rows}
        selected_id = st.selectbox("Select Item", options=list(item_options.keys()), format_func=lambda rid: item_options[rid])
        selected = find_row_by_id(item_rows, selected_id)
        if not selected:
            return

        edit_vendor_names = ["Unassigned", *vendor_options.keys()]
        current_vendor_name = selected.get("vendor_name") or "Unassigned"
        vendor_index = edit_vendor_names.index(current_vendor_name) if current_vendor_name in edit_vendor_names else 0
        unit_options = ["pcs", "box", "kg", "ltr", "set"]

        with st.form("item_edit_form"):
            col1, col2 = st.columns(2)
            edit_sku = col1.text_input("SKU", value=selected["sku"], key=f"item_sku_{selected_id}")
            edit_item_name = col2.text_input("Item Name", value=selected["item_name"], key=f"item_name_{selected_id}")
            edit_unit = col1.selectbox("Unit", options=unit_options, index=unit_options.index(selected["unit"]) if selected["unit"] in unit_options else 0, key=f"item_unit_{selected_id}")
            edit_unit_price = col2.number_input("Unit Price", min_value=0.0, step=0.5, value=float(selected["unit_price"]), key=f"item_price_{selected_id}")
            edit_stock_on_hand = col1.number_input("Stock On Hand", min_value=0.0, step=1.0, value=float(selected["stock_on_hand"]), key=f"item_stock_{selected_id}")
            edit_vendor_name = col2.selectbox("Preferred Vendor", options=edit_vendor_names, index=vendor_index, key=f"item_vendor_{selected_id}")
            updated = st.form_submit_button("Update Item")

        if updated:
            if not edit_sku.strip() or not edit_item_name.strip():
                st.error("SKU and item name are required.")
                return
            try:
                update_item(
                    client,
                    selected_id,
                    {
                        "sku": edit_sku.strip().upper(),
                        "item_name": edit_item_name.strip(),
                        "unit": edit_unit,
                        "unit_price": float(edit_unit_price),
                        "stock_on_hand": float(edit_stock_on_hand),
                        "vendor_id": vendor_options.get(edit_vendor_name),
                    },
                )
                st.success("Item updated.")
                st.rerun()
            except Exception as exc:
                st.error(f"Item update failed: {exc}")

        if render_delete_confirmation("confirm_delete_item", selected_id, selected["item_name"]):
            try:
                delete_item(client, selected_id)
                st.success("Item deleted.")
                st.rerun()
            except Exception as exc:
                st.error(f"Item cannot be deleted: {exc}")

    st.caption("Vendor-item-rate mappings are managed automatically from Item Master using Preferred Vendor and Unit Price.")


def render_receipts(client: SupabaseClient) -> None:
    render_section_intro("receipts")
    vendors = fetch_vendors(client)

    if not vendors:
        st.warning("Create at least one vendor before posting inward entries.")
        return

    vendor_options = {vendor["vendor_name"]: vendor["id"] for vendor in vendors}
    st.markdown("### Simplified Inward Entry")
    st.caption("Only date, vendor, mapped item/stage, and quantity are required.")

    selected_vendor_name = st.selectbox(
        "Vendor Name",
        options=list(vendor_options.keys()),
        key="inward_vendor_name",
    )
    selected_vendor_id = vendor_options[selected_vendor_name]
    vendor_mappings = fetch_vendor_item_rates_for_vendor_name(client, selected_vendor_name)
    mapping_rows_by_id = {int(row["id"]): row for row in vendor_mappings}
    mapping_option_ids = list(mapping_rows_by_id.keys())

    with st.form("receipt_form", clear_on_submit=True):
        inward_date = st.date_input("Date", value=date.today())

        if mapping_option_ids:
            selected_mapping_id = st.selectbox(
                "Auto-loaded Vendor Items / Stages",
                options=mapping_option_ids,
                format_func=lambda mapping_id: mapping_rows_by_id[mapping_id]["item_label"],
                key=f"inward_vendor_item_{selected_vendor_id}",
                help="Loaded strictly from the selected vendor's permanent Vendor-Item-Rate mapping.",
            )
        else:
            st.warning("No items or stages are assigned to this vendor yet. Map items first.")
            st.selectbox(
                "Auto-loaded Vendor Items / Stages",
                options=[""],
                format_func=lambda _: "No mapped items for selected vendor",
                disabled=True,
            )
            selected_mapping_id = None

        quantity = st.number_input("Quantity", min_value=0.01, step=1.0)
        submitted = st.form_submit_button("Save Inward Entry")

    if submitted:
        if not mapping_option_ids or selected_mapping_id is None:
            st.error("No permanent vendor-item-rate mapping found. Configure it in Item Register first.")
            return
        try:
            selected_mapping = mapping_rows_by_id[selected_mapping_id]
            selected_item_id = int(selected_mapping["item_id"])
            selected_item_label = str(selected_mapping.get("item_label") or "Mapped Item")
            auto_unit_rate = float(selected_mapping.get("unit_rate") or 0.0)
            auto_total_amount = float(quantity) * auto_unit_rate
            receipt_number = f"RCV-{datetime.now():%Y%m%d-%H%M%S}"
            create_receipt(
                client,
                receipt_number,
                inward_date,
                selected_vendor_id,
                selected_item_id,
                float(quantity),
                auto_unit_rate,
                st.session_state["user"]["full_name"],
                f"Auto-calculated total amount: {auto_total_amount:.2f}",
            )

            # Auto-create inward lot in simplified mode so lot traceability remains.
            lot_number = f"LOT-{datetime.now():%Y%m%d-%H%M%S}"
            create_inward_lot(
                client,
                {
                    "lot_number": lot_number,
                    "receipt_id": fetch_receipts(client)[0]["id"],
                    "vendor_id": selected_vendor_id,
                    "item_id": selected_item_id,
                    "quantity_received": float(quantity),
                    "manufacturing_date": inward_date.isoformat(),
                    "expiry_date": inward_date.isoformat(),
                    "qc_status": "Pending QC",
                    "warehouse_bin": "",
                    "notes": "Auto-generated from simplified inward entry",
                    "created_by": st.session_state["user"]["full_name"],
                },
            )

            create_payment_slip(
                client,
                {
                    "voucher_number": generate_payment_slip_number(client),
                    "voucher_date": inward_date.isoformat(),
                    "vendor_id": selected_vendor_id,
                    "amount": auto_total_amount,
                    PAYMENT_SLIP_TYPE_COLUMN: "Vendor",
                    "tracking_number": receipt_number,
                    "tracking_status": "Generated from Inward",
                    "vendor_signature_name": "",
                    "vendor_signature_date": inward_date.isoformat(),
                    "operation_notes": f"Auto-generated from inward: {selected_item_label} x {float(quantity):.2f}",
                    "approved_by": st.session_state["user"]["full_name"],
                    "remarks": f"PAYEE: {selected_vendor_name}",
                },
            )

            st.session_state["last_inward_slip"] = {
                "lot_number": lot_number,
                "date": inward_date.isoformat(),
                "vendor_name": selected_vendor_name,
                "item": selected_item_label,
                "quantity": float(quantity),
                "rate": auto_unit_rate,
                "calculated_amount": auto_total_amount,
            }

            st.success("Inward entry saved. Total cost was calculated in the background and a Payment Slip was generated.")
            st.rerun()
        except Exception as exc:
            st.error(f"Receipt could not be posted: {exc}")

    last_inward_slip = st.session_state.get("last_inward_slip")
    if isinstance(last_inward_slip, dict) and last_inward_slip:
        st.markdown("---")
        st.markdown("### Inward Slip")
        st.caption("Download the official inward receipt slip for the latest saved inward entry.")
        try:
            slip_pdf = generate_inward_slip_pdf(last_inward_slip)
            st.download_button(
                label="Download Inward Slip PDF",
                data=slip_pdf,
                file_name=f"Inward_Slip_{last_inward_slip.get('lot_number', 'latest')}.pdf",
                mime="application/pdf",
                use_container_width=True,
                key="download_last_inward_slip_pdf",
            )
        except Exception as exc:
            st.warning("Inward slip PDF export is currently unavailable. Please verify ReportLab is installed and try again.")
            with st.expander("Technical details"):
                st.code(str(exc))


def render_payment_slips(client: SupabaseClient) -> None:
    render_section_intro("payment_slips")
    vendors = fetch_vendors(client)
    vendor_options = {vendor["vendor_name"]: vendor["id"] for vendor in vendors}

    with st.form("simple_payment_slip_form", clear_on_submit=True):
        st.markdown("### Record Payment Slip")
        col1, col2, col3 = st.columns(3)
        col1.text_input("Slip Number", value=generate_payment_slip_number(client), disabled=True)
        slip_date = col2.date_input("Date", value=date.today(), key="simple_slip_date")
        payee_type = col3.selectbox("Payee Type", options=["Vendor", "Worker"])

        if payee_type == "Vendor":
            if not vendor_options:
                st.selectbox("Vendor Name", options=["No vendors available"], disabled=True)
                vendor_name = ""
            else:
                vendor_name = st.selectbox("Vendor Name", options=list(vendor_options.keys()))
            payee_name = vendor_name
            vendor_id = vendor_options.get(vendor_name)
        else:
            payee_name = st.text_input("Worker / Payee Name", placeholder="e.g., Imran Polishia")
            vendor_id = None

        amount = st.number_input("Cash Amount", min_value=0.01, step=1.0, key="simple_slip_amount")
        description = st.text_area("Description", placeholder="Reason/purpose of this payment")
        signature_name = st.text_input("Signature")
        signature_date = st.date_input("Signature Date", value=date.today(), key="simple_signature_date")
        submitted = st.form_submit_button("Save Payment Slip")

    if submitted:
        if not payee_name.strip():
            st.error("Payee name is required.")
            return
        try:
            create_payment_slip(
                client,
                {
                    "voucher_number": generate_payment_slip_number(client),
                    "voucher_date": slip_date.isoformat(),
                    "vendor_id": vendor_id,
                    "amount": float(amount),
                    PAYMENT_SLIP_TYPE_COLUMN: payee_type,
                    "tracking_number": "",
                    "tracking_status": "Recorded",
                    "vendor_signature_name": signature_name.strip(),
                    "vendor_signature_date": signature_date.isoformat(),
                    "operation_notes": description.strip(),
                    "approved_by": st.session_state["user"]["full_name"],
                    "remarks": f"PAYEE: {payee_name.strip()}",
                },
            )
            st.success("Payment slip saved.")
            st.rerun()
        except Exception as exc:
            st.error(f"Payment slip could not be saved: {exc}")

    vouchers = fetch_payment_slips(client)
    st.markdown("### Payment Slip Register")
    st.dataframe(
        [
            {
                "slip_number": row.get("voucher_number"),
                "date": row.get("voucher_date"),
                "payee_type": row.get("payee_type"),
                "payee_name": row.get("payee_name"),
                "cash_amount": row.get("amount"),
                "description": row.get("description"),
                "signature": row.get("vendor_signature_name"),
                "signature_date": row.get("vendor_signature_date"),
            }
            for row in vouchers
        ],
        use_container_width=True,
        hide_index=True,
    )

    if vouchers:
        st.markdown("### Edit or Delete Payment Slip")
        options = {
            row["id"]: f"{row['voucher_number']} | {row.get('payee_name', 'Unknown')} | {float(row['amount']):.2f}"
            for row in vouchers
        }
        selected_id = st.selectbox(
            "Select Payment Slip",
            options=list(options.keys()),
            format_func=lambda rid: options[rid],
        )
        selected = find_row_by_id(vouchers, selected_id)
        if not selected:
            return

        vendor_names = list(vendor_options.keys())
        initial_payee_type = "Vendor" if selected.get("vendor_id") else "Worker"
        initial_payee_name = selected.get("payee_name") or ""
        with st.form("simple_payment_slip_edit_form"):
            col1, col2, col3 = st.columns(3)
            edit_slip_number = col1.text_input(
                "Slip Number",
                value=selected["voucher_number"],
                key=f"simple_slip_num_{selected_id}",
            )
            edit_slip_date = col2.date_input(
                "Date",
                value=parse_iso_date(selected.get("voucher_date")),
                key=f"simple_slip_date_{selected_id}",
            )
            edit_payee_type = col3.selectbox(
                "Payee Type",
                options=["Vendor", "Worker"],
                index=0 if initial_payee_type == "Vendor" else 1,
                key=f"simple_payee_type_{selected_id}",
            )

            if edit_payee_type == "Vendor":
                if vendor_names:
                    current_vendor_name = selected.get("vendor_name") if selected.get("vendor_name") in vendor_names else vendor_names[0]
                    edit_vendor_name = st.selectbox(
                        "Vendor Name",
                        options=vendor_names,
                        index=vendor_names.index(current_vendor_name),
                        key=f"simple_vendor_{selected_id}",
                    )
                    edit_payee_name = edit_vendor_name
                    edit_vendor_id = vendor_options[edit_vendor_name]
                else:
                    st.selectbox("Vendor Name", options=["No vendors available"], disabled=True)
                    edit_payee_name = ""
                    edit_vendor_id = None
            else:
                edit_payee_name = st.text_input(
                    "Worker / Payee Name",
                    value=initial_payee_name,
                    key=f"simple_worker_{selected_id}",
                )
                edit_vendor_id = None

            edit_amount = st.number_input(
                "Cash Amount",
                min_value=0.01,
                step=1.0,
                value=float(selected.get("amount") or 0.0),
                key=f"simple_slip_amount_{selected_id}",
            )
            edit_description = st.text_area(
                "Description",
                value=selected.get("description") or "",
                key=f"simple_description_{selected_id}",
            )
            edit_signature_name = st.text_input(
                "Signature",
                value=selected.get("vendor_signature_name") or "",
                key=f"simple_signature_name_{selected_id}",
            )
            edit_signature_date = st.date_input(
                "Signature Date",
                value=parse_iso_date(selected.get("vendor_signature_date")),
                key=f"simple_signature_date_{selected_id}",
            )
            updated = st.form_submit_button("Update Payment Slip")

        if updated:
            if not edit_payee_name.strip():
                st.error("Payee name is required.")
                return
            try:
                update_payment_slip(
                    client,
                    selected_id,
                    {
                        "voucher_number": edit_slip_number.strip().upper(),
                        "voucher_date": edit_slip_date.isoformat(),
                        "vendor_id": edit_vendor_id,
                        "amount": float(edit_amount),
                        PAYMENT_SLIP_TYPE_COLUMN: edit_payee_type,
                        "tracking_number": "",
                        "tracking_status": "Recorded",
                        "vendor_signature_name": edit_signature_name.strip(),
                        "vendor_signature_date": edit_signature_date.isoformat(),
                        "operation_notes": edit_description.strip(),
                        "remarks": f"PAYEE: {edit_payee_name.strip()}",
                    },
                )
                st.success("Payment slip updated.")
                st.rerun()
            except Exception as exc:
                st.error(f"Payment slip update failed: {exc}")

        if render_delete_confirmation("confirm_delete_payment_slip", selected_id, selected["voucher_number"]):
            try:
                delete_payment_slip(client, selected_id)
                st.success("Payment slip deleted.")
                st.rerun()
            except Exception as exc:
                st.error(f"Payment slip delete failed: {exc}")


def render_inward_summary(client: SupabaseClient) -> None:
    render_section_intro("inward_summary")
    summary_rows = fetch_inward_summary_rows(client)
    receipts = fetch_receipts(client)

    total_quantity = sum(float(row.get("total_quantity") or 0.0) for row in summary_rows)
    total_amount = sum(float(row.get("total_amount") or 0.0) for row in summary_rows)

    metric1, metric2, metric3 = st.columns(3)
    metric1.metric("Inward Entries", str(len(receipts)))
    metric2.metric("Total Quantity", f"{total_quantity:,.2f}")
    metric3.metric("Total Amount", format_pkr(total_amount))

    if summary_rows:
        st.dataframe(summary_rows, use_container_width=True, hide_index=True)
    else:
        st.caption("No inward entries recorded yet.")


def render_vendor_ledger(client: SupabaseClient) -> None:
    render_section_intro("vendor_ledger")
    vendors = fetch_vendors(client)
    if not vendors:
        st.caption("No vendors available yet.")
        return

    st.markdown(
        """
        <style>
            .main-title { font-size: 26px; font-weight: 700; color: #1E3A8A; margin-bottom: 5px; }
            .sub-title { font-size: 16px; font-weight: 600; color: #4B5563; margin-bottom: 15px; }
        </style>
        """,
        unsafe_allow_html=True,
    )
    st.markdown('<div class="main-title">Prexa Industries - Vendor Ledger & Statement</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-title">Surgical Manufacturing & Export Operations ERP</div>', unsafe_allow_html=True)
    st.markdown('<div class="ledger-header">Vendor inward lots and payment slips are combined into one running vendor balance.</div>', unsafe_allow_html=True)

    vendor_options = {vendor["vendor_name"]: vendor["id"] for vendor in vendors}
    col1, col2, col3 = st.columns(3)
    selected_vendor_name = col1.selectbox("Select Vendor", options=list(vendor_options.keys()), key="ledger_vendor_name")
    start_date = col2.date_input("Start Date", value=date.today().replace(day=1), key="ledger_start_date")
    end_date = col3.date_input("End Date", value=date.today(), key="ledger_end_date")
    selected_vendor_id = vendor_options[selected_vendor_name]

    ledger_rows = [
        row
        for row in fetch_vendor_ledger_rows(client)
        if row.get("vendor_id") == selected_vendor_id
        or str(row.get("payee_name") or "").strip().casefold() == selected_vendor_name.casefold()
    ]
    ledger_rows = [
        row
        for row in ledger_rows
        if start_date <= parse_row_date(row.get("date")) <= end_date
    ]

    if ledger_rows:
        ledger_rows.sort(key=lambda row: (row.get("date") or "", row.get("sort_id") or 0))

    # Recompute vendor-specific running balance on the filtered sequence,
    # equivalent to: sort by date ascending -> cumulative sum of signed amounts.
    running_balance = 0.0
    for row in ledger_rows:
        running_balance += float(row.get("amount") or 0.0)
        row["running_balance"] = running_balance

    total_quantity = sum(float(row.get("quantity") or 0.0) for row in ledger_rows if row.get("entry_type") == "Inward Lot")
    total_inward_amount = sum(float(row.get("amount") or 0.0) for row in ledger_rows if row.get("entry_type") == "Inward Lot")
    total_payment_amount = sum(abs(float(row.get("amount") or 0.0)) for row in ledger_rows if row.get("entry_type") == "Payment")
    accumulated_balance = float(ledger_rows[-1].get("running_balance") or 0.0) if ledger_rows else 0.0

    metric1, metric2, metric3 = st.columns(3)
    metric1.metric("Accumulated Quantity", f"{total_quantity:,.2f}")
    metric2.metric("Total Inward", format_pkr(total_inward_amount))
    metric3.metric("Accumulated Balance", format_pkr(accumulated_balance))

    st.caption(f"Payments posted for this vendor: {format_pkr(total_payment_amount)}")

    if ledger_rows:
        try:
            opening_balance = float(ledger_rows[0].get("running_balance") or 0.0) - float(ledger_rows[0].get("amount") or 0.0)
            pdf_file = generate_vendor_statement_pdf(
                selected_vendor_name,
                start_date,
                end_date,
                ledger_rows,
                opening_balance,
                accumulated_balance,
            )
            st.download_button(
                label="Download HD PDF Report",
                data=pdf_file,
                file_name=f"{selected_vendor_name}_Ledger_Report.pdf",
                mime="application/pdf",
                use_container_width=True,
            )
        except Exception as exc:
            st.info(f"PDF export is unavailable in this environment: {exc}")

        st.dataframe(
            [
                {
                    "date": row.get("date"),
                    "type": row.get("entry_type"),
                    "item_or_description": row.get("item_name"),
                    "reference": row.get("reference_number"),
                    "quantity": row.get("quantity"),
                    "amount": row.get("amount"),
                    "running_balance": row.get("running_balance"),
                }
                for row in ledger_rows
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.caption("No inward lots or payment slips recorded yet for this vendor.")


def render_users(client: SupabaseClient) -> None:
    render_section_intro("users")
    st.caption("Admins can create login users here.")
    with st.form("user_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        username = col1.text_input("Username")
        full_name = col2.text_input("Full Name")
        role = col1.selectbox("Role", options=list(ROLE_PERMISSIONS.keys()))
        password = col2.text_input("Temporary Password", type="password")
        submitted = st.form_submit_button("Create User")

    if submitted:
        if not username.strip() or not full_name.strip() or not password:
            st.error("Username, full name, and temporary password are required.")
        else:
            try:
                create_user(client, username, full_name, role, password)
                st.success("User created.")
                st.rerun()
            except Exception as exc:
                st.error(f"User could not be created: {exc}")

    st.dataframe(fetch_users(client), use_container_width=True, hide_index=True)


def main() -> None:
    st.set_page_config(page_title="Prexa Industries ERP", page_icon="🏭", layout="wide")
    inject_styles()
    ensure_session_state()

    st.markdown(
        """
        <div class="hero-card">
            <div class="hero-eyebrow">Prexa Industries</div>
            <div class="hero-title">Surgical Manufacturing & Export Operations ERP</div>
            <p class="hero-copy">Supabase cloud data backend with role-based operational workflows.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    client, _connection_status = get_supabase_client()

    ready, status_message = initialize_data_layer(client)
    if not ready:
        st.error(status_message)
        return

    if not st.session_state["user"]:
        render_login(client)
        return

    available_sections = [
        section
        for section in [
            "dashboard",
            "vendors",
            "items",
            "receipts",
            "inward_summary",
            "vendor_ledger",
            "payment_slips",
            "users",
        ]
        if require_role(section)
    ]
    section = render_sidebar_navigation(available_sections)

    if section == "dashboard":
        render_dashboard(client)
    elif section == "vendors":
        render_vendors(client)
    elif section == "items":
        render_items(client)
    elif section == "receipts":
        render_receipts(client)
    elif section == "inward_summary":
        render_inward_summary(client)
    elif section == "vendor_ledger":
        render_vendor_ledger(client)
    elif section == "payment_slips":
        render_payment_slips(client)
    elif section == "users":
        render_users(client)


if __name__ == "__main__":
    main()
