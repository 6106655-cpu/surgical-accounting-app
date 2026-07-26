"""Payment recording and voucher generation."""

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from db.repository import create_payment, list_payments, list_vendors
from reports.generators import generate_payment_voucher_pdf

PAYMENT_MODES = ["Cash", "Cheque", "Bank Transfer", "UPI", "NEFT/RTGS"]


def render_payment_module() -> None:
    st.subheader("Payment Module")
    st.caption("Record vendor payments and generate printable payment vouchers.")

    vendors = list_vendors()
    if not vendors:
        st.warning("No vendors found. Add inward receipts or vendors first.")
        return

    vendor_options = {row["name"]: row["id"] for row in vendors}

    col1, col2 = st.columns(2)
    with col1:
        payment_date = st.date_input("Payment Date", value=date.today(), key="payment_date")
        selected_vendor = st.selectbox("Vendor", options=list(vendor_options.keys()))
        vendor_id = vendor_options[selected_vendor]

    with col2:
        amount = st.number_input(
            "Amount (Rs.)",
            min_value=0.0,
            value=0.0,
            step=0.01,
            format="%.2f",
        )
        mode = st.selectbox("Payment Mode", options=PAYMENT_MODES)
        remarks = st.text_area("Remarks", placeholder="Optional payment notes")

    if st.button("Save Payment & Generate Voucher", type="primary", use_container_width=True):
        if amount <= 0:
            st.error("Enter a valid payment amount.")
        else:
            try:
                payment = create_payment(
                    payment_date=payment_date,
                    vendor_id=vendor_id,
                    amount=amount,
                    mode=mode,
                    remarks=remarks,
                )
                pdf_bytes = generate_payment_voucher_pdf(payment)
                st.session_state["last_payment_pdf"] = pdf_bytes
                st.session_state["last_payment_no"] = payment["payment_no"]
                st.success(f"Payment {payment['payment_no']} recorded successfully.")
            except Exception as exc:
                st.error(str(exc))

    if st.session_state.get("last_payment_pdf"):
        st.download_button(
            label=f"Download Payment Voucher ({st.session_state.get('last_payment_no', '')})",
            data=st.session_state["last_payment_pdf"],
            file_name=f"{st.session_state.get('last_payment_no', 'payment')}.pdf",
            mime="application/pdf",
            use_container_width=True,
        )

    st.divider()
    st.markdown("### Payment History")

    payments = list_payments()
    if payments:
        payment_df = pd.DataFrame([dict(row) for row in payments])
        st.dataframe(
            payment_df[
                [
                    "payment_no",
                    "payment_date",
                    "vendor_name",
                    "amount",
                    "mode",
                    "remarks",
                    "created_at",
                ]
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No payments recorded yet.")
