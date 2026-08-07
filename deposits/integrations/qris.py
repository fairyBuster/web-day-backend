"""
QRIS (Quick Response Code Indonesian Standard) integration utilities.

Static QRIS -> Dynamic QRIS conversion:
- Parse QRIS tag-length-value (TLV) structure
- Inject tag 54 (transaction amount) and tag 62 (merchant tx ID)
- Recalculate CRC16 (tag 63)
- Generate QR image from final string
"""

import re
import base64
import io
import logging
from decimal import Decimal
from typing import Optional

logger = logging.getLogger(__name__)

# QRIS Tag IDs
TAG_PAYLOAD_FORMAT = "00"
# Merchant Account Info tag range: 02-51 (varies per acquirer)
TAG_MERCHANT_CATEGORY_CODE = "52"
TAG_TRANSACTION_CURRENCY = "53"
TAG_TRANSACTION_AMOUNT = "54"
TAG_COUNTRY_CODE = "58"
TAG_MERCHANT_NAME = "59"
TAG_MERCHANT_CITY = "60"
TAG_POSTAL_CODE = "61"
TAG_ADDITIONAL_DATA = "62"
TAG_CRC = "63"
TAG_TERMINAL_LABEL = "07"
TAG_MERCHANT_PAN = "26"  # sub-tag


def _crc16_ccitt(data: bytes) -> int:
    """CRC16-CCITT (0x1021) as used in QRIS."""
    crc = 0xFFFF
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def calculate_qris_crc(qris_string: str) -> str:
    """Calculate CRC16 for a QRIS string (without tag 63)."""
    crc = _crc16_ccitt(qris_string.encode("ascii"))
    return f"{crc:04X}"


def parse_qris_tags(qris_string: str) -> dict:
    """
    Parse QRIS TLV string into {tag: value} dict.
    Tag is 2 digits, length is 2 digits, value is `length` chars.
    Supports nested Merchant Account Information (tag 26 with sub-tags).
    """
    tags = {}
    i = 0
    while i < len(qris_string):
        if i + 4 > len(qris_string):
            break
        tag = qris_string[i:i+2]
        length_str = qris_string[i+2:i+4]
        try:
            length = int(length_str)
        except ValueError:
            break
        i += 4
        if i + length > len(qris_string):
            break
        value = qris_string[i:i+length]
        tags[tag] = value
        i += length
    return tags


def build_qris_string(tags: dict) -> str:
    """
    Build QRIS TLV string from {tag: value} dict.
    CRC (tag 63) is excluded and recalculated.
    """
    sorted_tags = sorted(
        [(t, v) for t, v in tags.items() if t != TAG_CRC],
        key=lambda x: x[0]
    )
    payload = ""
    for tag, value in sorted_tags:
        length = len(value)
        payload += f"{tag}{length:02d}{value}"
    # Append CRC
    crc = calculate_qris_crc(payload + TAG_CRC + "04")
    payload += f"{TAG_CRC}04{crc}"
    return payload


def convert_static_to_dynamic(
    qris_string: str,
    amount: Decimal,
    order_num: str,
) -> str:
    """
    Convert a static QRIS string to dynamic:
    - Add/modify tag 54 (transaction amount - the actual amount user must pay)
    - Add/modify tag 62 (additional data with unique tx reference ID)
    - Recalculate tag 63 (CRC)
    
    Returns the modified QRIS string.
    """
    tags = parse_qris_tags(qris_string)

    # Remove CRC so we can rebuild
    tags.pop(TAG_CRC, None)

    # Inject transaction amount (tag 54) - the actual amount to pay
    # Amount must be integer for QRIS
    amount_str = f"{int(amount)}"
    tags[TAG_TRANSACTION_AMOUNT] = amount_str

    # Inject additional data (tag 62) with unique reference ID sub-tag 01
    ref_id = f"01{len(order_num):02d}{order_num}"
    tags[TAG_ADDITIONAL_DATA] = ref_id

    return build_qris_string(tags)


def generate_qr_image(qris_string: str, box_size: int = 10, border: int = 4) -> Optional[str]:
    """
    Generate a QR code image from a QRIS string.
    Returns base64-encoded PNG data URL string.
    """
    import io
    try:
        import qrcode
    except ImportError:
        logger.warning("qrcode library not installed, falling back to google charts")
        return _generate_qr_fallback(qris_string)

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(qris_string)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


