import io
import json
import os
import sqlite3
import uuid
import zipfile
from datetime import datetime
from typing import Optional
from urllib.parse import quote

import pandas as pd
import streamlit as st
from streamlit_option_menu import option_menu
from db.database import get_connection
import streamlit.components.v1 as components
from slip_app import (
    build_barcode_image,
    build_print_html,
    build_slip_image,
    get_recent_slips,
    init_db as init_slip_db,
    save_slip_record,
    to_data_uri,
)

try:
    from fpdf import FPDF
    FPDF_AVAILABLE = True
except ImportError:
    FPDF_AVAILABLE = False

# Page Configuration
st.set_page_config(page_title="Prexa Industries - ERP", layout="wide", initial_sidebar_state="expanded")

# Custom Modern & Stylish CSS
st.markdown("""
    <style>
    :root {
        --prexa-bg: #FFFFFF;
        --prexa-text: #000000;
        --prexa-text-strong: #000000;
        --prexa-text-muted: #000000;
        --prexa-border: rgba(29, 53, 87, 0.22);
    }
    html, body, .stApp {
        background: var(--prexa-bg) !important;
        color: var(--prexa-text);
        font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
        color-scheme: light !important;
    }
    html, body {
        margin: 0 !important;
        padding: 0 !important;
        min-height: 100%;
    }
    [data-testid="stAppViewContainer"],
    [data-testid="stAppViewContainer"] .main,
    [data-testid="stAppViewContainer"] .main > div,
    [data-testid="stAppViewContainer"] .main .block-container,
    [data-testid="stVerticalBlock"] {
        background: var(--prexa-bg) !important;
        color: var(--prexa-text) !important;
    }
    [data-testid="stAppViewContainer"] .main,
    [data-testid="stAppViewContainer"] .main * {
        color: var(--prexa-text) !important;
        -webkit-text-fill-color: var(--prexa-text) !important;
    }
    .stApp,
    .stApp *,
    [data-testid="stSidebar"],
    [data-testid="stSidebar"] *,
    table,
    thead,
    tbody,
    tr,
    th,
    td {
        color: #000000 !important;
        -webkit-text-fill-color: #000000 !important;
    }
    [data-testid="stAppViewContainer"] .main h1,
    [data-testid="stAppViewContainer"] .main h2,
    [data-testid="stAppViewContainer"] .main h3,
    [data-testid="stAppViewContainer"] .main h4,
    [data-testid="stAppViewContainer"] .main h5,
    [data-testid="stAppViewContainer"] .main h6,
    [data-testid="stAppViewContainer"] .main p,
    [data-testid="stAppViewContainer"] .main span,
    [data-testid="stAppViewContainer"] .main label,
    [data-testid="stAppViewContainer"] .main li,
    [data-testid="stAppViewContainer"] .main small,
    [data-testid="stAppViewContainer"] .main strong,
    [data-testid="stAppViewContainer"] .main td,
    [data-testid="stAppViewContainer"] .main th,
    [data-testid="stAppViewContainer"] .main [data-testid="stMarkdownContainer"],
    [data-testid="stAppViewContainer"] .main [data-testid="stWidgetLabel"] {
        color: var(--prexa-text-strong) !important;
        -webkit-text-fill-color: var(--prexa-text-strong) !important;
    }
    [data-testid="stAppViewContainer"] .main input,
    [data-testid="stAppViewContainer"] .main textarea,
    [data-testid="stAppViewContainer"] .main [role="combobox"],
    [data-testid="stAppViewContainer"] .main [role="listbox"],
    [data-testid="stAppViewContainer"] .main [role="option"],
    [data-testid="stAppViewContainer"] .main [role="columnheader"],
    [data-testid="stAppViewContainer"] .main [role="gridcell"] {
        color: var(--prexa-text) !important;
        -webkit-text-fill-color: var(--prexa-text) !important;
    }
    .stApp {
        padding-top: 0;
        min-height: 100vh;
    }

    .header-container {
        display: none;
    }
    .company-title {
        color: var(--prexa-text-strong);
        font-size: 34px;
        font-weight: 900;
        margin: 0 0 4px 0;
        line-height: 1.05;
        letter-spacing: 0.2px;
    }
    .company-address {
        color: var(--prexa-text-muted);
        font-size: 13px;
        margin: 0 0 14px 0;
        line-height: 1.4;
    }

    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #FFFFFF 0%, #F4F8FF 100%) !important;
        border-right: 1px solid var(--prexa-border) !important;
        box-shadow: 4px 0 30px rgba(29, 53, 87, 0.08);
    }
    [data-testid="stSidebar"] .sidebar-content {
        padding-top: 14px;
    }
    .sidebar-brand {
        color: var(--prexa-text-strong);
        font-weight: 900;
        font-size: 20px;
        text-align: center;
        margin-bottom: 6px;
        letter-spacing: 0.08em;
        line-height: 1.05;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .sidebar-divider {
        width: 100%;
        height: 1px;
        background: rgba(29, 53, 87, 0.16);
        margin: 8px 0 12px 0;
    }
    .sidebar-header {
        color: var(--prexa-text-strong);
        font-weight: 800;
        font-size: 16px;
        text-align: center;
        padding: 8px 0 10px 0;
        border-bottom: 1px solid var(--prexa-border);
        margin-bottom: 14px;
    }
    [data-testid="stSidebar"] button {
        color: var(--prexa-text-strong) !important;
        border-radius: 14px !important;
        border: 1px solid var(--prexa-border) !important;
        background: #FFFFFF !important;
        box-shadow: inset 0 1px 0 rgba(255,255,255,0.08);
    }
    [data-testid="stSidebar"] button:hover {
        background: #EEF4FF !important;
    }

    .block-container {
        background: #FFFFFF !important;
        padding: 44px 18px 18px 18px !important;
        max-width: 100% !important;
    }
    [data-testid="stAppViewContainer"] .main .block-container {
        padding-top: 44px !important;
    }
    .css-1d391kg, .css-1d391kg .element-container, .css-18e3th9, .element-container {
        border: none !important;
        background: transparent !important;
        box-shadow: none !important;
    }

    .panel-card, .kpi-group, .kpi-card, .ledger-card {
        background: #FFFFFF;
        border-radius: 20px;
        border: 1px solid rgba(15, 23, 42, 0.08);
        box-shadow: 0 18px 30px rgba(15, 23, 42, 0.05);
        padding: 16px;
        margin-bottom: 16px;
    }
    .panel-card {
        padding: 16px;
    }
    .panel-title {
        font-size: 20px;
        font-weight: 800;
        color: var(--prexa-text-strong);
        margin-bottom: 8px;
    }
    .panel-title {
        font-size: 20px;
        font-weight: 800;
        color: var(--prexa-text-strong);
        margin-bottom: 16px;
    }
    .panel-subtitle {
        color: var(--prexa-text-muted);
        margin-bottom: 10px;
    }
    .panel-content {
        margin-top: 6px;
    }

    .kpi-group {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 18px;
        margin-bottom: 18px;
    }
    .kpi-card {
        min-height: 110px;
    }
    .kpi-card h3 {
        font-size: 14px;
        margin-bottom: 12px;
        color: var(--prexa-text-muted);
        font-weight: 700;
    }
    .kpi-card .kpi-value {
        font-size: 24px;
        font-weight: 800;
        color: var(--prexa-text-strong);
        margin: 0;
    }
    .kpi-card.warning {
        border-color: rgba(245, 158, 11, 0.22);
    }
    .kpi-card.warning .kpi-value {
        color: var(--prexa-text-strong);
    }

    .metric-card {
        background: #FFFFFF;
        border-radius: 18px;
        border: 1px solid rgba(148, 163, 184, 0.14);
        box-shadow: 0 10px 18px rgba(15, 23, 42, 0.05);
        padding: 10px 12px;
        min-height: 95px;
        height: 95px;
        position: relative;
        overflow: hidden;
        display: flex;
        flex-direction: column;
        justify-content: center;
        gap: 4px;
        width: 100%;
        box-sizing: border-box;
    }
    .metric-card::before {
        content: "";
        position: absolute;
        top: 0;
        left: 0;
        width: 100%;
        height: 4px;
        border-top-left-radius: 18px;
        border-top-right-radius: 18px;
    }
    .metric-card.accent-1::before { background: #2563EB; }
    .metric-card.accent-2::before { background: #10B981; }
    .metric-card.accent-3::before { background: #F59E0B; }
    .metric-card.accent-4::before { background: #8B5CF6; }
    .metric-card.accent-1 .metric-value { color: var(--prexa-text-strong); }
    .metric-card.accent-2 .metric-value { color: var(--prexa-text-strong); }
    .metric-card.accent-3 .metric-value { color: var(--prexa-text-strong); }
    .metric-card.accent-4 .metric-value { color: var(--prexa-text-strong); }
    .metric-card h3 {
        margin-top: 0;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.08em;
        margin-bottom: 4px;
        color: var(--prexa-text-muted);
        text-transform: uppercase;
    }
    .metric-card .metric-value {
        font-size: 18px;
        font-weight: 800;
        color: var(--prexa-text-strong);
        margin: 0;
        line-height: 1.05;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .metric-card .metric-helper {
        color: var(--prexa-text-muted);
        font-size: 12px;
        margin-top: 4px;
    }

    .company-title {
        color: var(--prexa-text-strong);
        font-size: 34px;
        font-weight: 900;
        margin: 0 0 4px 0;
        line-height: 1.05;
        letter-spacing: 0.2px;
    }
    .company-address {
        color: var(--prexa-text-muted);
        font-size: 13px;
        margin: 0 0 14px 0;
        line-height: 1.4;
    }

    .prexa-table-wrap {
        width: 100%;
        overflow-x: auto;
        background: #FFFFFF;
        border: 1px solid rgba(15, 23, 42, 0.12);
        border-radius: 12px;
    }
    .prexa-table {
        width: 100%;
        border-collapse: collapse;
        background: #FFFFFF;
    }
    .prexa-table thead th {
        background: #F8FAFC;
        color: #000000 !important;
        font-weight: 700;
        text-align: left;
        font-size: 13px;
        border-bottom: 1px solid rgba(15, 23, 42, 0.14);
    }
    .prexa-table th,
    .prexa-table td {
        color: #000000 !important;
        -webkit-text-fill-color: #000000 !important;
        padding: 10px 12px;
        font-size: 13px;
        border-bottom: 1px solid rgba(15, 23, 42, 0.08);
        vertical-align: top;
    }
    .prexa-table tbody tr:nth-child(even) {
        background: #FCFDFF;
    }
    .prexa-table tbody tr:hover {
        background: #F5F8FC;
    }

    .voucher-box {
        border-radius: 22px;
        background: #FFFFFF;
        border: 1px solid rgba(15, 23, 42, 0.08);
        box-shadow: 0 18px 38px rgba(15, 23, 42, 0.08);
        padding: 26px;
        margin-top: 16px;
        margin-bottom: 16px;
    }
    .voucher-table th, .voucher-table td {
        border: 1px solid rgba(148, 163, 184, 0.16);
        padding: 12px 14px;
        font-size: 13px;
        color: var(--prexa-text);
    }
    .voucher-table th {
        background: #F8FAFC;
    }
    .sig-line {
        border-top: 1px dashed rgba(15, 23, 42, 0.35);
        width: 180px;
        text-align: center;
        padding-top: 8px;
        font-size: 12px;
        color: var(--prexa-text-muted);
    }

    button[kind="primary"] {
        background: #E8F1FF !important;
        color: var(--prexa-text-strong) !important;
        border-radius: 14px !important;
        border: 1px solid var(--prexa-border) !important;
        box-shadow: 0 8px 14px rgba(29, 53, 87, 0.08) !important;
    }
    button[kind="secondary"] {
        border-radius: 14px !important;
    }

    .store-slip-shell {
        max-width: 920px;
        margin: 0 auto;
    }
    .store-slip-shell .store-slip-section {
        margin-bottom: 18px;
    }
    .store-slip-shell [data-testid="stForm"] {
        border: 1px solid rgba(15, 23, 42, 0.08);
        border-radius: 18px;
        padding: 16px;
        background: #FFFFFF;
        box-shadow: 0 14px 28px rgba(15, 23, 42, 0.05);
    }
    .store-slip-shell .stButton > button,
    .store-slip-shell .stDownloadButton > button,
    .store-slip-shell div[data-testid="stFormSubmitButton"] button {
        width: 100%;
        min-height: 52px;
        font-size: 15px;
        font-weight: 700;
    }
    .store-slip-shell .stTextInput input,
    .store-slip-shell .stNumberInput input,
    .store-slip-shell div[data-baseweb="select"] > div,
    .store-slip-shell textarea {
        min-height: 50px;
        font-size: 15px;
        border-radius: 14px;
    }
    .store-slip-shell label,
    .store-slip-shell [data-testid="stWidgetLabel"] {
        font-size: 14px;
        font-weight: 700;
    }
    .store-slip-shell iframe {
        width: 100% !important;
        max-width: 100%;
    }

    @media (max-width: 900px) {
        html, body, .stApp {
            color-scheme: light !important;
        }
        .block-container {
            padding-left: 12px !important;
            padding-right: 12px !important;
        }
        [data-testid="stAppViewContainer"] input,
        [data-testid="stAppViewContainer"] textarea,
        [data-testid="stAppViewContainer"] div[data-baseweb="select"] > div,
        [data-testid="stAppViewContainer"] [role="combobox"],
        [data-testid="stAppViewContainer"] [role="listbox"],
        [data-testid="stAppViewContainer"] [role="option"] {
            background: #FFFFFF !important;
            color: var(--prexa-text) !important;
            -webkit-text-fill-color: var(--prexa-text) !important;
            border-color: rgba(15, 23, 42, 0.20) !important;
        }
        [data-testid="stAppViewContainer"] input::placeholder,
        [data-testid="stAppViewContainer"] textarea::placeholder {
            color: #000000 !important;
            -webkit-text-fill-color: #000000 !important;
        }
        [data-testid="stAppViewContainer"] input:disabled,
        [data-testid="stAppViewContainer"] textarea:disabled,
        [data-testid="stAppViewContainer"] div[data-baseweb="select"] > div[aria-disabled="true"] {
            background: #F8FAFC !important;
            color: var(--prexa-text) !important;
            opacity: 1 !important;
        }
        [data-testid="stAppViewContainer"] .stButton > button,
        [data-testid="stAppViewContainer"] .stDownloadButton > button,
        [data-testid="stAppViewContainer"] div[data-testid="stFormSubmitButton"] button,
        [data-testid="stAppViewContainer"] button[kind="primary"],
        [data-testid="stAppViewContainer"] button[kind="secondary"] {
            background: #FFFFFF !important;
            color: var(--prexa-text-strong) !important;
            border: 1px solid rgba(15, 23, 42, 0.20) !important;
            box-shadow: none !important;
        }
        .store-slip-shell {
            max-width: 100%;
        }
        .store-slip-shell [data-testid="stForm"] {
            padding: 14px;
            border-radius: 16px;
        }
        .store-slip-shell .stTextInput input,
        .store-slip-shell .stNumberInput input,
        .store-slip-shell div[data-baseweb="select"] > div,
        .store-slip-shell textarea {
            min-height: 54px;
            font-size: 16px;
        }
        .store-slip-shell .stButton > button,
        .store-slip-shell .stDownloadButton > button,
        .store-slip-shell div[data-testid="stFormSubmitButton"] button {
            min-height: 56px;
            font-size: 16px;
            border-radius: 16px;
        }
        .store-slip-shell h3,
        .store-slip-shell .stSubheader {
            font-size: 1.1rem;
        }
    }

    @media (max-width: 640px) {
        .store-slip-shell .store-slip-section {
            margin-bottom: 14px;
        }
        .store-slip-shell label,
        .store-slip-shell [data-testid="stWidgetLabel"] {
            font-size: 15px;
        }
        .store-slip-shell iframe {
            min-height: 420px;
        }
    }

    @media print {
        @page {
            size: A4 portrait;
            margin: 10mm;
        }
        body {
            background-color: #FFFFFF !important;
            margin: 0 !important;
            padding: 0 !important;
        }
        header, footer, nav, [data-testid="stSidebar"], .stApp > header, div[data-testid="stToolbar"], .element-container:not(:has(.voucher-box)) {
            display: none !important;
        }
        body * {
            visibility: hidden;
        }
        .voucher-box, .voucher-box * {
            visibility: visible;
        }
    }
    </style>
""", unsafe_allow_html=True)

