import base64
import io
import os
import sqlite3
import uuid
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont
import streamlit as st
import streamlit.components.v1 as components

DB_PATH = "slip_records.db"
SLIP_DIR = "slips"

if not os.path.exists(SLIP_DIR):
    os.makedirs(SLIP_DIR, exist_ok=True)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS slips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slip_code TEXT UNIQUE,
            vendor TEXT,
            item TEXT,
            quantity INTEGER,
            created_at TEXT,
            filename TEXT
        )
        """
    )
    conn.commit()
    conn.close()


CODE128_PATTERNS = [
    tuple(int(d) for d in pattern)
    for pattern in [
        "212222","222122","222221","121223","121322","131222","122213","122312","132212","221213",
        "221312","231212","112232","122132","122231","113222","123122","123221","223211","221132",
        "221231","213212","223112","312131","311222","321122","321221","312212","322112","322211",
        "212123","212321","232121","111323","131123","131321","112313","132113","132311","211313",
        "231113","231311","112133","112331","132131","113123","113321","133121","313121","211331",
        "231131","213113","213311","213131","311123","311321","331121","312113","312311","332111",
        "314111","221411","431111","111224","111422","121124","121421","141122","141221","112214",
        "112412","122114","122411","142112","142211","241211","221114","413111","241112","134111",
        "111242","121142","121241","114212","124112","124211","411212","421112","421211","212141","214121",
        "412121","111143","111341","131141","114113","114311","411113","411311","113141","114131",
        "311141","411131","211412","211214","211232","2331112",
    ]
]


def get_font(size=24):
    # Prefer Segoe UI, fall back to Arial then PIL default
    try:
        return ImageFont.truetype("Segoe UI.ttf", size)
    except Exception:
        try:
            return ImageFont.truetype("Arial.ttf", size)
        except Exception:
            return ImageFont.load_default()


def build_barcode_image(code: str, width: int = 680, height: int = 160) -> Image.Image:
    def encode_code128(value: str) -> list[int]:
        values = [104]
        for ch in value:
            code_point = ord(ch)
            if 32 <= code_point <= 126:
                values.append(code_point - 32)
            elif code_point == 127:
                values.append(95)
            else:
                raise ValueError(f"Unsupported Code 128 character: {ch}")
        checksum = values[0]
        for idx, val in enumerate(values[1:], start=1):
            checksum += val * idx
        values.append(checksum % 103)
        values.append(106)
        return values

    values = encode_code128(code)
    patterns = [CODE128_PATTERNS[value] for value in values]
    total_modules = sum(sum(pattern) for pattern in patterns)
    quiet_margin = 20
    module_width = max(1, (width - 2 * quiet_margin) // total_modules)
    barcode_width = total_modules * module_width
    barcode_height = height - 32
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    x = (width - barcode_width) // 2
    bar_top = 8
    bar_bottom = bar_top + barcode_height - 24
    for pattern in patterns:
        for idx, module in enumerate(pattern):
            span = module * module_width
            if idx % 2 == 0:
                draw.rectangle([x, bar_top, x + span - 1, bar_bottom], fill="black")
            x += span

    text_font = get_font(24)
    text_bbox = draw.textbbox((0, 0), code, font=text_font)
    text_width = text_bbox[2] - text_bbox[0]
    text_x = (width - text_width) / 2
    text_y = bar_bottom + 8
    draw.text((text_x, text_y), code, fill="black", font=text_font)
    return img


def build_slip_image(vendor: str, item: str, quantity: int, slip_code: str, created_at: str) -> Image.Image:
    width, height = 1200, 700
    img = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(img)

    company_font = get_font(40)
    title_font = get_font(28)
    label_font = get_font(32)
    value_font = get_font(36)
    small_font = get_font(24)

    draw.rectangle([20, 20, width - 20, height - 20], outline="black", width=4)
    draw.text((40, 36), "PREXA INDUSTRIES", fill="black", font=company_font)
    draw.text((40, 88), "Factory Store Slip", fill="black", font=title_font)

    draw.text((40, 160), "Vendor:", fill="black", font=label_font)
    draw.text((260, 160), vendor, fill="black", font=value_font)

    draw.text((40, 230), "Item:", fill="black", font=label_font)
    draw.text((260, 230), item, fill="black", font=value_font)

    draw.text((40, 300), "Quantity:", fill="black", font=label_font)
    draw.text((260, 300), str(quantity), fill="black", font=value_font)

    draw.text((40, 370), "Slip Code:", fill="black", font=label_font)
    draw.text((260, 370), slip_code, fill="black", font=value_font)

    draw.text((40, 440), "Created:", fill="black", font=label_font)
    draw.text((260, 440), created_at, fill="black", font=small_font)

    barcode = build_barcode_image(slip_code, width=620, height=100)
    barcode_x = (width - 620) // 2
    barcode_y = 500
    img.paste(barcode, (barcode_x, barcode_y))

    # Move signatures up so they sit comfortably above the bottom border
    signature_y = height - 80
    left_line_x = 120
    right_line_x = 760
    line_width = 260

    draw.line((left_line_x, signature_y, left_line_x + line_width, signature_y), fill="black", width=3)
    draw.line((right_line_x, signature_y, right_line_x + line_width, signature_y), fill="black", width=3)

    label_y = signature_y + 16
    draw.text((left_line_x, label_y), "Store Manager", fill="black", font=small_font)
    draw.text((right_line_x, label_y), "Director", fill="black", font=small_font)

    return img


def to_data_uri(img: Image.Image) -> str:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    data = base64.b64encode(buffer.getvalue()).decode()
    return f"data:image/png;base64,{data}"


def save_slip_record(vendor: str, item: str, quantity: int, slip_code: str, filename: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR IGNORE INTO slips (slip_code, vendor, item, quantity, created_at, filename) VALUES (?, ?, ?, ?, ?, ?)",
        (slip_code, vendor, item, quantity, datetime.now().isoformat(), filename),
    )
    conn.commit()
    conn.close()


def get_recent_slips(limit: int = 10):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT slip_code, vendor, item, quantity, created_at, filename FROM slips ORDER BY id DESC LIMIT ?", (limit,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def build_print_html(vendor: str, item: str, quantity: int, slip_code: str, created_at: str, barcode_uri: str) -> str:
    html = f"""
    <html>
      <head>
        <meta charset='utf-8'>
        <style>
          @page {{ size: A4 portrait; margin: 10mm; }}
          body {{ margin: 0; padding: 0; font-family: Arial, sans-serif; background: #f8f8f8; }}
          .page {{ width: 210mm; min-height: 297mm; padding: 12mm 10mm; box-sizing: border-box; background: white; }}
          .slip {{ width: 100%; height: calc(50vh - 24px); box-sizing: border-box; padding: 14mm; border: 2px solid #111; margin-bottom: 14mm; position: relative; }}
          .slip:last-child {{ margin-bottom: 0; }}
          .header {{ font-size: 24pt; font-weight: 700; margin-bottom: 10px; letter-spacing: 0.5px; }}
          .line {{ display: flex; justify-content: space-between; margin-bottom: 8px; }}
          .label {{ font-size: 14pt; color: #444; width: 24%; }}
          .value {{ font-size: 18pt; font-weight: 700; color: #111; width: 72%; }}
          .barcode {{ margin-top: 16px; text-align: center; }}
          .barcode img {{ max-width: 100%; height: auto; }}
          .cutline {{ text-align: center; margin: 0; color: #666; font-size: 11pt; }}
          .cutline:before {{ content: '---- CUT HERE ----'; }}
          @media print {{ body {{ background: #fff; }} .page {{ box-shadow: none; margin: 0; }} .no-print {{ display: none; }} }}
        </style>
      </head>
      <body>
        <div class='page'>
          {build_single_slip_html(vendor, item, quantity, slip_code, created_at, barcode_uri)}
          <p class='cutline'></p>
          {build_single_slip_html(vendor, item, quantity, slip_code, created_at, barcode_uri)}
        </div>
      </body>
    </html>
    """
    return html


def build_single_slip_html(vendor: str, item: str, quantity: int, slip_code: str, created_at: str, barcode_uri: str) -> str:
    return f"""
    <div class='slip'>
      <div class='header'>Factory Store Slip</div>
      <div class='line'><span class='label'>Vendor</span><span class='value'>{vendor}</span></div>
      <div class='line'><span class='label'>Item</span><span class='value'>{item}</span></div>
      <div class='line'><span class='label'>Quantity</span><span class='value'>{quantity}</span></div>
      <div class='line'><span class='label'>Slip Code</span><span class='value'>{slip_code}</span></div>
      <div class='line'><span class='label'>Created</span><span class='value'>{created_at}</span></div>
      <div class='barcode'><img src='{barcode_uri}' alt='Barcode'></div>
    </div>
    """


def main():
    st.set_page_config(page_title="Factory Slip Generator", layout="centered")
    st.markdown("<style>body { background: #f3f4f6; } .big-input input { height: 54px; font-size: 20px; padding: 12px; } .big-button button { width: 100%; height: 64px; font-size: 20px; }</style>", unsafe_allow_html=True)
    st.markdown("# Factory Store Slip Generator")
    st.markdown("Minimal interface for store staff. One slip fills half a page so the printed sheet can be cut in two.")

    with st.form(key="slip_form"):
        vendor = st.text_input("Vendor Name", value="", placeholder="Enter vendor name", key="vendor_input").strip().title()
        item = st.text_input("Item Name", value="", placeholder="Enter item or part name", key="item_input").strip().title()
        quantity = st.number_input("Quantity", min_value=1, value=1, step=1, key="quantity_input")
        generate = st.form_submit_button("Generate Slip")

    if generate:

        if not vendor or not item:
            st.error("Vendor and Item fields are required.")
        else:
            slip_code = uuid.uuid4().hex[:12].upper()
            created_at = datetime.now().strftime("%Y-%m-%d %H:%M")
            slip_image = build_slip_image(vendor, item, quantity, slip_code, created_at)
            filename = os.path.join(SLIP_DIR, f"slip_{slip_code}.png")
            slip_image.save(filename)
            save_slip_record(vendor, item, quantity, slip_code, filename)

            st.success("Slip generated successfully.")
            st.image(slip_image, caption="Slip Preview", use_container_width=True)

            buffer = io.BytesIO()
            slip_image.save(buffer, format="PNG")
            buffer.seek(0)
            st.download_button("Download Slip PNG", data=buffer, file_name=f"slip_{slip_code}.png", mime="image/png")

            barcode_uri = to_data_uri(build_barcode_image(slip_code, width=620, height=100))
            html = build_print_html(vendor, item, quantity, slip_code, created_at, barcode_uri)
            st.markdown("### Print Layout")
            components.html(html, height=950)

    st.markdown("---")
    st.subheader("Recent Slips")
    rows = get_recent_slips(8)
    if rows:
        st.table(
            [
                {
                    "Slip Code": row[0],
                    "Vendor": row[1],
                    "Item": row[2],
                    "Qty": row[3],
                    "Created": row[4],
                }
                for row in rows
            ]
        )
    else:
        st.info("No slips generated yet.")


if __name__ == "__main__":
    init_db()
    main()
