"""Inward receipt entry and listing."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from db.repository import create_inward_receipt, list_inward_receipts
from reports.generators import generate_inward_receipt_pdf


def render_inward_module() -> None:
    st.subheader("Inward Module")
    st.caption("Record material receipts from vendors and generate printable inward receipts.")

    col1, col2 = st.columns(2)

    with col1:
        receipt_date = st.date_input("Date", value=date.today(), key="inward_date")
        vendor_name = st.text_input("Vendor Name", placeholder="Enter vendor name")
        item_name = st.text_input("Item Name", placeholder="Surgical item / raw material")

    with col2:
        quantity = st.number_input("Quantity", min_value=0.0, value=1.0, step=1.0)
        rate = st.number_input("Rate (Rs.)", min_value=0.0, value=0.0, step=0.01, format="%.2f")
        total = round(quantity * rate, 2)
        st.metric("Total (Auto Calculated)", f"Rs. {total:,.2f}")

    if st.button("Save Inward Receipt", type="primary", use_container_width=True):
        if not vendor_name or not item_name:
            st.error("Vendor Name and Item Name are required.")
        elif quantity <= 0:
            st.error("Quantity must be greater than zero.")
        else:
            try:
                receipt = create_inward_receipt(
                    receipt_date=receipt_date,
                    vendor_name=vendor_name,
                    item_name=item_name,
                    quantity=quantity,
                    rate=rate,
                )
                pdf_bytes = generate_inward_receipt_pdf(receipt)
                st.session_state["last_inward_pdf"] = pdf_bytes
                st.session_state["last_inward_no"] = receipt["receipt_no"]
                st.success(f"Inward receipt {receipt['receipt_no']} saved successfully.")
            except Exception as exc:
                st.error(str(exc))

    if st.session_state.get("last_inward_pdf"):
        st.download_button(
            label=f"Download Receipt PDF ({st.session_state.get('last_inward_no', '')})",
            data=st.session_state["last_inward_pdf"],
            file_name=f"{st.session_state.get('last_inward_no', 'inward')}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

    st.divider()
    st.markdown("### Recent Inward Receipts")

    status_filter = st.selectbox(
        "Filter by Status",
        options=["All", "pending", "billed"],
        index=0,
    )
    status = None if status_filter == "All" else status_filter
    receipts = list_inward_receipts(status=status)

    if receipts:
        df = pd.DataFrame([dict(row) for row in receipts])
        display_cols = [
            "receipt_no",
            "receipt_date",
            "vendor_name",
            "item_name",
            "quantity",
            "rate",
            "total",
            "status",
        ]
        st.dataframe(df[display_cols], use_container_width=True, hide_index=True)
    else:
        st.info("No inward receipts found.")