def generate_qr_image_file(qris_string: str, save_dir: str, filename: str, label: str = "") -> str:
    """
    Generate QR image and save to disk. Returns relative URL path.
    If label is provided, overlays text at the bottom of the QR image.
    """
    import os, io
    from django.conf import settings

    try:
        import qrcode
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("qrcode not installed, generating via fallback URL")
        return _generate_qr_fallback(qris_string)

    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(qris_string)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")

    # Overlay label text at bottom if provided
    if label:
        try:
            draw = ImageDraw.Draw(img)
            # Add white padding bar at bottom for text
            new_h = img.height + 50
            new_img = Image.new("RGB", (img.width, new_h), "white")
            new_img.paste(img, (0, 0))
            draw = ImageDraw.Draw(new_img)

            # Try to use a reasonable font, fallback to default
            try:
                font = ImageFont.truetype("arial.ttf", 28)
            except Exception:
                try:
                    font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 28)
                except Exception:
                    font = ImageFont.load_default()

            text = f"Kode: {label}"
            bbox = draw.textbbox((0, 0), text, font=font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            x = (new_img.width - tw) // 2
            y = img.height + (50 - th) // 2
            draw.text((x, y), text, fill="black", font=font)
            img = new_img
        except Exception as e:
            logger.warning("Failed to overlay label on QR: %s", e)

    # Ensure directory exists
    full_dir = os.path.join(settings.MEDIA_ROOT, save_dir)
    os.makedirs(full_dir, exist_ok=True)

    filepath = os.path.join(full_dir, filename)
    img.save(filepath, format="PNG")

    return f"{settings.MEDIA_URL}{save_dir}/{filename}"


def generate_unique_code(length: int = 6) -> str:
    """Generate short unique alphanumeric code for deposit matching."""
    import secrets
    import string
    chars = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


def generate_unique_amount_code() -> int:
    """Generate 3-digit unique code (100-399) to add to deposit amount."""
    import secrets
    return secrets.randbelow(300) + 100  # 100-399, maksimal 400


def overlay_text_on_image(source_path: str, text: str, save_dir: str, filename: str) -> str:
    """
    Overlay text di bagian bawah gambar QR asli.
    Tidak memodifikasi QR code, hanya tambah padding + text.
    Returns relative URL path.
    """
    import os
    from django.conf import settings

    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("Pillow not installed for overlay")
        return ""

    try:
        img = Image.open(source_path).convert("RGB")
    except Exception as e:
        logger.warning("Cannot open image for overlay: %s", e)
        return ""

    # Full directory
    full_dir = os.path.join(settings.MEDIA_ROOT, save_dir)
    os.makedirs(full_dir, exist_ok=True)
    filepath = os.path.join(full_dir, filename)

    # If no text, just copy the image
    if not text:
        img.save(filepath, format="PNG")
        return f"{settings.MEDIA_URL}{save_dir}/{filename}"

    # Font
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 32)
    except Exception:
        try:
            font = ImageFont.truetype("arial.ttf", 32)
        except Exception:
            font = ImageFont.load_default()

    # Hitung padding bawah untuk text
    draw_tmp = ImageDraw.Draw(img)
    bbox = draw_tmp.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    padding = th + 30

    # Buat canvas baru dengan padding bawah
    new_img = Image.new("RGB", (img.width, img.height + padding), "white")
    new_img.paste(img, (0, 0))

    draw = ImageDraw.Draw(new_img)
    x = (new_img.width - tw) // 2
    y = img.height + (padding - th) // 2
    draw.text((x, y), text, fill="black", font=font)

    # Save
    new_img.save(filepath, format="PNG")

    return f"{settings.MEDIA_URL}{save_dir}/{filename}"


def _generate_qr_fallback(data: str) -> str:
    """Fallback: Google Charts API QR image (may be deprecated)."""
    import urllib.parse
    encoded = urllib.parse.quote(data, safe="")
    return f"https://chart.googleapis.com/chart?chs=300x300&cht=qr&chl={encoded}&choe=UTF-8"


def sanitize_qris_string(raw: str) -> str:
    """Clean up a QRIS string from whitespace/newlines."""
    return re.sub(r'\s+', '', raw).strip()
