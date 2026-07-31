# Surgical Manufacturing Accounting App

Streamlit desktop accounting application for a surgical manufacturing business. Uses SQLite for local storage and generates printable PDF documents for inward receipts, bills, and payment vouchers.

## Features

- **Inward Module** — Auto receipt numbers (`INR-1001`), vendor/item entry, auto total, dual-copy printable receipt PDF
- **Billing Module** — Merge multiple pending inward receipts into one vendor bill/invoice
- **Payment Module** — Record vendor payments with mode and remarks; printable payment voucher
- **Vendor Ledger** — Automatic debit (bills) / credit (payments) with running balance

## Project Structure

```
surgical-accounting-app/
├── app.py                  # Streamlit entry point
├── requirements.txt
├── scripts/
│   └── init_db.py          # Database initialization script
├── db/
│   ├── database.py         # SQLite schema & connection
│   └── repository.py       # Business logic & CRUD
├── ui/
│   ├── inward.py
│   ├── billing.py
│   ├── payment.py
│   └── ledger.py
├── reports/
│   └── generators.py       # PDF receipt/voucher generators
└── data/
    └── accounting.db       # Created on first run (gitignored)
```

## Setup

```bash
cd ~/Projects/surgical-accounting-app
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/init_db.py
streamlit run app.py
```

## Deploy on Streamlit Community Cloud (Free)

### 1. Prepare repository

Make sure these files are committed:

- `app.py` (entry point)
- `requirements.txt` (dependencies)
- all code folders used by the app (`db/`, `reports/`, `ui/`, `scripts/`)

### 2. Push to GitHub

```bash
git add .
git commit -m "Prepare Streamlit Cloud deployment"
git push origin main
```

### 3. Deploy from Streamlit Cloud

1. Open https://share.streamlit.io/
2. Sign in with GitHub
3. Click **New app**
4. Select your repository
5. Set:
    - **Branch**: `main`
    - **Main file path**: `app.py`
6. Click **Deploy**

After deployment, Streamlit gives you a permanent public URL.

### 4. Optional secrets

If you later add API keys/passwords, place them in Streamlit app secrets:

- App settings -> **Secrets**
- Add the TOML values there (do not commit `.streamlit/secrets.toml`)

### Important note about storage

Streamlit Community Cloud uses ephemeral local disk. Files like generated slips and local databases can reset when the app restarts.

For durable production data, move storage to an external database/object storage.

## Accounting Logic

| Event   | Ledger Entry | Effect on Balance      |
|---------|--------------|------------------------|
| Bill    | Debit        | Payable increases      |
| Payment | Credit       | Payable decreases      |

Positive closing balance = amount still payable to the vendor.

## Document Numbering

| Document        | Prefix   | Example   |
|-----------------|----------|-----------|
| Inward Receipt  | INR-     | INR-1001  |
| Bill / Invoice  | BILL-    | BILL-1001 |
| Payment Voucher | PAY-     | PAY-1001  |

Counters start at 1000 and auto-increment on each new document.
