"""Vendor ledger with running debit/credit balance."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from db.repository import get_all_vendor_balances, get_vendor_ledger, list_vendors


def render_ledger_module() -> None:
    st.subheader("Vendor Ledger")
    st.caption("Automatic debit (bills) and credit (payments) with running balance.")

    vendors = list_vendors()
    if not vendors:
        st.warning("No vendors found.")
        return

    st.markdown("### Vendor Balances")
    balances = get_all_vendor_balances()
    balance_df = pd.DataFrame(balances)
    balance_df = balance_df.rename(
        columns={
            "vendor_name": "Vendor",
            "closing_balance": "Outstanding Balance (Rs.)",
        }
    )
    st.dataframe(
        balance_df[["Vendor", "Outstanding Balance (Rs.)"]],
        use_container_width=True,
        hide_index=True,
    )

    st.divider()

    vendor_options = {row["name"]: row["id"] for row in vendors}
    selected_vendor = st.selectbox(
        "View Ledger For",
        options=list(vendor_options.keys()),
        key="ledger_vendor_select",
    )
    vendor_id = vendor_options[selected_vendor]

    ledger = get_vendor_ledger(vendor_id)
    st.metric(
        "Closing Balance",
        f"Rs. {ledger['closing_balance']:,.2f}",
        help="Positive balance means amount payable to vendor.",
    )

    if ledger["entries"]:
        ledger_df = pd.DataFrame(ledger["entries"])
        ledger_df = ledger_df.rename(
            columns={
                "date": "Date",
                "description": "Description",
                "debit": "Debit (Rs.)",
                "credit": "Credit (Rs.)",
                "balance": "Balance (Rs.)",
            }
        )
        st.dataframe(
            ledger_df[["Date", "Description", "Debit (Rs.)", "Credit (Rs.)", "Balance (Rs.)"]],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No ledger entries for this vendor yet.")
