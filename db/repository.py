"""Data access layer for accounting operations."""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from db.database import get_connection

PREFIX_MAP = {
    "inward": "INR",
    "bill": "BILL",
    "payment": "PAY",
}


def _next_number(conn: sqlite3.Connection, counter_name: str) -> str:
    prefix = PREFIX_MAP[counter_name]
    row = conn.execute(
        "SELECT value FROM counters WHERE name = ?",
        (counter_name,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown counter: {counter_name}")

    next_value = int(row["value"]) + 1
    conn.execute(
        "UPDATE counters SET value = ? WHERE name = ?",
        (next_value, counter_name),
    )
    return f"{prefix}-{next_value}"


def get_or_create_vendor(conn: sqlite3.Connection, name: str) -> int:
    name = name.strip()
    if not name:
        raise ValueError("Vendor name is required.")

    row = conn.execute(
        "SELECT id FROM vendors WHERE lower(name) = lower(?)",
        (name,),
    ).fetchone()
    if row:
        return int(row["id"])

    cursor = conn.execute(
        "INSERT INTO vendors (name) VALUES (?)",
        (name,),
    )
    return int(cursor.lastrowid)


def list_vendors(conn: sqlite3.Connection | None = None) -> list[sqlite3.Row]:
    conn = conn or get_connection()
    return conn.execute(
        "SELECT id, name, contact, address FROM vendors ORDER BY name"
    ).fetchall()


def create_inward_receipt(
    receipt_date: date,
    vendor_name: str,
    item_name: str,
    quantity: float,
    rate: float,
) -> dict[str, Any]:
    if quantity <= 0 or rate < 0:
        raise ValueError("Quantity must be positive and rate cannot be negative.")

    total = round(quantity * rate, 2)
    conn = get_connection()

    try:
        vendor_id = get_or_create_vendor(conn, vendor_name)
        receipt_no = _next_number(conn, "inward")

        cursor = conn.execute(
            """
            INSERT INTO inward_receipts
                (receipt_no, receipt_date, vendor_id, item_name, quantity, rate, total)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                receipt_no,
                receipt_date.isoformat(),
                vendor_id,
                item_name.strip(),
                quantity,
                rate,
                total,
            ),
        )
        conn.commit()

        return get_inward_receipt(int(cursor.lastrowid))
    finally:
        conn.close()


def get_inward_receipt(receipt_id: int) -> dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT ir.*, v.name AS vendor_name
            FROM inward_receipts ir
            JOIN vendors v ON v.id = ir.vendor_id
            WHERE ir.id = ?
            """,
            (receipt_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Inward receipt not found.")
        return dict(row)
    finally:
        conn.close()


def list_inward_receipts(
    vendor_id: int | None = None,
    status: str | None = None,
) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        query = """
            SELECT ir.*, v.name AS vendor_name
            FROM inward_receipts ir
            JOIN vendors v ON v.id = ir.vendor_id
            WHERE 1=1
        """
        params: list[Any] = []

        if vendor_id is not None:
            query += " AND ir.vendor_id = ?"
            params.append(vendor_id)
        if status is not None:
            query += " AND ir.status = ?"
            params.append(status)

        query += " ORDER BY ir.receipt_date DESC, ir.id DESC"
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def get_pending_inwards_for_vendor(vendor_id: int) -> list[sqlite3.Row]:
    return list_inward_receipts(vendor_id=vendor_id, status="pending")


def create_bill(vendor_id: int, inward_ids: list[int], bill_date: date) -> dict[str, Any]:
    if not inward_ids:
        raise ValueError("Select at least one inward receipt.")

    conn = get_connection()
    try:
        placeholders = ",".join("?" * len(inward_ids))
        rows = conn.execute(
            f"""
            SELECT id, vendor_id, total, status
            FROM inward_receipts
            WHERE id IN ({placeholders})
            """,
            inward_ids,
        ).fetchall()

        if len(rows) != len(inward_ids):
            raise ValueError("One or more inward receipts were not found.")

        for row in rows:
            if int(row["vendor_id"]) != vendor_id:
                raise ValueError("All inward receipts must belong to the selected vendor.")
            if row["status"] != "pending":
                raise ValueError("Only pending inward receipts can be billed.")

        total_amount = round(sum(float(row["total"]) for row in rows), 2)
        bill_no = _next_number(conn, "bill")

        bill_cursor = conn.execute(
            """
            INSERT INTO bills (bill_no, bill_date, vendor_id, total_amount)
            VALUES (?, ?, ?, ?)
            """,
            (bill_no, bill_date.isoformat(), vendor_id, total_amount),
        )
        bill_id = int(bill_cursor.lastrowid)

        for inward_id in inward_ids:
            conn.execute(
                "INSERT INTO bill_items (bill_id, inward_id) VALUES (?, ?)",
                (bill_id, inward_id),
            )
            conn.execute(
                """
                UPDATE inward_receipts
                SET status = 'billed', bill_id = ?
                WHERE id = ?
                """,
                (bill_id, inward_id),
            )

        vendor_name = conn.execute(
            "SELECT name FROM vendors WHERE id = ?",
            (vendor_id,),
        ).fetchone()["name"]

        conn.execute(
            """
            INSERT INTO ledger_entries
                (vendor_id, entry_date, entry_type, reference_type, reference_id, amount, description)
            VALUES (?, ?, 'debit', 'bill', ?, ?, ?)
            """,
            (
                vendor_id,
                bill_date.isoformat(),
                bill_id,
                total_amount,
                f"Bill {bill_no} raised against vendor {vendor_name}",
            ),
        )

        conn.commit()
        return get_bill(bill_id)
    finally:
        conn.close()


def get_bill(bill_id: int) -> dict[str, Any]:
    conn = get_connection()
    try:
        bill = conn.execute(
            """
            SELECT b.*, v.name AS vendor_name
            FROM bills b
            JOIN vendors v ON v.id = b.vendor_id
            WHERE b.id = ?
            """,
            (bill_id,),
        ).fetchone()
        if bill is None:
            raise ValueError("Bill not found.")

        items = conn.execute(
            """
            SELECT ir.*
            FROM bill_items bi
            JOIN inward_receipts ir ON ir.id = bi.inward_id
            WHERE bi.bill_id = ?
            ORDER BY ir.receipt_no
            """,
            (bill_id,),
        ).fetchall()

        result = dict(bill)
        result["items"] = [dict(item) for item in items]
        return result
    finally:
        conn.close()


def list_bills(vendor_id: int | None = None) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        query = """
            SELECT b.*, v.name AS vendor_name
            FROM bills b
            JOIN vendors v ON v.id = b.vendor_id
            WHERE 1=1
        """
        params: list[Any] = []
        if vendor_id is not None:
            query += " AND b.vendor_id = ?"
            params.append(vendor_id)
        query += " ORDER BY b.bill_date DESC, b.id DESC"
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def create_payment(
    payment_date: date,
    vendor_id: int,
    amount: float,
    mode: str,
    remarks: str = "",
) -> dict[str, Any]:
    if amount <= 0:
        raise ValueError("Payment amount must be greater than zero.")

    conn = get_connection()
    try:
        vendor = conn.execute(
            "SELECT name FROM vendors WHERE id = ?",
            (vendor_id,),
        ).fetchone()
        if vendor is None:
            raise ValueError("Vendor not found.")

        payment_no = _next_number(conn, "payment")
        cursor = conn.execute(
            """
            INSERT INTO payments
                (payment_no, payment_date, vendor_id, amount, mode, remarks)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                payment_no,
                payment_date.isoformat(),
                vendor_id,
                round(amount, 2),
                mode,
                remarks.strip(),
            ),
        )
        payment_id = int(cursor.lastrowid)

        conn.execute(
            """
            INSERT INTO ledger_entries
                (vendor_id, entry_date, entry_type, reference_type, reference_id, amount, description)
            VALUES (?, ?, 'credit', 'payment', ?, ?, ?)
            """,
            (
                vendor_id,
                payment_date.isoformat(),
                payment_id,
                round(amount, 2),
                f"Payment {payment_no} to {vendor['name']} via {mode}",
            ),
        )

        conn.commit()
        return get_payment(payment_id)
    finally:
        conn.close()


def get_payment(payment_id: int) -> dict[str, Any]:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT p.*, v.name AS vendor_name
            FROM payments p
            JOIN vendors v ON v.id = p.vendor_id
            WHERE p.id = ?
            """,
            (payment_id,),
        ).fetchone()
        if row is None:
            raise ValueError("Payment not found.")
        return dict(row)
    finally:
        conn.close()


def list_payments(vendor_id: int | None = None) -> list[sqlite3.Row]:
    conn = get_connection()
    try:
        query = """
            SELECT p.*, v.name AS vendor_name
            FROM payments p
            JOIN vendors v ON v.id = p.vendor_id
            WHERE 1=1
        """
        params: list[Any] = []
        if vendor_id is not None:
            query += " AND p.vendor_id = ?"
            params.append(vendor_id)
        query += " ORDER BY p.payment_date DESC, p.id DESC"
        return conn.execute(query, params).fetchall()
    finally:
        conn.close()


def get_vendor_ledger(vendor_id: int) -> dict[str, Any]:
    conn = get_connection()
    try:
        vendor = conn.execute(
            "SELECT id, name FROM vendors WHERE id = ?",
            (vendor_id,),
        ).fetchone()
        if vendor is None:
            raise ValueError("Vendor not found.")

        entries = conn.execute(
            """
            SELECT entry_date, entry_type, reference_type, reference_id, amount, description
            FROM ledger_entries
            WHERE vendor_id = ?
            ORDER BY entry_date ASC, id ASC
            """,
            (vendor_id,),
        ).fetchall()

        running_balance = 0.0
        ledger_rows: list[dict[str, Any]] = []

        for entry in entries:
            debit = float(entry["amount"]) if entry["entry_type"] == "debit" else 0.0
            credit = float(entry["amount"]) if entry["entry_type"] == "credit" else 0.0
            running_balance = round(running_balance + debit - credit, 2)

            ledger_rows.append(
                {
                    "date": entry["entry_date"],
                    "description": entry["description"] or entry["reference_type"],
                    "reference_type": entry["reference_type"],
                    "reference_id": entry["reference_id"],
                    "debit": debit,
                    "credit": credit,
                    "balance": running_balance,
                }
            )

        return {
            "vendor_id": vendor["id"],
            "vendor_name": vendor["name"],
            "entries": ledger_rows,
            "closing_balance": running_balance,
        }
    finally:
        conn.close()


def get_all_vendor_balances() -> list[dict[str, Any]]:
    conn = get_connection()
    try:
        vendors = conn.execute("SELECT id, name FROM vendors ORDER BY name").fetchall()
        balances: list[dict[str, Any]] = []

        for vendor in vendors:
            summary = get_vendor_ledger(int(vendor["id"]))
            balances.append(
                {
                    "vendor_id": vendor["id"],
                    "vendor_name": vendor["name"],
                    "closing_balance": summary["closing_balance"],
                }
            )
        return balances
    finally:
        conn.close()
