"""Billing module - merge pending inward receipts into vendor bills."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from db.repository import create_bill, get_pending_inwards_for_vendor, list_bills, list_vendors
from reports.generators import generate_bill_pdf


def render_billing_module() -> None:
    st.subheader("Billing Module")
    st.caption("Select a vendor and merge pending inward receipts into a single bill.")

    vendors = list_vendors()
    if not vendors:
        st.warning("No vendors found. Create an inward receipt first to add vendors.")
        return

    vendor_options = {row["name"]: row["id"] for row in vendors}
    selected_vendor = st.selectbox("Select Vendor", options=list(vendor_options.keys()))
    vendor_id = vendor_options[selected_vendor]

    pending = get_pending_inwards_for_vendor(vendor_id)
    if not pending:
        st.info("No pending inward receipts for this vendor.")
    else:
        df = pd.DataFrame([dict(row) for row in pending])
        df["select"] = False
        edited = st.data_editor(
            df[
                [
                    "select",
                    "receipt_no",
                    "receipt_date",
                    "item_name",
                    "quantity",
                    "rate",
                    "total",
                ]
            ],
            column_config={
                "select": st.column_config.CheckboxColumn("Select", default=False),
                "receipt_no": "Inward No",
                "receipt_date": "Date",
                "item_name": "Item",
                "quantity": "Qty",
                "rate": "Rate",
                "total": "Total",
            },
            disabled=["receipt_no", "receipt_date", "item_name", "quantity", "rate", "total"],
            hide_index=True,
            use_container_width=True,
            key="pending_inward_editor",
        )

        selected_rows = edited[edited["select"]]
        selected_total = float(selected_rows["total"].sum()) if not selected_rows.empty else 0.0
        st.metric("Selected Bill Total", f"Rs. {selected_total:,.2f}")

        bill_date = st.date_input("Bill Date", value=date.today(), key="bill_date")

        if st.button("Generate Bill / Invoice", type="primary", use_container_width=True):
            if selected_rows.empty:
                st.error("Select at least one pending inward receipt.")
            else:
                receipt_id_map = {row["receipt_no"]: int(row["id"]) for row in pending}
                inward_ids = [
                    receipt_id_map[receipt_no]
                    for receipt_no in selected_rows["receipt_no"].tolist()
                ]
                try:
                    bill = create_bill(vendor_id, inward_ids, bill_date)
                    pdf_bytes = generate_bill_pdf(bill)
                    st.session_state["last_bill_pdf"] = pdf_bytes
                    st.session_state["last_bill_no"] = bill["bill_no"]
                    st.success(f"Bill {bill['bill_no']} created for Rs. {bill['total_amount']:,.2f}")
                    st.rerun()
                except Exception as exc:
                    st.error(str(exc))

    if st.session_state.get("last_bill_pdf"):
        st.download_button(
            label=f"Download Bill PDF ({st.session_state.get('last_bill_no', '')})",
            data=st.session_state["last_bill_pdf"],
            file_name=f"{st.session_state.get('last_bill_no', 'bill')}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

    st.divider()
    st.markdown("### Bill History")

    bills = list_bills()
    if bills:
        bill_df = pd.DataFrame([dict(row) for row in bills])
        st.dataframe(
            bill_df[
                ["bill_no", "bill_date", "vendor_name", "total_amount", "status", "created_at"]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No bills generated yet.")
