"""PDF report generators for receipts, bills, and payment vouchers."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from fpdf import FPDF

COMPANY_NAME = "Surgical Manufacturing Unit"
COMPANY_TAGLINE = "Precision Instruments & Medical Supplies"


class ReportPDF(FPDF):
    def header(self) -> None:
        self.set_font("Helvetica", "B", 14)
        self.cell(0, 8, COMPANY_NAME, ln=True, align="C")
        self.set_font("Helvetica", "", 10)
        self.cell(0, 6, COMPANY_TAGLINE, ln=True, align="C")
        self.ln(4)

    def footer(self) -> None:
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.cell(0, 10, f"Page {self.page_no()}", align="C")


def _money(value: float) -> str:
    return f"{value:,.2f}"


def _pdf_bytes(pdf: FPDF) -> bytes:
    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()


def generate_inward_receipt_pdf(receipt: dict[str, Any]) -> bytes:
    pdf = ReportPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    for copy_label in ("ORIGINAL - FOR VENDOR", "DUPLICATE - FOR OFFICE"):
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "INWARD RECEIPT", ln=True, align="C")
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(180, 0, 0)
        pdf.cell(0, 7, copy_label, ln=True, align="C")
        pdf.set_text_color(0, 0, 0)
        pdf.ln(4)

        pdf.set_font("Helvetica", "", 10)
        pdf.cell(95, 7, f"Receipt No: {receipt['receipt_no']}", border=0)
        pdf.cell(95, 7, f"Date: {receipt['receipt_date']}", ln=True, align="R")
        pdf.cell(0, 7, f"Vendor: {receipt['vendor_name']}", ln=True)
        pdf.ln(4)

        pdf.set_font("Helvetica", "B", 10)
        pdf.cell(70, 8, "Item Name", border=1)
        pdf.cell(30, 8, "Qty", border=1, align="C")
        pdf.cell(40, 8, "Rate", border=1, align="R")
        pdf.cell(50, 8, "Total", border=1, align="R", ln=True)

        pdf.set_font("Helvetica", "", 10)
        pdf.cell(70, 8, receipt["item_name"], border=1)
        pdf.cell(30, 8, str(receipt["quantity"]), border=1, align="C")
        pdf.cell(40, 8, _money(float(receipt["rate"])), border=1, align="R")
        pdf.cell(50, 8, _money(float(receipt["total"])), border=1, align="R", ln=True)

        pdf.ln(6)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 8, f"Grand Total: Rs. {_money(float(receipt['total']))}", ln=True, align="R")
        pdf.ln(20)

        pdf.set_font("Helvetica", "", 10)
        pdf.cell(95, 7, "Received By: ____________________", border=0)
        pdf.cell(95, 7, "Authorized Sign: ____________________", ln=True, align="R")

    return _pdf_bytes(pdf)


def generate_bill_pdf(bill: dict[str, Any]) -> bytes:
    pdf = ReportPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "VENDOR BILL / INVOICE", ln=True, align="C")
    pdf.ln(4)

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(95, 7, f"Bill No: {bill['bill_no']}", border=0)
    pdf.cell(95, 7, f"Date: {bill['bill_date']}", ln=True, align="R")
    pdf.cell(0, 7, f"Vendor: {bill['vendor_name']}", ln=True)
    pdf.ln(4)

    pdf.set_font("Helvetica", "B", 10)
    pdf.cell(35, 8, "Inward No", border=1)
    pdf.cell(25, 8, "Date", border=1)
    pdf.cell(55, 8, "Item", border=1)
    pdf.cell(20, 8, "Qty", border=1, align="C")
    pdf.cell(25, 8, "Rate", border=1, align="R")
    pdf.cell(30, 8, "Total", border=1, align="R", ln=True)

    pdf.set_font("Helvetica", "", 10)
    for item in bill["items"]:
        pdf.cell(35, 8, item["receipt_no"], border=1)
        pdf.cell(25, 8, item["receipt_date"], border=1)
        pdf.cell(55, 8, item["item_name"][:28], border=1)
        pdf.cell(20, 8, str(item["quantity"]), border=1, align="C")
        pdf.cell(25, 8, _money(float(item["rate"])), border=1, align="R")
        pdf.cell(30, 8, _money(float(item["total"])), border=1, align="R", ln=True)

    pdf.ln(6)
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(
        0,
        8,
        f"Bill Total: Rs. {_money(float(bill['total_amount']))}",
        ln=True,
        align="R",
    )

    return _pdf_bytes(pdf)


def generate_payment_voucher_pdf(payment: dict[str, Any]) -> bytes:
    pdf = ReportPDF()
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 8, "PAYMENT VOUCHER", ln=True, align="C")
    pdf.ln(6)

    pdf.set_font("Helvetica", "", 10)
    pdf.cell(95, 8, f"Voucher No: {payment['payment_no']}", border=0)
    pdf.cell(95, 8, f"Date: {payment['payment_date']}", ln=True, align="R")
    pdf.cell(0, 8, f"Paid To: {payment['vendor_name']}", ln=True)
    pdf.cell(0, 8, f"Payment Mode: {payment['mode']}", ln=True)
    pdf.ln(6)

    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 10, f"Amount Paid: Rs. {_money(float(payment['amount']))}", ln=True)

    if payment.get("remarks"):
        pdf.ln(4)
        pdf.set_font("Helvetica", "", 10)
        pdf.multi_cell(0, 7, f"Remarks: {payment['remarks']}")

    pdf.ln(24)
    pdf.cell(95, 8, "Prepared By: ____________________", border=0)
    pdf.cell(95, 8, "Approved By: ____________________", ln=True, align="R")
    pdf.ln(12)
    pdf.cell(0, 8, "Received By / Signature: ________________________________________", ln=True)

    return _pdf_bytes(pdf)


def save_pdf(content: bytes, filename: str, output_dir: Path | None = None) -> Path:
    folder = output_dir or Path(__file__).resolve().parent.parent / "data" / "exports"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / filename
    path.write_bytes(content)
    return path