# File Paths
VENDOR_FILE = "vendor_catalog.json"
INWARD_FILE = "inward_transactions.csv"
PAYMENT_FILE = "vendor_payments.csv"
DEFAULT_ADMIN_PIN = "1234"

STORE_STAFF_PAGES = ["Factory Store Slip"]
ADMIN_PAGES = [
    "Dashboard",
    "Factory Store Slip",
    "Payments & Voucher",
    "Vendor Bills",
    "Vendor Ledger",
    "Vendor Directory",
    "Items Catalog",
    "Reports",
]
def load_vendor_catalog() -> dict:
    if not os.path.exists(VENDOR_FILE):
        return {}
    try:
        with open(VENDOR_FILE, "r") as file_handle:
            data = json.load(file_handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_vendor_catalog(vendor_catalog_data: dict) -> None:
    with open(VENDOR_FILE, "w") as file_handle:
        json.dump(vendor_catalog_data, file_handle, indent=2)


def save_payment_data(df: pd.DataFrame) -> None:
    df.to_csv(PAYMENT_FILE, index=False)


def parse_optional_rate(rate_value: str) -> float:
    text = str(rate_value).strip()
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def to_strict_title_case(text: str) -> str:
    cleaned_text = " ".join(str(text).strip().split())
    if not cleaned_text:
        return ""
    return " ".join(token[:1].upper() + token[1:].lower() for token in cleaned_text.split(" "))


def build_print_view_data_uri(print_html: str) -> str:
    if not print_html:
        return ""
    return f"data:text/html;charset=utf-8,{quote(print_html)}"


def render_controlled_table(df: pd.DataFrame, *, show_index: bool = False, max_height: Optional[int] = None) -> None:
    if df is None:
        st.info("No records available.")
        return

    table_df = df.copy().where(pd.notna(df), "")
    table_html = table_df.to_html(index=show_index, classes="prexa-table", border=0, escape=True)
    max_height_style = f"max-height:{int(max_height)}px;overflow:auto;" if max_height else ""
    st.markdown(
        f"<div class='prexa-table-wrap' style='{max_height_style}'>{table_html}</div>",
        unsafe_allow_html=True,
    )


def append_inward_record(
    entry_date: str,
    vendor: str,
    item: str,
    quantity: float,
    rate: float,
    payment_terms: str,
) -> float:
    total_amount = round(quantity * rate, 2)
    new_data = pd.DataFrame([
        {
            "Date": entry_date,
            "Vendor": vendor,
            "Item": item,
            "Quantity": quantity,
            "Unit Rate (PKR)": rate,
            "Total Amount (PKR)": total_amount,
            "Payment Terms": payment_terms,
        }
    ])
    new_data.to_csv(INWARD_FILE, mode="a", header=False, index=False)
    return total_amount


def load_inward_data() -> pd.DataFrame:
    if os.path.exists(INWARD_FILE):
        return pd.read_csv(INWARD_FILE)
    return pd.DataFrame()


def save_inward_data(df: pd.DataFrame) -> None:
    df.to_csv(INWARD_FILE, index=False)


def update_inward_record(
    row_id: int,
    entry_date: str,
    vendor: str,
    item: str,
    quantity: float,
    rate: float,
    payment_terms: str,
) -> None:
    df = load_inward_data()
    if row_id < 0 or row_id >= len(df):
        return

    total_amount = round(float(quantity) * float(rate), 2)
    df.loc[row_id, ["Date", "Vendor", "Item", "Quantity", "Unit Rate (PKR)", "Total Amount (PKR)", "Payment Terms"]] = [
        entry_date,
        vendor,
        item,
        float(quantity),
        float(rate),
        total_amount,
        payment_terms,
    ]
    save_inward_data(df)


def delete_inward_record(row_id: int) -> None:
    df = load_inward_data()
    if row_id < 0 or row_id >= len(df):
        return
    df = df.drop(index=row_id).reset_index(drop=True)
    save_inward_data(df)


def load_payments_data() -> pd.DataFrame:
    if os.path.exists(PAYMENT_FILE):
        return pd.read_csv(PAYMENT_FILE)
    return pd.DataFrame()


def update_payment_record(
    row_id: int,
    payment_date: str,
    vendor: str,
    amount_paid: float,
    payment_mode: str,
    payment_purpose: str,
    reference_notes: str,
) -> None:
    df = load_payments_data()
    if row_id < 0 or row_id >= len(df):
        return

    df.loc[row_id, [
        "Date",
        "Vendor",
        "Amount Paid (PKR)",
        "Payment Mode",
        "Payment Purpose / Description",
        "Reference / Notes",
    ]] = [
        payment_date,
        vendor,
        float(amount_paid),
        payment_mode,
        payment_purpose,
        reference_notes,
    ]
    save_payment_data(df)


def delete_payment_record(row_id: int) -> None:
    df = load_payments_data()
    if row_id < 0 or row_id >= len(df):
        return
    df = df.drop(index=row_id).reset_index(drop=True)
    save_payment_data(df)

def lookup_slip_by_barcode(code: str) -> Optional[dict]:
    code = str(code).strip()
    if not code:
        return None
    barcode_db = "slip_records.db"
    if not os.path.exists(barcode_db):
        return None

    try:
        conn = sqlite3.connect(barcode_db)
        cursor = conn.cursor()
        cursor.execute("SELECT vendor, item, quantity FROM slips WHERE slip_code = ?", (code,))
        row = cursor.fetchone()
        conn.close()
        if row:
            return {"Vendor": row[0], "Item": row[1], "Quantity": int(row[2])}
    except Exception:
        return None
    return None


def import_transactions_from_json(uploaded_file) -> tuple[bool, str]:
    """Import transactions from a JSON backup file into the `transactions` table.

    Returns a (success: bool, message: str) tuple.
    """
    if uploaded_file is None:
        return False, "No file provided."

    try:
        raw = uploaded_file.read()
        data = json.loads(raw)
    except Exception as exc:
        return False, f"Invalid JSON file: {exc}"

    # Accept either a top-level list, a dict wrapping the list (common keys: 'transactions', 'data'),
    # or a single transaction object.
    if isinstance(data, dict):
        # try common keys first
        for key in ("transactions", "data", "items", "records"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            # attempt to find the first nested list of dict-like objects anywhere in the dict
            def find_transactions_list(obj, depth=0, max_depth=4):
                if depth > max_depth:
                    return None
                if isinstance(obj, list):
                    # prefer lists of dicts
                    if all(isinstance(x, dict) for x in obj) and len(obj) > 0:
                        return obj
                    # if list elements are lists/dicts, try to find inside
                    for item in obj:
                        res = find_transactions_list(item, depth + 1, max_depth)
                        if res:
                            return res
                    return None
                if isinstance(obj, dict):
                    for v in obj.values():
                        res = find_transactions_list(v, depth + 1, max_depth)
                        if res:
                            return res
                return None

            found = find_transactions_list(data)
            if found is not None:
                data = found
            else:
                # if dict looks like a single transaction (has common transaction keys), wrap it
                tx_keys = {"date", "description", "amount", "category", "Date", "Description", "Amount", "Category"}
                if any(k in data for k in tx_keys):
                    data = [data]
                else:
                    return False, "JSON must be an array of transaction objects or contain one under a key like 'transactions' or 'data'."
    elif not isinstance(data, list):
        # if it's a single primitive or unexpected type, fail
        return False, "JSON must be an array of transaction objects or an object containing such an array."

    conn = None
    try:
        conn = get_connection()
        cur = conn.cursor()
        # ensure transactions table exists
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                description TEXT,
                amount REAL,
                category TEXT
            )
            """
        )

        inserted = 0
        for obj in data:
            if not isinstance(obj, dict):
                continue
            date_val = obj.get("date") or obj.get("Date") or ""
            description = obj.get("description") or obj.get("desc") or obj.get("Description") or ""
            amount = obj.get("amount") or obj.get("Amount") or 0.0
            category = obj.get("category") or obj.get("Category") or ""

            try:
                cur.execute(
                    "INSERT INTO transactions (date, description, amount, category) VALUES (?, ?, ?, ?)",
                    (str(date_val), description, float(amount or 0.0), category),
                )
                inserted += 1
            except Exception:
                # skip rows that fail conversion/constraints
                continue

        conn.commit()
        return True, f"Imported {inserted} transactions."
    except Exception as db_exc:
        return False, f"Database error: {db_exc}"
    finally:
        if conn:
            conn.close()


def build_backup_zip() -> tuple[bytes, str]:
    inward_df = pd.read_csv(INWARD_FILE) if os.path.exists(INWARD_FILE) else pd.DataFrame()
    payments_df = load_payments_data()
    vendors_data = {}
    if os.path.exists(VENDOR_FILE):
        with open(VENDOR_FILE, "r") as f:
            vendors_data = json.load(f)

    ledger_items = []
    for vendor in sorted(vendors_data.keys()):
        bill_rows = inward_df[inward_df["Vendor"] == vendor] if not inward_df.empty else pd.DataFrame()
        payment_rows = payments_df[payments_df["Vendor"] == vendor] if not payments_df.empty else pd.DataFrame()

        for _, row in bill_rows.iterrows():
            ledger_items.append({
                "Vendor": vendor,
                "Date": row.get("Date", ""),
                "Type": "Bill",
                "Reference": row.get("Item", ""),
                "Debit (PKR)": row.get("Total Amount (PKR)", 0.0),
                "Credit (PKR)": 0.0,
                "Description": row.get("Payment Terms", ""),
            })

        for _, row in payment_rows.iterrows():
            ledger_items.append({
                "Vendor": vendor,
                "Date": row.get("Date", ""),
                "Type": "Payment",
                "Reference": row.get("Voucher No", ""),
                "Debit (PKR)": 0.0,
                "Credit (PKR)": row.get("Amount Paid (PKR)", 0.0),
                "Description": row.get("Payment Purpose / Description", ""),
            })

    ledger_df = pd.DataFrame(ledger_items)
    backup_name = f"prexa_erp_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("inward_transactions.csv", inward_df.to_csv(index=False))
        zf.writestr("vendor_payments.csv", payments_df.to_csv(index=False))
        zf.writestr("vendor_catalog.json", json.dumps(vendors_data, indent=2))
        zf.writestr("vendor_ledger.csv", ledger_df.to_csv(index=False))

    return buffer.getvalue(), backup_name


def format_bill_label(row: pd.Series) -> str:
    date_label = row.get("Date", "")
    item_label = row.get("Item", "")
    amount_label = row.get("Total Amount (PKR)", 0.0)
    return f"{date_label} • {item_label} • PKR {amount_label:,.2f}"


def format_payment_label(row: pd.Series) -> str:
    date_label = row.get("Date", "")
    voucher_no = row.get("Voucher No", "")
    amount_label = row.get("Amount Paid (PKR)", 0.0)
    return f"{date_label} • {voucher_no} • PKR {amount_label:,.2f}"


def build_ledger_pdf(ledger_rows: list[dict], vendor: str, from_date: datetime.date, to_date: datetime.date) -> bytes:
    pdf = FPDF(orientation="L", format="A4")
    pdf.set_auto_page_break(auto=True, margin=10)
    pdf.set_left_margin(10)
    pdf.set_right_margin(10)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 14)
    pdf.cell(0, 10, f"Vendor Ledger - {vendor}", ln=True)
    pdf.set_font("Helvetica", "", 9)
    pdf.cell(0, 8, f"Period: {from_date} to {to_date}", ln=True)
    pdf.cell(0, 8, f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True)
    pdf.ln(4)

    def fit_text(text: str, max_width: float) -> str:
        text = str(text or "")
        if pdf.get_string_width(text) <= max_width:
            return text
        while text and pdf.get_string_width(text + "...") > max_width:
            text = text[:-1]
        return f"{text}..." if text else ""

    headers = ["Date", "Reference", "Description", "Debit", "Credit", "Balance"]
    widths = [24, 80, 120, 26, 26, 26]
    pdf.set_font("Helvetica", "B", 9)
    for header, width in zip(headers, widths):
        pdf.cell(width, 8, header, border=1, align="C")
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    for row in ledger_rows:
        date_text = fit_text(row.get("Date", ""), widths[0] - 2)
        ref_text = fit_text(row.get("Reference", ""), widths[1] - 2)
        desc_text = fit_text(row.get("Description", ""), widths[2] - 2)
        debit_text = f"{float(row.get('Debit (PKR)', 0.0)):.2f}"
        credit_text = f"{float(row.get('Credit (PKR)', 0.0)):.2f}"
        balance_text = f"{float(row.get('Balance (PKR)', 0.0)):.2f}"

        pdf.cell(widths[0], 6, date_text, border=1)
        pdf.cell(widths[1], 6, ref_text, border=1)
        pdf.cell(widths[2], 6, desc_text, border=1)
        pdf.cell(widths[3], 6, debit_text, border=1, align="R")
        pdf.cell(widths[4], 6, credit_text, border=1, align="R")
        pdf.cell(widths[5], 6, balance_text, border=1, align="R")
        pdf.ln()

    buffer = io.BytesIO()
    pdf_output = pdf.output(dest="S")
    if isinstance(pdf_output, str):
        pdf_bytes = pdf_output.encode("latin-1")
    elif isinstance(pdf_output, (bytes, bytearray)):
        pdf_bytes = bytes(pdf_output)
    else:
        raise TypeError(f"Unexpected FPDF output type: {type(pdf_output)}")
    buffer.write(pdf_bytes)
    buffer.seek(0)
    return buffer.read()


def aggregate_bill_rows(bills_df: pd.DataFrame) -> pd.DataFrame:
    if bills_df.empty:
        return bills_df.copy()

    df = bills_df.copy()
    if "row_id" in df.columns:
        df = df.drop(columns=["row_id"])

    group_cols = ["Item"]
    if "Payment Terms" in df.columns:
        group_cols.append("Payment Terms")

    if "Quantity" in df.columns:
        df["Quantity"] = pd.to_numeric(df["Quantity"], errors="coerce").fillna(0)
    if "Total Amount (PKR)" in df.columns:
        df["Total Amount (PKR)"] = pd.to_numeric(df["Total Amount (PKR)"], errors="coerce").fillna(0)

    if "Unit Rate (PKR)" in df.columns:
        df["Unit Rate (PKR)"] = pd.to_numeric(df["Unit Rate (PKR)"], errors="coerce").fillna(0)
        group_cols.append("Unit Rate (PKR)")
        aggregated = df.groupby(group_cols, dropna=False, as_index=False).agg(
            {
                "Quantity": "sum",
                "Total Amount (PKR)": "sum",
            }
        )
    else:
        aggregated = df.groupby(group_cols, dropna=False, as_index=False).agg(
            {
                "Quantity": "sum",
                "Total Amount (PKR)": "sum",
            }
        )

    if "Unit Rate (PKR)" in aggregated.columns:
        aggregated["Unit Rate (PKR)"] = aggregated["Unit Rate (PKR)"].round(2)
    if "Total Amount (PKR)" in aggregated.columns:
        aggregated["Total Amount (PKR)"] = aggregated["Total Amount (PKR)"].round(2)

    return aggregated


vendor_catalog = load_vendor_catalog()
init_slip_db()

# Sidebar Navigation
with st.sidebar:
    st.markdown("<div class='sidebar-brand'>PREXA INDUSTRIES</div>", unsafe_allow_html=True)
    st.markdown("<div class='sidebar-divider'></div>", unsafe_allow_html=True)
    st.markdown("<div class='sidebar-header'>🏢 MAIN SYSTEM MENU</div>", unsafe_allow_html=True)
    st.session_state.setdefault("app_selected_page", "Factory Store Slip")

    role_choice = st.radio(
        "Access role",
        options=["Store Staff", "Admin / Director"],
        index=0,
        key="access_role_selector",
    )

    admin_pin = DEFAULT_ADMIN_PIN
    is_admin = False
    if role_choice == "Admin / Director":
        entered_admin_pin = st.text_input("Admin PIN", type="password", key="admin_pin_input")
        if entered_admin_pin and entered_admin_pin == admin_pin:
            is_admin = True
        elif entered_admin_pin:
            st.error("Invalid admin PIN.")
        else:
            st.info("Enter admin PIN to unlock director view.")

    menu_pages = ADMIN_PAGES if is_admin else STORE_STAFF_PAGES
    icon_map = {
        "Dashboard": "speedometer2",
        "Factory Store Slip": "upc-scan",
        "Payments & Voucher": "receipt",
        "Vendor Bills": "journal-check",
        "Vendor Ledger": "journal-text",
        "Vendor Directory": "people-fill",
        "Items Catalog": "tags-fill",
        "Reports": "bar-chart-line",
    }
    menu_icons = [icon_map.get(page, "circle") for page in menu_pages]

    if st.session_state.app_selected_page not in menu_pages:
        st.session_state.app_selected_page = menu_pages[0]
    
    selected_page = option_menu(
        menu_title=None,
        options=menu_pages,
        icons=menu_icons,
        default_index=menu_pages.index(st.session_state.app_selected_page),
        styles={
            "container": {"padding": "0!important", "background-color": "transparent"},
            "icon": {"color": "#0088CC", "font-size": "18px"}, 
            "nav-link": {
                "font-size": "15px", 
                "font-weight": "700", 
                "text-align": "left", 
                "margin": "6px 0px", 
                "color": "#94A3B8",
                "padding": "12px 15px",
                "border-radius": "8px"
            },
            "nav-link-selected": {
                "background-color": "#1E3B8A", 
                "color": "#FFFFFF", 
                "font-weight": "800",
                "box-shadow": "0px 4px 10px rgba(30, 59, 138, 0.4)"
            },
        }
    )
    st.session_state.app_selected_page = selected_page

    if selected_page not in menu_pages:
        selected_page = menu_pages[0]
        st.session_state.app_selected_page = selected_page

    st.markdown("---")
    if is_admin and st.button("📦 Export Local Backup", use_container_width=True):
        backup_bytes, backup_name = build_backup_zip()
        st.download_button(
            label="Download ERP Backup",
            data=backup_bytes,
            file_name=backup_name,
            mime="application/zip",
            key="erp_backup_download"
        )
    st.caption("⚡ **Prexa ERP v2.0** | Professional Edition")

# Load Datasets
df_inward = pd.read_csv(INWARD_FILE)
df_payments = load_payments_data()

if not df_inward.empty:
    df_inward["Total Amount (PKR)"] = pd.to_numeric(df_inward["Total Amount (PKR)"], errors='coerce').fillna(0)
if not df_payments.empty:
    df_payments["Amount Paid (PKR)"] = pd.to_numeric(df_payments["Amount Paid (PKR)"], errors='coerce').fillna(0)

# 1. DASHBOARD
if selected_page == "Dashboard":
    st.markdown("<div style='margin-top: 20px;'></div>", unsafe_allow_html=True)
    st.markdown("### Business Overview & Accounting")

    total_purchases = df_inward["Total Amount (PKR)"].sum() if not df_inward.empty else 0.0
    total_paid = df_payments["Amount Paid (PKR)"].sum() if not df_payments.empty else 0.0
    balance_due = total_purchases - total_paid
    active_vendors = df_inward["Vendor"].nunique() if not df_inward.empty else 0

    col1, col2, col3, col4 = st.columns([1, 1, 1, 1], gap="small")
    with col1:
        st.markdown(
            f"<div class='metric-card accent-1'><h3>Total Purchases</h3><p class='metric-value'>PKR {total_purchases:,.2f}</p></div>",
            unsafe_allow_html=True,
        )
    with col2:
        st.markdown(
            f"<div class='metric-card accent-2'><h3>Total Payments</h3><p class='metric-value'>PKR {total_paid:,.2f}</p></div>",
            unsafe_allow_html=True,
        )
    with col3:
        st.markdown(
            f"<div class='metric-card accent-3'><h3>Total Payable Balance</h3><p class='metric-value'>PKR {balance_due:,.2f}</p></div>",
            unsafe_allow_html=True,
        )
    with col4:
        st.markdown(
            f"<div class='metric-card accent-4'><h3>Active Vendors</h3><p class='metric-value'>{active_vendors}</p></div>",
            unsafe_allow_html=True,
        )

    # Monthly purchase and payment trend charts
    df_trend_inward = df_inward.copy()
    df_trend_payments = df_payments.copy()
    if not df_trend_inward.empty:
        df_trend_inward["Date"] = pd.to_datetime(df_trend_inward["Date"], errors="coerce")
        df_trend_inward = df_trend_inward.dropna(subset=["Date"])
        df_trend_inward["Month"] = df_trend_inward["Date"].dt.to_period("M").dt.to_timestamp()
        monthly_purchases = (
            df_trend_inward.groupby("Month", as_index=False)["Total Amount (PKR)"].sum().rename(columns={"Total Amount (PKR)": "Purchases"})
        )
    else:
        monthly_purchases = pd.DataFrame({"Month": [], "Purchases": []})

    if not df_trend_payments.empty:
        df_trend_payments["Date"] = pd.to_datetime(df_trend_payments["Date"], errors="coerce")
        df_trend_payments = df_trend_payments.dropna(subset=["Date"])
        df_trend_payments["Month"] = df_trend_payments["Date"].dt.to_period("M").dt.to_timestamp()
        monthly_payments = (
            df_trend_payments.groupby("Month", as_index=False)["Amount Paid (PKR)"].sum().rename(columns={"Amount Paid (PKR)": "Payments"})
        )
    else:
        monthly_payments = pd.DataFrame({"Month": [], "Payments": []})

    monthly_trends = pd.merge(monthly_purchases, monthly_payments, on="Month", how="outer").sort_values("Month").fillna(0)
    if not monthly_trends.empty:
        monthly_trends = monthly_trends.set_index("Month")

    chart_col1, chart_col2 = st.columns(2, gap="small")
    with chart_col1:
        st.markdown("### Monthly Purchase Trend")
        if not monthly_trends.empty:
            st.line_chart(monthly_trends[["Purchases"]], height=180)
        else:
            st.info("No purchase trend data available.")
    with chart_col2:
        st.markdown("### Monthly Payment Trend")
        if not monthly_trends.empty:
            st.bar_chart(monthly_trends[["Payments"]], height=180)
        else:
            st.info("No payment trend data available.")

    st.markdown("<div class='panel-title'>Recent Activity</div>", unsafe_allow_html=True)

    recent_inwards = df_inward.sort_values("Date", ascending=False).head(5) if not df_inward.empty else pd.DataFrame()
    recent_payments = df_payments.sort_values("Date", ascending=False).head(5) if not df_payments.empty else pd.DataFrame()

    col_r1, col_r2 = st.columns(2)
    with col_r1:
        st.markdown("### Recent Bills")
        if not recent_inwards.empty:
            render_controlled_table(recent_inwards[["Date", "Vendor", "Item", "Total Amount (PKR)"]], max_height=230)
        else:
            st.info("No recent bills available.")
    with col_r2:
        st.markdown("### Recent Payments")
        if not recent_payments.empty:
            render_controlled_table(recent_payments[["Date", "Vendor", "Amount Paid (PKR)"]], max_height=230)
        else:
            st.info("No recent payments available.")

# 2. FACTORY STORE SLIP
elif selected_page == "Factory Store Slip":
    st.markdown("<div class='store-slip-shell'>", unsafe_allow_html=True)
    st.subheader("🏭 Factory Store Slip")
    st.caption("Generate unpriced store slips. Rate and total amount are hidden in this interface by design.")

    if not vendor_catalog:
        st.warning("No vendors are available in the catalog. Add vendors in Vendor Directory first.")
    else:
        vendor_options = sorted(vendor_catalog.keys())
        generate_slip = False
        print_slip_now = False
        with st.container(border=True):
            st.markdown("### Create a store slip")
            st.caption("Touch-friendly input layout for tablets and mobile screens.")
            with st.form("factory_slip_form", clear_on_submit=True):
                selected_slip_vendor = st.selectbox(
                    "Vendor",
                    options=vendor_options,
                    key="factory_slip_vendor_select",
                )
                slip_item_name = st.text_input(
                    "Item name",
                    key="factory_slip_item_input",
                    placeholder="Type item name",
                )
                slip_quantity = st.number_input(
                    "Quantity",
                    min_value=1,
                    value=1,
                    step=1,
                    key="factory_slip_quantity_input",
                )
                st.text_input(
                    "Date and time",
                    value=datetime.now().strftime("%Y-%m-%d %H:%M"),
                    disabled=True,
                )
                action_col1, action_col2 = st.columns(2)
                generate_slip = action_col1.form_submit_button("Generate and save slip")
                print_slip_now = action_col2.form_submit_button("🖨️ Print Slip")

        if print_slip_now:
            latest_print_html = st.session_state.get("factory_last_print_html", "")
            if not latest_print_html:
                st.warning("Generate at least one slip first, then tap Print Slip.")
            else:
                st.session_state.factory_last_print_view_uri = build_print_view_data_uri(latest_print_html)
                st.info("Mobile popup blockers can stop automatic printing. Use the open-print-view button below.")

        if generate_slip:
            normalized_item = to_strict_title_case(slip_item_name)
            if not normalized_item:
                st.error("Item name is required.")
            else:
                slip_code = uuid.uuid4().hex[:12].upper()
                created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
                slip_image = build_slip_image(
                    selected_slip_vendor,
                    normalized_item,
                    int(slip_quantity),
                    slip_code,
                    created_at,
                )

                slip_filename = os.path.join("slips", f"slip_{slip_code}.png")
                slip_image.save(slip_filename)
                save_slip_record(selected_slip_vendor, normalized_item, int(slip_quantity), slip_code, slip_filename)

                append_inward_record(
                    datetime.now().strftime("%Y-%m-%d"),
                    selected_slip_vendor,
                    normalized_item,
                    float(slip_quantity),
                    0.0,
                    "Pending Rate Review",
                )

                st.success("Slip generated and sent to Inward as an unpriced pending entry.")

                with st.container(border=True):
                    st.markdown("### Slip details")
                    st.text_input("Slip code", value=slip_code, disabled=True, key=f"slip_code_{slip_code}")
                    st.text_input("Date and time", value=created_at, disabled=True, key=f"slip_time_{slip_code}")
                    st.image(slip_image, caption="Factory store slip preview")

                    buffer = io.BytesIO()
                    slip_image.save(buffer, format="PNG")
                    buffer.seek(0)
                    st.download_button(
                        "Download slip PNG",
                        data=buffer,
                        file_name=f"slip_{slip_code}.png",
                        mime="image/png",
                        key=f"download_slip_{slip_code}",
                    )

                    barcode_uri = to_data_uri(build_barcode_image(slip_code, width=620, height=100))
                    print_layout_html = build_print_html(
                        selected_slip_vendor,
                        normalized_item,
                        int(slip_quantity),
                        slip_code,
                        created_at,
                        barcode_uri,
                    )
                    st.session_state.factory_last_print_html = print_layout_html
                    st.session_state.factory_last_slip_code = slip_code
                    st.session_state.factory_last_print_view_uri = build_print_view_data_uri(print_layout_html)

                    with st.expander("Open print-ready layout", expanded=False):
                        components.html(
                            print_layout_html,
                            height=620,
                        )

        latest_print_view_uri = st.session_state.get("factory_last_print_view_uri", "")
        latest_print_html = st.session_state.get("factory_last_print_html", "")
        if latest_print_view_uri and latest_print_html:
            st.markdown(
                f"""
                <a href="{latest_print_view_uri}" target="_blank" rel="noopener noreferrer" style="text-decoration:none;display:block;width:100%;">
                                    <button style="width:100%;min-height:52px;border-radius:14px;border:1px solid rgba(13,59,102,0.22);background:#ffffff;color:#000000;font-weight:700;font-size:15px;cursor:pointer;">
                    🖨️ Open printable view in new tab
                  </button>
                </a>
                """,
                unsafe_allow_html=True,
            )
            st.download_button(
                "Download printable HTML",
                data=latest_print_html,
                file_name="factory_slip_print.html",
                mime="text/html",
                key="download_printable_slip_html",
            )

    recent_slips = get_recent_slips(8)
    with st.container(border=True):
        st.subheader("Recent slips")
        if recent_slips:
            render_controlled_table(
                pd.DataFrame([
                    {
                        "Slip Code": row[0],
                        "Vendor": row[1],
                        "Item": row[2],
                        "Qty": row[3],
                        "Created": row[4],
                    }
                    for row in recent_slips
                ]),
                show_index=False,
            )
        else:
            st.info("No slips generated yet.")

    with st.container(border=True):
        st.subheader("📥 Inward records and rate assignment")
        st.caption("Handle barcode inward capture, manual inward entry, and final rate assignment here.")

    st.markdown("### 📷 Barcode scan / inward entry")
    with st.form("barcode_form", clear_on_submit=True):
        barcode_code = st.text_input(
            "Scan or enter slip barcode",
            value="",
            placeholder="Scan barcode here or type the slip code manually",
            key="barcode_code_input"
        )
        scan_btn = st.form_submit_button("Lookup & Record Slip")

    if scan_btn:
        slip = lookup_slip_by_barcode(barcode_code)
        if slip is None:
            st.error("Barcode not found or slip database unavailable.")
        else:
            st.session_state.pending_inward_barcode = {
                "slip_code": str(barcode_code).strip(),
                "vendor": slip["Vendor"],
                "item": slip["Item"],
                "quantity": int(slip["Quantity"]),
            }
            st.success(f"Barcode {st.session_state.pending_inward_barcode['slip_code']} loaded. Edit the rate or other fields below.")

    pending_slip = st.session_state.get("pending_inward_barcode")
    if pending_slip:
        with st.container(border=True):
            st.markdown("### Barcode entry details")
            st.caption("Edit the slip details before recording the inward entry. Leave the rate blank if you want to store it at zero for now.")
            with st.form("inward_barcode_entry_form", clear_on_submit=False):
                slip_date = st.date_input("Date", datetime.now(), key="inward_barcode_date")
                slip_vendor = st.text_input("Vendor", value=pending_slip["vendor"], key="inward_barcode_vendor")
                slip_item = st.text_input("Item", value=pending_slip["item"], key="inward_barcode_item")
                slip_quantity = st.number_input("Quantity", min_value=1, value=int(pending_slip["quantity"]), step=1, key="inward_barcode_quantity")
                slip_rate_default = float(vendor_catalog.get(slip_vendor, {}).get(slip_item, 0.0))
                slip_rate_raw = st.text_input(
                    "Rate (PKR)",
                    value=f"{slip_rate_default:.2f}" if slip_rate_default else "",
                    placeholder="Optional: enter a manual rate",
                    key="inward_barcode_rate",
                )
                slip_terms = st.selectbox("Payment Terms", ["Credit", "Cash", "Bank Transfer", "Cheque"], index=0, key="inward_barcode_terms")
                slip_record_btn = st.form_submit_button("Record inward entry")

            if slip_record_btn:
                slip_rate = parse_optional_rate(slip_rate_raw)
                total_amount = append_inward_record(
                    slip_date.strftime("%Y-%m-%d"),
                    slip_vendor.strip().title(),
                    slip_item.strip().title(),
                    float(slip_quantity),
                    slip_rate,
                    slip_terms,
                )
                if slip_rate == 0.0:
                    st.info("Recorded with a zero rate. You can edit the entry below to update the rate at any time.")
                else:
                    st.success(f"Inward entry recorded for {slip_vendor} / {slip_item} ({int(slip_quantity)} pcs) with PKR {total_amount:,.2f}.")
                st.session_state.pop("pending_inward_barcode", None)
                st.experimental_rerun()

            if st.button("Clear loaded entry", key="clear_pending_inward_barcode"):
                st.session_state.pop("pending_inward_barcode", None)
                st.experimental_rerun()

    with st.expander("Or enter inward entry manually"):
        with st.form("inward_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            
            with c1:
                entry_date = st.date_input("Date", datetime.now())
                selected_vendor = st.selectbox("Select Vendor", list(vendor_catalog.keys()))
                vendor_items = list(vendor_catalog[selected_vendor].keys()) if selected_vendor else []
                selected_item = st.selectbox("Select Item", vendor_items if vendor_items else ["No Items Available"])
                payment_terms = st.selectbox("Payment Terms", ["Credit", "Cash", "Bank Transfer", "Cheque"])

            with c2:
                default_rate = vendor_catalog[selected_vendor].get(selected_item, 0.0) if selected_vendor and selected_item in vendor_catalog[selected_vendor] else 0.0
                quantity = st.number_input("Quantity", min_value=1, value=10, step=1)
                rate_raw = st.text_input(
                    "Rate (PKR)",
                    value=f"{default_rate:.2f}" if default_rate else "",
                    placeholder="Optional: enter a manual rate",
                )
                
                rate = parse_optional_rate(rate_raw)
                total_amount = quantity * rate
                st.markdown(f"### **Total Amount: PKR {total_amount:,.2f}**")

            save_btn = st.form_submit_button("Save Inward Entry")

            if save_btn:
                if not selected_item or selected_item == "No Items Available":
                    st.error("Please select a valid item.")
                else:
                    append_inward_record(
                        entry_date.strftime("%Y-%m-%d"),
                        selected_vendor.strip().title(),
                        selected_item.strip().title(),
                        float(quantity),
                        rate,
                        payment_terms,
                    )
                    st.success("Inward entry saved successfully!")
                    st.rerun()

    st.markdown("---")
    st.subheader("📊 Recent Inward Records")
    render_controlled_table(df_inward, show_index=False)

    if not df_inward.empty:
        st.markdown("---")
        st.subheader("✏️ Manage Inward Records")
        inward_manage = df_inward.reset_index().rename(columns={"index": "row_id"})
        selected_inward = st.selectbox(
            "Select record to edit or delete",
            options=inward_manage["row_id"].tolist(),
            format_func=lambda rid: f"{inward_manage.loc[inward_manage['row_id'] == rid, 'Date'].iloc[0]} — {inward_manage.loc[inward_manage['row_id'] == rid, 'Vendor'].iloc[0]} / {inward_manage.loc[inward_manage['row_id'] == rid, 'Item'].iloc[0]}",
            key="manage_inward_select",
        )
        selected_row = inward_manage[inward_manage["row_id"] == selected_inward].iloc[0]
        with st.expander("Edit selected inward record"):
            edit_date = st.date_input(
                "Date",
                value=pd.to_datetime(selected_row["Date"], errors="coerce").date() if pd.notna(selected_row["Date"]) else datetime.now().date(),
                key="edit_inward_date",
            )
            edit_vendor = st.text_input("Vendor", value=selected_row["Vendor"], key="edit_inward_vendor")
            edit_item = st.text_input("Item", value=selected_row["Item"], key="edit_inward_item")
            edit_quantity = st.number_input("Quantity", min_value=0.0, value=float(selected_row["Quantity"]), step=1.0, key="edit_inward_quantity")
            edit_rate = st.number_input("Unit Rate (PKR)", min_value=0.0, value=float(selected_row["Unit Rate (PKR)"],), step=1.0, key="edit_inward_rate")
            edit_payment_terms = st.selectbox(
                "Payment Terms",
                ["Credit", "Cash", "Bank Transfer", "Cheque"],
                index=["Credit", "Cash", "Bank Transfer", "Cheque"].index(selected_row["Payment Terms"]) if selected_row["Payment Terms"] in ["Credit", "Cash", "Bank Transfer", "Cheque"] else 0,
                key="edit_inward_terms",
            )
            computed_total = round(edit_quantity * edit_rate, 2)
            st.markdown(f"**Computed Total Amount:** PKR {computed_total:,.2f}")
            if st.button("Save Inward Changes", key="save_inward_changes"):
                update_inward_record(
                    int(selected_inward),
                    edit_date.strftime("%Y-%m-%d"),
                    edit_vendor.strip().title(),
                    edit_item.strip().title(),
                    edit_quantity,
                    edit_rate,
                    edit_payment_terms,
                )
                st.success("Inward record updated successfully.")
                st.experimental_rerun()

        with st.expander("Delete selected inward record"):
            st.warning("This will permanently remove the selected inward record.")
            confirm_inward_delete = st.checkbox("I understand this action cannot be undone.", key="confirm_delete_inward")
            if confirm_inward_delete and st.button("Delete Inward Record", key="delete_inward_record"):
                delete_inward_record(int(selected_inward))
                st.success("Inward record deleted successfully.")
                st.experimental_rerun()

    st.markdown("</div>", unsafe_allow_html=True)

# 3. PAYMENTS & VOUCHER
elif selected_page == "Payments & Voucher":
    st.subheader("💳 Vendor Payments & Voucher Generator")

    col_pay1, col_pay2 = st.columns([1, 1])

    with col_pay1:
        st.markdown("### 💵 Record Payment & Create Voucher")
        next_v_num = f"PV-{len(df_payments) + 1001}"
        
        with st.form("payment_form", clear_on_submit=False):
            st.info(f"**Generated Voucher No:** {next_v_num}")
            p_date = st.date_input("Payment Date", datetime.now())
            p_vendor = st.selectbox("Vendor Name", list(vendor_catalog.keys()), key="p_v")
            p_amount = st.number_input("Amount Paid (PKR)", min_value=1.0, step=500.0)
            p_mode = st.selectbox("Payment Mode", ["Cash", "Bank Transfer", "Cheque", "Online"])
            p_purpose = st.text_area("Payment Purpose / Description", placeholder="E.g. Payment for Iris Scissors")
            p_notes = st.text_input("Reference / Notes", placeholder="Cheque No / Bank Ref")

            pay_btn = st.form_submit_button("Save Payment & Generate Voucher")

            if pay_btn:
                new_pay = pd.DataFrame([{
                    "Voucher No": next_v_num,
                    "Date": p_date.strftime("%Y-%m-%d"),
                    "Vendor": p_vendor,
                    "Amount Paid (PKR)": p_amount,
                    "Payment Mode": p_mode,
                    "Payment Purpose / Description": p_purpose if p_purpose else "Payment Made against Inward/Job",
                    "Reference / Notes": p_notes if p_notes else "-"
                }])
                new_pay.to_csv(PAYMENT_FILE, mode='a', header=False, index=False)
                st.session_state['selected_voucher'] = next_v_num
                st.success(f"✅ Payment Saved! Voucher {next_v_num} created successfully.")
                st.rerun()

    with col_pay2:
        st.markdown("### 🔍 Select Vendor Ledger View")
        selected_ledger_vendor = st.selectbox("Choose Vendor", list(vendor_catalog.keys()), key="ledger_v")

        v_inwards = df_inward[df_inward["Vendor"] == selected_ledger_vendor] if not df_inward.empty else pd.DataFrame()
        v_pays = df_payments[df_payments["Vendor"] == selected_ledger_vendor] if not df_payments.empty else pd.DataFrame()

        total_in = v_inwards["Total Amount (PKR)"].sum() if not v_inwards.empty else 0.0
        total_out = v_pays["Amount Paid (PKR)"].sum() if not v_pays.empty else 0.0
        net_bal = total_in - total_out

        st.info(f"**Total Purchases:** PKR {total_in:,.2f} | **Total Paid:** PKR {total_out:,.2f}")
        if net_bal > 0:
            st.warning(f"**Net Outstanding Payable:** PKR {net_bal:,.2f}")
        else:
            st.success(f"**Account Clear / Advance:** PKR {abs(net_bal):,.2f}")

    st.markdown("---")
    st.markdown("### 📄 Payment Voucher Preview & Print")
    
    df_payments_current = load_payments_data()
    
    if not df_payments_current.empty:
        voucher_options = df_payments_current["Voucher No"].tolist()
        default_index = len(voucher_options) - 1
        if 'selected_voucher' in st.session_state and st.session_state['selected_voucher'] in voucher_options:
            default_index = voucher_options.index(st.session_state['selected_voucher'])

        selected_v_no = st.selectbox("Select Voucher to Print:", voucher_options, index=default_index)
        v_row = df_payments_current[df_payments_current["Voucher No"] == selected_v_no].iloc[0]

        voucher_html = f"""
        <div class='voucher-box'>
            <div style='display:flex; justify-content:space-between; align-items:center;'>
                <div>
                    <h2 style='color:#000000; margin:0; font-weight:800; font-size:24px;'>PREXA INDUSTRIES</h2>
                    <p style='margin:0; font-size:12px; color:#000000;'>Surgical, Dental & Manicure Instruments</p>
                    <p style='margin:0; font-size:12px; color:#000000;'>2Km Kingra Road Kakeywali, Sialkot - Pakistan</p>
                </div>
                <div style='text-align:right;'>
                    <h3 style='margin:0; color:#000000; text-decoration: underline; font-size:18px;'>PAYMENT VOUCHER</h3>
                    <p style='margin:4px 0 0 0; font-weight:bold; font-size:14px;'>Voucher No: {v_row.get('Voucher No', 'N/A')}</p>
                    <p style='margin:0; font-size:12px;'>Date: {v_row.get('Date', 'N/A')}</p>
                </div>
            </div>
            <hr style='border:1px solid #1E3B8A; margin:10px 0;'>
            <table class='voucher-table'>
                <tr>
                    <td style='width:50%;'><strong>Paid To (Vendor / Contractor):</strong><br><span style='font-size:15px;'>{v_row.get('Vendor', '')}</span></td>
                    <td style='width:50%;'><strong>Payment Mode:</strong><br>{v_row.get('Payment Mode', '')}</td>
                </tr>
                <tr>
                    <td colspan='2' style='background-color: #F8FAFC;'><strong>Amount Paid:</strong><br><span style='font-size:20px; font-weight:bold; color:#000000;'>PKR {float(v_row.get('Amount Paid (PKR)', 0)):,.2f}</span></td>
                </tr>
                <tr>
                    <td colspan='2'><strong>Payment Purpose / Description:</strong><br><span style='font-size:14px;'>{v_row.get('Payment Purpose / Description', '')}</span></td>
                </tr>
                <tr>
                    <td colspan='2'><strong>Reference / Bank / Cheque Details:</strong><br>{v_row.get('Reference / Notes', '-')}</td>
                </tr>
            </table>
            <div class='sig-space'>
                <div class='sig-line'>Prepared / Paid By (Cashier)</div>
                <div class='sig-line'>Approved By (Manager)</div>
                <div class='sig-line'>Vendor Receiver Signature</div>
            </div>
        </div>
        """
        st.markdown(voucher_html, unsafe_allow_html=True)

        voucher_print_html = f"""
        <html>
            <head>
                <meta charset='utf-8'>
                <meta name='viewport' content='width=device-width, initial-scale=1.0'>
                <title>Payment Voucher {v_row.get('Voucher No', 'N/A')}</title>
                <style>
                    body {{
                        margin: 0;
                        padding: 16px;
                        background: #ffffff;
                        color: #000000;
                        font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
                    }}
                    .print-shell {{ max-width: 900px; margin: 0 auto; }}
                    .voucher-box {{ border: 1px solid rgba(15, 23, 42, 0.14); border-radius: 14px; box-shadow: none; }}
                    .voucher-table {{ width: 100%; border-collapse: collapse; }}
                    .voucher-table td, .voucher-table th {{ border: 1px solid rgba(148, 163, 184, 0.25); color: #000000; }}
                    .sig-line {{ color: #000000; }}
                </style>
            </head>
            <body>
                <div class='print-shell'>
                    {voucher_html}
                </div>
            </body>
        </html>
        """

        voucher_print_uri = build_print_view_data_uri(voucher_print_html)
        st.markdown(
            f"""
            <a href="{voucher_print_uri}" target="_blank" rel="noopener noreferrer" style="text-decoration:none;display:block;width:100%;">
                <button style="width:100%;min-height:48px;border-radius:12px;border:1px solid rgba(13,59,102,0.22);background:#ffffff;color:#000000;font-weight:700;font-size:14px;cursor:pointer;">
                    🖨️ Open voucher printable view in new tab
                </button>
            </a>
            """,
            unsafe_allow_html=True,
        )
        st.download_button(
            "Download voucher printable HTML",
            data=voucher_print_html,
            file_name=f"voucher_{v_row.get('Voucher No', 'N_A')}.html",
            mime="text/html",
            key=f"download_voucher_html_{selected_v_no}",
        )

    st.markdown("---")
    st.markdown(f"### 📑 Account History for **{selected_ledger_vendor}**")
    t1, t2 = st.tabs(["📦 Inward Bills History", "💵 Payment History"])
    with t1:
        render_controlled_table(v_inwards, show_index=False)
    with t2:
        render_controlled_table(v_pays, show_index=False)

    if not df_payments_current.empty:
        st.markdown("---")
        st.subheader("✏️ Manage Payments")
        payments_manage = df_payments_current.reset_index().rename(columns={"index": "row_id"})
        selected_payment = st.selectbox(
            "Select payment to edit or delete",
            options=payments_manage["row_id"].tolist(),
            format_func=lambda rid: f"{payments_manage.loc[payments_manage['row_id'] == rid, 'Date'].iloc[0]} — {payments_manage.loc[payments_manage['row_id'] == rid, 'Vendor'].iloc[0]} / {payments_manage.loc[payments_manage['row_id'] == rid, 'Voucher No'].iloc[0]}",
            key="manage_payment_select",
        )
        payment_row = payments_manage[payments_manage["row_id"] == selected_payment].iloc[0]

        with st.expander("Edit selected payment"):
            edit_p_date = st.date_input(
                "Payment Date",
                value=pd.to_datetime(payment_row["Date"], errors="coerce").date() if pd.notna(payment_row["Date"]) else datetime.now().date(),
                key="edit_payment_date",
            )
            edit_p_vendor = st.text_input("Vendor", value=payment_row["Vendor"], key="edit_payment_vendor")
            edit_p_amount = st.number_input("Amount Paid (PKR)", min_value=0.0, value=float(payment_row["Amount Paid (PKR)"],), step=1.0, key="edit_payment_amount")
            edit_p_mode = st.selectbox(
                "Payment Mode",
                ["Cash", "Bank Transfer", "Cheque", "Online"],
                index=["Cash", "Bank Transfer", "Cheque", "Online"].index(payment_row["Payment Mode"]) if payment_row["Payment Mode"] in ["Cash", "Bank Transfer", "Cheque", "Online"] else 0,
                key="edit_payment_mode",
            )
            edit_purpose = st.text_area("Payment Purpose / Description", value=payment_row["Payment Purpose / Description"], key="edit_payment_purpose")
            edit_notes = st.text_input("Reference / Notes", value=payment_row["Reference / Notes"], key="edit_payment_notes")
            if st.button("Save Payment Changes", key="save_payment_changes"):
                update_payment_record(
                    int(selected_payment),
                    edit_p_date.strftime("%Y-%m-%d"),
                    edit_p_vendor.strip().title(),
                    edit_p_amount,
                    edit_p_mode,
                    edit_purpose,
                    edit_notes,
                )
                st.success("Payment record updated successfully.")
                st.experimental_rerun()

        with st.expander("Delete selected payment"):
            st.warning("This will permanently remove the selected payment record.")
            confirm_payment_delete = st.checkbox("I understand this action cannot be undone.", key="confirm_delete_payment")
            if confirm_payment_delete and st.button("Delete Payment Record", key="delete_payment_record"):
                delete_payment_record(int(selected_payment))
                st.success("Payment record deleted successfully.")
                st.experimental_rerun()

# 5. VENDOR BILLS
elif selected_page == "Vendor Bills":
    st.subheader("🧾 Vendor Bills")
    st.caption("Review, edit, and delete inward bills and payment records for each vendor.")

    if not vendor_catalog:
        st.warning("No vendors available yet.")
    else:
        selected_vendor = st.selectbox("Select Vendor", sorted(vendor_catalog.keys()), key="vendor_bills_vendor")
        v_inwards = df_inward[df_inward["Vendor"] == selected_vendor].copy() if not df_inward.empty else pd.DataFrame(columns=df_inward.columns)
        v_payments = df_payments[df_payments["Vendor"] == selected_vendor].copy() if not df_payments.empty else pd.DataFrame(columns=df_payments.columns)

        total_bills = v_inwards["Total Amount (PKR)"].sum() if not v_inwards.empty else 0.0
        total_paid = v_payments["Amount Paid (PKR)"].sum() if not v_payments.empty else 0.0
        remaining_balance = total_bills - total_paid

        st.markdown("<div class='kpi-group'>", unsafe_allow_html=True)
        st.markdown(f"<div class='kpi-card'><h3>Vendor inward bills</h3><p class='kpi-value'>PKR {total_bills:,.2f}</p></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='kpi-card'><h3>Vendor payments</h3><p class='kpi-value'>PKR {total_paid:,.2f}</p></div>", unsafe_allow_html=True)
        balance_class = 'kpi-card warning' if remaining_balance > 0 else 'kpi-card'
        st.markdown(f"<div class='{balance_class}'><h3>Current balance</h3><p class='kpi-value'>PKR {remaining_balance:,.2f}</p></div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        bills_tab, payments_tab = st.tabs(["Bills", "Payments"])

        with bills_tab:
            if v_inwards.empty:
                st.info("No vendor bills found.")
            else:
                bills_df = v_inwards.reset_index(drop=False).rename(columns={"index": "row_id"})
                render_controlled_table(
                    bills_df[["row_id", "Date", "Item", "Quantity", "Unit Rate (PKR)", "Total Amount (PKR)", "Payment Terms"]],
                    show_index=False,
                )

                selected_bill_id = st.selectbox(
                    "Select bill to edit or delete",
                    options=bills_df["row_id"].tolist(),
                    format_func=lambda idx: format_bill_label(bills_df.loc[bills_df["row_id"] == idx].iloc[0]),
                    key="vendor_bill_select",
                )
                selected_bill = bills_df[bills_df["row_id"] == selected_bill_id].iloc[0]

                with st.expander("Edit selected bill"):
                    edit_date = st.date_input("Bill date", value=pd.to_datetime(selected_bill["Date"], errors="coerce").date() if pd.notna(selected_bill["Date"]) else datetime.now().date(), key=f"edit_bill_date_{selected_bill_id}")
                    edit_item = st.text_input("Item", value=selected_bill["Item"], key=f"edit_bill_item_{selected_bill_id}")
                    edit_quantity = st.number_input("Quantity", min_value=0.0, value=float(selected_bill["Quantity"]), step=1.0, key=f"edit_bill_quantity_{selected_bill_id}")
                    edit_rate_raw = st.text_input(
                        "Unit rate (PKR)",
                        value=f"{float(selected_bill['Unit Rate (PKR)']):.2f}" if float(selected_bill["Unit Rate (PKR)"]) else "",
                        placeholder="Optional: enter or change the rate",
                        key=f"edit_bill_rate_{selected_bill_id}",
                    )
                    edit_rate = parse_optional_rate(edit_rate_raw)
                    edit_payment_terms = st.selectbox(
                        "Payment terms",
                        ["Credit", "Cash", "Bank Transfer", "Cheque"],
                        index=["Credit", "Cash", "Bank Transfer", "Cheque"].index(selected_bill["Payment Terms"]) if selected_bill["Payment Terms"] in ["Credit", "Cash", "Bank Transfer", "Cheque"] else 0,
                        key=f"edit_bill_terms_{selected_bill_id}",
                    )
                    edit_total = round(edit_quantity * edit_rate, 2)
                    st.markdown(f"**Computed total:** PKR {edit_total:,.2f}")
                    if st.button("Save bill changes", key=f"save_bill_changes_{selected_bill_id}"):
                        df_inward.loc[selected_bill_id, ["Date", "Item", "Quantity", "Unit Rate (PKR)", "Total Amount (PKR)", "Payment Terms"]] = [
                            edit_date.strftime("%Y-%m-%d"),
                            edit_item.strip().title(),
                            edit_quantity,
                            edit_rate,
                            edit_total,
                            edit_payment_terms,
                        ]
                        save_inward_data(df_inward)
                        st.success("Bill updated successfully.")
                        st.rerun()

                with st.expander("Delete selected bill"):
                    st.warning("This will permanently delete the selected bill.")
                    confirm_bill_delete = st.checkbox("I understand this action cannot be undone.", key=f"confirm_delete_bill_{selected_bill_id}")
                    if confirm_bill_delete and st.button("Delete bill", key=f"delete_bill_{selected_bill_id}"):
                        df_inward.drop(index=selected_bill_id, inplace=True)
                        save_inward_data(df_inward)
                        st.success("Bill deleted successfully.")
                        st.rerun()

        with payments_tab:
            if v_payments.empty:
                st.info("No vendor payments found.")
            else:
                payments_df = v_payments.reset_index(drop=False).rename(columns={"index": "row_id"})
                render_controlled_table(
                    payments_df[["row_id", "Voucher No", "Date", "Amount Paid (PKR)", "Payment Mode", "Payment Purpose / Description"]],
                    show_index=False,
                )

                selected_payment_id = st.selectbox(
                    "Select payment to edit or delete",
                    options=payments_df["row_id"].tolist(),
                    format_func=lambda idx: format_payment_label(payments_df.loc[payments_df["row_id"] == idx].iloc[0]),
                    key="vendor_payment_select",
                )
                selected_payment = payments_df[payments_df["row_id"] == selected_payment_id].iloc[0]

                with st.expander("Edit selected payment"):
                    edit_p_date = st.date_input("Payment date", value=pd.to_datetime(selected_payment["Date"], errors="coerce").date() if pd.notna(selected_payment["Date"]) else datetime.now().date(), key=f"edit_payment_date_{selected_payment_id}")
                    edit_p_amount = st.number_input("Amount paid (PKR)", min_value=0.0, value=float(selected_payment["Amount Paid (PKR)"]), step=1.0, key=f"edit_payment_amount_{selected_payment_id}")
                    edit_p_mode = st.selectbox(
                        "Payment mode",
                        ["Cash", "Bank Transfer", "Cheque", "Online"],
                        index=["Cash", "Bank Transfer", "Cheque", "Online"].index(selected_payment["Payment Mode"]) if selected_payment["Payment Mode"] in ["Cash", "Bank Transfer", "Cheque", "Online"] else 0,
                        key=f"edit_payment_mode_{selected_payment_id}",
                    )
                    edit_purpose = st.text_area("Payment purpose / description", value=selected_payment["Payment Purpose / Description"], key=f"edit_payment_purpose_{selected_payment_id}")
                    edit_notes = st.text_input("Reference / notes", value=selected_payment["Reference / Notes"], key=f"edit_payment_notes_{selected_payment_id}")
                    if st.button("Save payment changes", key=f"save_payment_changes_{selected_payment_id}"):
                        df_payments.loc[selected_payment_id, ["Date", "Amount Paid (PKR)", "Payment Mode", "Payment Purpose / Description", "Reference / Notes"]] = [
                            edit_p_date.strftime("%Y-%m-%d"),
                            edit_p_amount,
                            edit_p_mode,
                            edit_purpose,
                            edit_notes,
                        ]
                        save_payment_data(df_payments)
                        st.success("Payment updated successfully.")
                        st.rerun()

                with st.expander("Delete selected payment"):
                    st.warning("This will permanently delete the selected payment.")
                    confirm_payment_delete = st.checkbox("I understand this action cannot be undone.", key=f"confirm_delete_payment_{selected_payment_id}")
                    if confirm_payment_delete and st.button("Delete payment", key=f"delete_payment_{selected_payment_id}"):
                        df_payments.drop(index=selected_payment_id, inplace=True)
                        save_payment_data(df_payments)
                        st.success("Payment deleted successfully.")
                        st.rerun()

# 5. VENDOR LEDGER
elif selected_page == "Vendor Ledger":
    st.subheader("📘 Vendor Ledger")
    st.caption("View a dedicated vendor ledger with debit, credit and running balances.")

    if not vendor_catalog:
        st.warning("No vendors available yet.")
    else:
        selected_vendor = st.selectbox("Select Vendor", sorted(vendor_catalog.keys()))
        v_inwards = df_inward[df_inward["Vendor"] == selected_vendor].copy() if not df_inward.empty else pd.DataFrame(columns=df_inward.columns)
        v_payments = df_payments[df_payments["Vendor"] == selected_vendor].copy() if not df_payments.empty else pd.DataFrame(columns=df_payments.columns)

        if "Date" in v_inwards.columns:
            v_inwards["Date"] = pd.to_datetime(v_inwards["Date"], errors="coerce")
        if "Date" in v_payments.columns:
            v_payments["Date"] = pd.to_datetime(v_payments["Date"], errors="coerce")

        col_filter1, col_filter2 = st.columns(2)
        with col_filter1:
            from_date = st.date_input("From Date", value=datetime.now().date().replace(day=1), key="ledger_from_date")
        with col_filter2:
            to_date = st.date_input("To Date", value=datetime.now().date(), key="ledger_to_date")

        if from_date > to_date:
            st.error("From Date cannot be later than To Date.")
            filtered_inwards = pd.DataFrame(columns=v_inwards.columns)
            filtered_payments = pd.DataFrame(columns=v_payments.columns)
        else:
            filtered_inwards = v_inwards[
                (v_inwards["Date"].dt.date >= from_date) &
                (v_inwards["Date"].dt.date <= to_date)
            ] if not v_inwards.empty else pd.DataFrame(columns=v_inwards.columns)
            filtered_payments = v_payments[
                (v_payments["Date"].dt.date >= from_date) &
                (v_payments["Date"].dt.date <= to_date)
            ] if not v_payments.empty else pd.DataFrame(columns=v_payments.columns)

        history = []
        if not filtered_inwards.empty:
            for _, row in filtered_inwards.sort_values("Date", ascending=True).iterrows():
                history.append({
                    "Date": row["Date"].strftime("%Y-%m-%d") if not pd.isna(row["Date"]) else "",
                    "Description": f"Inward bill for {row.get('Item', 'goods')}",
                    "Reference": row.get("Item", "Inward Entry"),
                    "Debit (PKR)": row.get("Total Amount (PKR)", 0.0),
                    "Credit (PKR)": 0.0,
                })
        if not filtered_payments.empty:
            for _, row in filtered_payments.sort_values("Date", ascending=True).iterrows():
                history.append({
                    "Date": row["Date"].strftime("%Y-%m-%d") if not pd.isna(row["Date"]) else "",
                    "Description": row.get("Payment Purpose / Description", "Vendor payment"),
                    "Reference": row.get("Voucher No", "Payment"),
                    "Debit (PKR)": 0.0,
                    "Credit (PKR)": row.get("Amount Paid (PKR)", 0.0),
                })

        vendor_balance = 0.0
        ledger_rows = []
        for row in sorted(history, key=lambda x: (x.get("Date", ""), x.get("Reference", ""))):
            vendor_balance = round(vendor_balance + float(row.get("Debit (PKR)", 0.0)) - float(row.get("Credit (PKR)", 0.0)), 2)
            ledger_rows.append({
                "Date": row.get("Date", ""),
                "Reference": row.get("Reference", ""),
                "Description": row.get("Description", ""),
                "Debit (PKR)": row.get("Debit (PKR)", 0.0),
                "Credit (PKR)": row.get("Credit (PKR)", 0.0),
                "Balance (PKR)": vendor_balance,
            })

        st.markdown("<div class='ledger-card'>", unsafe_allow_html=True)
        if ledger_rows:
            ledger_df = pd.DataFrame(ledger_rows)
            render_controlled_table(ledger_df, show_index=False)
            col_print, col_pdf = st.columns([1, 1])
            with col_print:
                if st.button("Open Print View"):
                    html = f"""
                    <html>
                      <head>
                        <meta charset='utf-8'>
                        <style>
                          body {{ font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 24px; background: #fff; color: #000000; }}
                          h1 {{ font-size: 24px; margin-bottom: 8px; }}
                          table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
                          th, td {{ border: 1px solid #ddd; padding: 10px; font-size: 13px; }}
                          th {{ background: #f4f6fb; text-align: left; }}
                        </style>
                      </head>
                      <body onload='window.print()'>
                        <h1>Vendor Ledger - {selected_vendor}</h1>
                        <p><strong>Period:</strong> {from_date} to {to_date}</p>
                        <p><strong>Generated:</strong> {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
                        {ledger_df.to_html(index=False)}
                      </body>
                    </html>
                    """
                    components.html(html, height=700)
            with col_pdf:
                if FPDF_AVAILABLE:
                    pdf_bytes = build_ledger_pdf(ledger_rows, selected_vendor, from_date, to_date)
                    st.download_button(
                        "Download PDF",
                        data=pdf_bytes,
                        file_name=f"ledger_{selected_vendor}_{from_date}_to_{to_date}.pdf",
                        mime="application/pdf",
                    )
                else:
                    st.info("Install fpdf2 to enable PDF export.")
        else:
            st.info("No ledger entries are available for this vendor for the selected date range.")
        st.markdown("</div>", unsafe_allow_html=True)

# 6. REPORTS
elif selected_page == "Reports":
    st.subheader("📈 Reports")
    st.caption("Review financial reports and vendor performance across the ERP.")

    total_vendors = len(vendor_catalog)
    invoice_count = len(df_inward)
    payment_count = len(df_payments)
    avg_payment = df_payments["Amount Paid (PKR)"].mean() if not df_payments.empty else 0.0

    st.markdown("<div class='kpi-group'>", unsafe_allow_html=True)
    st.markdown(f"<div class='kpi-card'><h3>Total Vendors</h3><p class='kpi-value'>{total_vendors}</p></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='kpi-card'><h3>Total Invoices</h3><p class='kpi-value'>{invoice_count}</p></div>", unsafe_allow_html=True)
    st.markdown(f"<div class='kpi-card'><h3>Average Payment</h3><p class='kpi-value'>PKR {avg_payment:,.2f}</p></div>", unsafe_allow_html=True)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='panel-content'>", unsafe_allow_html=True)
    st.markdown("<div class='panel-title'>Vendor Balances Report</div>", unsafe_allow_html=True)
    balances = []
    for vendor in sorted(vendor_catalog.keys()):
        v_total = df_inward[df_inward["Vendor"] == vendor]["Total Amount (PKR)"].sum() if not df_inward.empty else 0.0
        v_paid = df_payments[df_payments["Vendor"] == vendor]["Amount Paid (PKR)"].sum() if not df_payments.empty else 0.0
        balances.append({
            "Vendor": vendor,
            "Total Billed": v_total,
            "Total Paid": v_paid,
            "Balance": v_total - v_paid,
        })
    render_controlled_table(pd.DataFrame(balances).sort_values("Balance", ascending=False), show_index=False)
    st.markdown("</div>", unsafe_allow_html=True)

    st.markdown("<div class='panel-content'>", unsafe_allow_html=True)
    st.markdown("<div class='panel-title'>Import Transactions (JSON Backup)</div>", unsafe_allow_html=True)
    uploaded = st.file_uploader("Upload JSON backup file", type=["json"], help="Upload an array of transaction objects with keys: date, description, amount, category")
    if uploaded is not None:
        with st.spinner("Importing transactions..."):
            ok, msg = import_transactions_from_json(uploaded)
        if ok:
            st.success(msg)
        else:
            st.error(msg)
    st.markdown("</div>", unsafe_allow_html=True)

# 5. VENDOR DIRECTORY
elif selected_page == "Vendor Directory":
    st.subheader("👥 Vendor Management")
    col_v1, col_v2 = st.columns([2, 1])
    
    with col_v1:
        st.markdown("### 📋 All Vendors List")
        vendors_summary = [{"Vendor Name": v_name, "Total Items Registered": len(items)} for v_name, items in vendor_catalog.items()]
        render_controlled_table(pd.DataFrame(vendors_summary), show_index=False)

    with col_v2:
        st.markdown("### ➕ Add New Vendor")
        with st.form("add_vendor_form", clear_on_submit=True):
            new_v = st.text_input("Enter Vendor Name:")
            add_v_btn = st.form_submit_button("Add Vendor")
            if add_v_btn and new_v:
                if new_v not in vendor_catalog:
                    vendor_catalog[new_v] = {}
                    save_vendor_catalog(vendor_catalog)
                    st.success(f"Vendor '{new_v}' added successfully!")
                    st.rerun()

# 5. ITEMS CATALOG
elif selected_page == "Items Catalog":
    st.subheader("📦 Vendor Items & Rates Catalog")
    col_i1, col_i2 = st.columns([2, 1])
    
    with col_i1:
        filter_vendor = st.selectbox("Filter Items by Vendor:", ["All Vendors"] + list(vendor_catalog.keys()))
        items_data = []
        for v_name, items in vendor_catalog.items():
            if filter_vendor == "All Vendors" or filter_vendor == v_name:
                for item_name, item_rate in items.items():
                    items_data.append({"Vendor": v_name, "Item Name": item_name, "Rate (PKR)": item_rate})
        render_controlled_table(pd.DataFrame(items_data), show_index=False)

    with col_i2:
        st.markdown("### ➕ Add New Item / Rate")
        with st.form("add_item_form", clear_on_submit=True):
            target_v = st.selectbox("Select Vendor:", list(vendor_catalog.keys()))
            item_n = st.text_input("Item Name:")
            item_r = st.number_input("Rate (PKR):", min_value=0.0, step=5.0)
            add_i_btn = st.form_submit_button("Add Item")
            if add_i_btn and item_n:
                vendor_catalog[target_v][item_n] = item_r
                save_vendor_catalog(vendor_catalog)
                st.success(f"Item '{item_n}' added successfully!")
                st.rerun()