"""Surgical Manufacturing Accounting - Streamlit Desktop App."""

from __future__ import annotations

import streamlit as st

from db.database import init_database
from ui.billing import render_billing_module
from ui.inward import render_inward_module
from ui.ledger import render_ledger_module
from ui.payment import render_payment_module

st.set_page_config(
    page_title="Surgical Manufacturing Accounting",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

init_database()

st.title("Surgical Manufacturing Accounting")
st.caption("Inward · Billing · Payments · Vendor Ledger")

with st.sidebar:
    st.header("Navigation")
    module = st.radio(
        "Select Module",
        options=[
            "Inward",
            "Billing",
            "Payment",
            "Vendor Ledger",
        ],
        label_visibility="collapsed",
    )
    st.divider()
    st.markdown(
        """
        **Workflow**
        1. Record inward receipts
        2. Merge pending inwards into bills
        3. Record vendor payments
        4. Review vendor ledger balances
        """
    )

if module == "Inward":
    render_inward_module()
elif module == "Billing":
    render_billing_module()
elif module == "Payment":
    render_payment_module()
else:
    render_ledger_module()
