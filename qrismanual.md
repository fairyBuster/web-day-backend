# QRIS Manual — Static to Dynamic Implementation Guide

Implementasi lengkap QRIS Manual: upload QRIS static, konversi otomatis ke dynamic dengan kode unik, manual accept/reject deposit melalui admin panel.

---

## 1. Alur / Flow

```
Admin upload QRIS static (gambar / raw string)
        │
        ▼
User request deposit Rp 10,000 via API
        │
        ▼
Sistem generate kode unik (misal: 112)
Nominal QR = 10,000 + 112 = 10,112
        │
        ▼
QRIS static dikonversi ke dynamic:
  - Tag 01: "11" → "12" (point-of-initiation: static → dynamic)
  - Tag 54 disisipkan = "10112" (amount)
  - Tag 63 (CRC16) di-recalculate
        │
        ▼
Generate QR image (PNG), simpan ke disk
        │
        ▼
Response ke user: QR image URL + kode unik
        │
        ▼
User scan & bayar tepat Rp 10,112
        │
        ▼
Admin verifikasi via panel → klik "Accept" / "Reject"
        │
        ▼
Accept → credit saldo user
Reject → deposit marked FAILED
```

---

## 2. Requirements

### `requirements.txt`

```
qrcode==8.2
opencv-python-headless
Pillow==12.0.0
```

### System dependencies (Docker / Linux)

```
libgl1        # atau libgl1-mesa-glx di Debian <13
libglib2.0-0
```

Dockerfile:

```dockerfile
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
```

---

## 3. QRIS Utilities — `deposits/integrations/qris.py`

Buat file baru `deposits/integrations/qris.py` (atau folder `integrations/` + `__init__.py`).

```python
"""
QRIS (Quick Response Code Indonesian Standard) integration utilities.

Static QRIS -> Dynamic QRIS conversion:
- Parse QRIS tag-length-value (TLV) structure
- Inject tag 54 (transaction amount)
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
TAG_POINT_OF_INITIATION = "01"  # 11=static, 12=dynamic
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
    """Build QRIS TLV string from {tag: value} dict. CRC recalculated."""
    sorted_tags = sorted(
        [(t, v) for t, v in tags.items() if t != TAG_CRC],
        key=lambda x: x[0]
    )
    payload = ""
    for tag, value in sorted_tags:
        length = len(value)
        payload += f"{tag}{length:02d}{value}"
    crc = calculate_qris_crc(payload + TAG_CRC + "04")
    payload += f"{TAG_CRC}04{crc}"
    return payload


def convert_static_to_dynamic(
    qris_string: str,
    amount: Decimal,
    order_num: str = "",
) -> str:
    """
    Convert static QRIS ke dynamic:
    1. Parse TLV preserving original order
    2. Change tag 01: 11 → 12 (static → dynamic)
    3. Insert tag 54 (amount) before tag 58 (country code)
    4. Skip tag 63, recalculate CRC16
    
    Returns the modified QRIS string.
    """
    elements = _parse_tlv_preserve_order(qris_string)

    # Managed tags to skip
    managed_tags = {"54", "55", "56", "57", "63"}

    result = []
    amount_inserted = False

    for tag, value in elements:
        if tag in managed_tags:
            continue
        if tag == "01":
            result.append(("01", "12"))
            continue
        # Insert amount before tag 58 (Country Code)
        if tag == "58" and not amount_inserted:
            amount_str = str(int(amount))
            result.append((TAG_TRANSACTION_AMOUNT, amount_str))
            amount_inserted = True
        result.append((tag, value))

    # Build string without CRC
    payload = ""
    for tag, value in result:
        payload += f"{tag}{len(value):02d}{value}"

    # CRC
    crc = calculate_qris_crc(payload + TAG_CRC + "04")
    return payload + f"{TAG_CRC}04{crc}"


def _parse_tlv_preserve_order(data: str):
    """Parse QRIS TLV, preserve original order. Returns list of (tag, value)."""
    elements = []
    i = 0
    while i + 4 <= len(data):
        tag = data[i:i+2]
        try:
            length = int(data[i+2:i+4])
        except ValueError:
            break
        if i + 4 + length > len(data):
            break
        value = data[i+4:i+4+length]
        elements.append((tag, value))
        i += 4 + length
    return elements


def generate_qr_image(qris_string: str, box_size: int = 10, border: int = 4) -> Optional[str]:
    """Generate a QR code image from a QRIS string. Returns base64 data URL."""
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
            new_h = img.height + 50
            new_img = Image.new("RGB", (img.width, new_h), "white")
            new_img.paste(img, (0, 0))
            draw = ImageDraw.Draw(new_img)

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


def generate_unique_amount_code() -> int:
    """Generate 3-digit unique code (100-300) to add to deposit amount."""
    import secrets
    return secrets.randbelow(201) + 100  # 100-300


def sanitize_qris_string(raw: str) -> str:
    """Clean up a QRIS string — remove newlines only, preserve spaces in values."""
    return re.sub(r'[\r\n]+', '', raw).strip()


def _generate_qr_fallback(data: str) -> str:
    """Fallback: Google Charts API QR image (may be deprecated)."""
    import urllib.parse
    encoded = urllib.parse.quote(data, safe="")
    return f"https://chart.googleapis.com/chart?chs=300x300&cht=qr&chl={encoded}&choe=UTF-8"
```

---

## 4. Models — `deposits/models.py`

### 4.1 GatewaySettings — tambahkan fields

```python
# Di class GatewaySettings, tambahkan:
qris_enabled = models.BooleanField(default=False)
qris_min_deposit_amount = models.DecimalField(
    max_digits=15, decimal_places=2, default=10000,
    help_text='Minimal nominal deposit QRIS'
)
qris_max_deposit_amount = models.DecimalField(
    max_digits=15, decimal_places=2, default=5000000,
    help_text='Maksimal nominal deposit QRIS (0 = tidak dibatasi)'
)
qris_expired_minutes = models.PositiveIntegerField(
    default=30, help_text='QR kadaluarsa setelah berapa menit (0 = tidak kadaluarsa)'
)
```

### 4.2 QRISGateway — model baru

```python
from django.db import models
from .integrations.qris import sanitize_qris_string


class QRISGateway(models.Model):
    """Menyimpan QRIS static yang di-upload manual oleh admin."""

    label = models.CharField(max_length=100, help_text='Label/nama QRIS (contoh: QRIS BCA, ShopeePay)')
    qris_image = models.ImageField(
        upload_to='qris/images/', blank=True, null=True,
        help_text='Upload gambar QRIS static'
    )
    qris_raw_data = models.TextField(
        blank=True, default='',
        help_text='Raw QRIS string hasil scan (0002010102...)'
    )
    is_active = models.BooleanField(default=True, help_text='Aktifkan QR ini untuk digunakan')
    max_use_count = models.PositiveIntegerField(
        default=0, help_text='Maksimal berapa kali QR ini bisa dipakai (0 = unlimited)'
    )
    used_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"QRIS: {self.label} ({'active' if self.is_active else 'inactive'})"

    def clean(self):
        if self.qris_raw_data:
            self.qris_raw_data = sanitize_qris_string(self.qris_raw_data)

    def save(self, *args, **kwargs):
        self.clean()
        # Auto-decode QR from uploaded image if raw_data is empty
        if self.qris_image and not self.qris_raw_data:
            self._decode_qr_from_image()
        # If image file is missing but raw_data exists, clear the broken image reference
        if self.qris_image and self.qris_raw_data:
            import os
            try:
                if not os.path.exists(self.qris_image.path):
                    self.qris_image = None
            except Exception:
                pass
        super().save(*args, **kwargs)

    def _decode_qr_from_image(self):
        """Try to decode QR code from uploaded image using OpenCV."""
        import logging
        logger = logging.getLogger(__name__)
        import os

        try:
            import cv2
            import numpy as np
        except ImportError:
            logger.info("QRISGateway: opencv not installed, skip auto-decode")
            return

        try:
            file_path = self.qris_image.path
            if not os.path.exists(file_path):
                logger.info("QRISGateway: image file not found, skip decode (path=%s)", file_path)
                return

            with open(file_path, 'rb') as f:
                file_bytes = np.frombuffer(f.read(), np.uint8)
            img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
            if img is None:
                logger.warning("QRISGateway: cannot decode image for label=%s", self.label)
                return

            detector = cv2.QRCodeDetector()
            data, bbox, _ = detector.detectAndDecode(img)
            if data:
                self.qris_raw_data = sanitize_qris_string(data)
                logger.info("QRISGateway: auto-decoded QR from image for label=%s", self.label)
            else:
                logger.warning("QRISGateway: no QR found in image for label=%s", self.label)
        except Exception as e:
            logger.warning("QRISGateway: failed to decode QR from image: %s", e)

    @classmethod
    def get_random_active(cls):
        """Ambil satu QRIS aktif secara random."""
        qs = list(cls.objects.filter(is_active=True))
        if not qs:
            return None
        import random
        return random.choice(qs)

    @property
    def is_available(self):
        if not self.is_active:
            return False
        if self.max_use_count > 0 and self.used_count >= self.max_use_count:
            return False
        return True

    class Meta:
        verbose_name = 'QRIS Gateway'
        verbose_name_plural = 'QRIS Gateway'
        ordering = ['-created_at']
        db_table = 'deposits_qris_gateway'
```

### 4.3 Deposit — tambahkan fields & properties

```python
# Di class Deposit, tambahkan:
from django.utils import timezone

GATEWAY_CHOICES = [
    # ... existing choices ...
    ('QRIS', 'QRIS Manual'),
]

expired_at = models.DateTimeField(null=True, blank=True)

@property
def display_amount(self):
    """Tampilkan amount dengan kode unik untuk QRIS."""
    if self.gateway == 'QRIS' and self.request_params:
        qris_amount = self.request_params.get('qris_amount')
        if qris_amount:
            return qris_amount
    return self.amount

@property
def unique_code(self):
    """Kode unik untuk deposit QRIS."""
    if self.gateway == 'QRIS' and self.request_params:
        return self.request_params.get('unique_code')
    return None

@property
def is_expired(self):
    """Cek apakah deposit sudah expired."""
    if self.expired_at and timezone.now() > self.expired_at:
        return True
    return False
```

---

## 5. CSRF Fix — `accounts/auth.py`

DRF `SessionAuthentication.enforce_csrf()` tidak menghormati `@csrf_exempt`. Override diperlukan:

```python
from rest_framework.authentication import SessionAuthentication


class BannedAwareSessionAuthentication(SessionAuthentication):
    def authenticate(self, request):
        result = super().authenticate(request)
        if not result:
            return None
        user, auth = result
        enforce_user_access(user)  # optional, sesuaikan dengan project
        return user, auth

    def enforce_csrf(self, request):
        """
        Skip CSRF enforcement for DRF views marked with csrf_exempt.
        DRF's default enforce_csrf passes callback=None to Django's
        CsrfViewMiddleware.process_view(), which causes getattr(None, 'csrf_exempt', False)
        to always return False -- ignoring the decorator entirely.
        """
        view = getattr(request, 'resolver_match', None)
        if view is not None:
            view_func = getattr(view, 'func', None)
            if view_func is not None and getattr(view_func, 'csrf_exempt', False):
                return
        super().enforce_csrf(request)
```

Pastikan class ini dipakai di `REST_FRAMEWORK['DEFAULT_AUTHENTICATION_CLASSES']`.

---

## 6. Views — `deposits/views.py`

### 6.1 QRISDepositInitiateView

```python
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import permissions
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from decimal import Decimal, InvalidOperation
from datetime import timedelta
import uuid
import logging

from .models import GatewaySettings, Deposit, QRISGateway
from products.models import Transaction

logger = logging.getLogger(__name__)


def _now_wib():
    """Return current datetime in Asia/Jakarta."""
    from django.utils import timezone
    return timezone.localtime(timezone.now())


class QRISDepositInitiateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "deposit_initiate"

    def post(self, request):
        gs = GatewaySettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.qris_enabled)
        min_qris = (gs.qris_min_deposit_amount or Decimal("0")) if gs else Decimal("0")
        max_qris = (gs.qris_max_deposit_amount or Decimal("0")) if gs else Decimal("0")

        if not enabled:
            return Response(
                {"detail": "Layanan sedang tidak tersedia"},
                status=status.HTTP_400_BAD_REQUEST
            )

        qris_gw = QRISGateway.get_random_active()
        if not qris_gw:
            return Response(
                {"detail": "Tidak ada QRIS aktif. Silakan hubungi admin."},
                status=status.HTTP_400_BAD_REQUEST
            )
        if not qris_gw.qris_raw_data:
            return Response(
                {"detail": "QRIS raw data kosong. Silakan hubungi admin."},
                status=status.HTTP_400_BAD_REQUEST
            )

        wallet_type = (request.data.get("wallet_type") or gs.default_wallet_type or "BALANCE").strip().upper()
        if wallet_type not in ("BALANCE", "BALANCE_DEPOSIT"):
            return Response({"detail": "wallet_type tidak valid"}, status=status.HTTP_400_BAD_REQUEST)

        amount_raw = request.data.get("amount")
        try:
            amount = Decimal(str(amount_raw)).quantize(Decimal("0.01"))
            if amount <= 0:
                raise InvalidOperation()
        except Exception:
            return Response({"detail": "amount tidak valid"}, status=status.HTTP_400_BAD_REQUEST)

        if min_qris > 0 and amount < min_qris:
            return Response(
                {"detail": f"Minimal deposit QRIS adalah {min_qris}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if max_qris > 0 and amount > max_qris:
            return Response(
                {"detail": f"Maksimal deposit QRIS adalah {max_qris}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = request.user
        order_num = f"DQRS{_now_wib().strftime('%y%m%d%H%M%S')}{uuid.uuid4().hex[:6].upper()}"

        from .integrations.qris import convert_static_to_dynamic, generate_unique_amount_code, generate_qr_image_file

        # Generate 3-digit unique code (100-300)
        unique_code = generate_unique_amount_code()
        qris_amount = int(amount) + unique_code

        # Konversi static QRIS -> dynamic QRIS
        try:
            dynamic_qris = convert_static_to_dynamic(qris_gw.qris_raw_data, Decimal(qris_amount))
        except Exception as e:
            logger.error("QRIS convert_static_to_dynamic error: %s", e)
            return Response(
                {"detail": "Gagal mengkonversi QRIS static ke dynamic."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

        # Generate QR image file
        qr_filename = f"{order_num}.png"
        qr_image_url = generate_qr_image_file(dynamic_qris, "qris/dynamic", qr_filename)

        qris_gw.used_count = qris_gw.used_count + 1
        qris_gw.save(update_fields=["used_count"])

        trx = Transaction.objects.create(
            user=user,
            product=None,
            type="DEPOSIT",
            amount=amount,
            currency_code="IDR",
            description=f"Deposit via QRIS ({wallet_type})",
            status="PENDING",
            wallet_type=wallet_type,
            trx_id=order_num,
        )

        # Hitung expired time
        expired_minutes = gs.qris_expired_minutes if gs else 30
        expired_at = _now_wib() + timedelta(minutes=expired_minutes) if expired_minutes > 0 else None

        dep = Deposit.objects.create(
            user=user,
            gateway="QRIS",
            order_num=order_num,
            amount=amount,
            amount_currency_code="IDR",
            wallet_type=wallet_type,
            status="PENDING",
            transaction=trx,
            expired_at=expired_at,
            request_params={
                "qris_label": qris_gw.label,
                "qris_gateway_id": qris_gw.pk,
                "unique_code": unique_code,
                "qris_amount": qris_amount,
                "requested_amount": int(amount),
                "dynamic_qris": dynamic_qris,
            },
            payment_url=qr_image_url or "",
        )

        return Response(
            {
                "order_num": order_num,
                "unique_code": unique_code,
                "amount": f"{amount:.2f}",
                "qris_amount": qris_amount,
                "qris_label": qris_gw.label,
                "qr_image": qr_image_url,
                "expired_at": expired_at.isoformat() if expired_at else None,
                "expired_minutes": expired_minutes,
                "message": f"Silakan transfer tepat Rp {qris_amount:,} (kode unik: {unique_code})",
            },
            status=status.HTTP_200_OK,
        )
```

### 6.2 QRISDepositAcceptView (admin manual callback)

```python
@method_decorator(csrf_exempt, name='dispatch')
class QRISDepositAcceptView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        order_num = (request.data.get("order_num") or "").strip()
        if not order_num:
            return Response({"detail": "order_num wajib diisi"}, status=status.HTTP_400_BAD_REQUEST)

        trx = Transaction.objects.filter(trx_id=order_num, type="DEPOSIT").first()
        dep = Deposit.objects.filter(order_num=order_num, gateway="QRIS").first()

        if not trx or not dep:
            return Response({"detail": "Deposit tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)
        if dep.status == "COMPLETED":
            return Response(
                {"detail": "Deposit sudah selesai", "status": "COMPLETED"},
                status=status.HTTP_200_OK
            )
        if dep.status == "FAILED":
            return Response(
                {"detail": "Deposit sudah gagal, tidak bisa di-accept"},
                status=status.HTTP_400_BAD_REQUEST
            )
        if dep.is_expired:
            return Response(
                {"detail": "Deposit sudah expired, tidak bisa di-accept"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Gunakan fungsi complete deposit yang sudah ada di project
        _complete_deposit(trx, dep)

        dep.callback_payload = {
            "accepted_by": request.user.username,
            "accepted_at": timezone.now().isoformat(),
            "method": "manual_accept",
        }
        dep.callback_at = timezone.now()
        dep.save(update_fields=["callback_payload", "callback_at"])

        return Response(
            {
                "order_num": order_num,
                "status": "COMPLETED",
                "credited_amount": f"{dep.credited_amount:.2f}" if dep.credited_amount else f"{trx.amount:.2f}",
            },
            status=status.HTTP_200_OK,
        )
```

### 6.3 QRISDepositRejectView

```python
@method_decorator(csrf_exempt, name='dispatch')
class QRISDepositRejectView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def post(self, request):
        order_num = (request.data.get("order_num") or "").strip()
        reason = (request.data.get("reason") or "Ditolak admin").strip()

        if not order_num:
            return Response({"detail": "order_num wajib diisi"}, status=status.HTTP_400_BAD_REQUEST)

        trx = Transaction.objects.filter(trx_id=order_num, type="DEPOSIT").first()
        dep = Deposit.objects.filter(order_num=order_num, gateway="QRIS").first()

        if not trx or not dep:
            return Response({"detail": "Deposit tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)

        # Gunakan fungsi mark failed yang sudah ada di project
        _mark_deposit_failed(trx, dep, reason=reason)

        dep.callback_payload = {
            "rejected_by": request.user.username,
            "rejected_at": timezone.now().isoformat(),
            "reason": reason,
        }
        dep.callback_at = timezone.now()
        dep.save(update_fields=["callback_payload", "callback_at"])

        return Response(
            {"order_num": order_num, "status": "FAILED", "reason": reason},
            status=status.HTTP_200_OK,
        )
```

### 6.4 Helper functions untuk complete/failed deposit

```python
from django.db import transaction as db_transaction


def _mark_deposit_failed(trx, dep, reason=""):
    """Mark transaction & deposit as FAILED."""
    if trx.status not in ("PENDING", "PROCESSING"):
        return
    update_fields = ["status"]
    trx.status = "FAILED"
    if reason:
        trx.description = ((trx.description or "").strip() + f" [{reason}]").strip()
        update_fields.append("description")
    trx.save(update_fields=update_fields)
    if dep:
        dep.status = "FAILED"
        dep.save(update_fields=["status"])


def _complete_deposit(trx, dep, paid_amount=None):
    """Complete deposit: credit user wallet, mark COMPLETED."""
    if trx.status == "COMPLETED":
        return

    expected_amount = Decimal(str(trx.amount or 0)).quantize(Decimal("0.01"))
    if paid_amount is not None and paid_amount > 0 and paid_amount != expected_amount:
        _mark_deposit_failed(trx, dep, reason="Amount mismatch")
        return

    from django.contrib.auth import get_user_model

    wallet_field = "balance" if trx.wallet_type == "BALANCE" else "balance_deposit"
    credited_amount = expected_amount
    currency_code = (trx.currency_code or "IDR").strip().upper() or "IDR"
    UserModel = get_user_model()

    with db_transaction.atomic():
        trx_locked = Transaction.objects.select_for_update().select_related("user").get(pk=trx.pk)
        if trx_locked.status == "COMPLETED":
            return
        user_locked = UserModel.objects.select_for_update().get(pk=trx_locked.user_id)
        current_balance = getattr(user_locked, wallet_field)
        setattr(user_locked, wallet_field, current_balance + credited_amount)
        user_locked.save(update_fields=[wallet_field])

        trx_locked.status = "COMPLETED"
        trx_locked.currency_code = currency_code
        trx_locked.amount = credited_amount
        trx_locked.save(update_fields=["status", "currency_code", "amount"])

        if dep:
            dep.status = "COMPLETED"
            dep.credited_amount = credited_amount
            dep.credited_currency_code = currency_code
            if not dep.amount_currency_code:
                dep.amount_currency_code = currency_code
            dep.save(update_fields=[
                "status", "credited_amount",
                "credited_currency_code", "amount_currency_code"
            ])
```

---

## 7. URLs — `deposits/urls.py`

```python
from .views import (
    # ... views yang sudah ada ...
    QRISDepositInitiateView,
    QRISDepositAcceptView,
    QRISDepositRejectView,
)

urlpatterns = [
    # ... existing routes ...
    path('qris/initiate/', QRISDepositInitiateView.as_view(), name='deposit-qris-initiate'),
    path('qris/accept/', QRISDepositAcceptView.as_view(), name='deposit-qris-accept'),
    path('qris/reject/', QRISDepositRejectView.as_view(), name='deposit-qris-reject'),
]
```

---

## 8. Admin — `deposits/admin.py`

### 8.1 GatewaySettings — tambahkan QRIS section

```python
('QRIS Manual', {
    'fields': (
        'qris_min_deposit_amount',
        'qris_max_deposit_amount',
        'qris_expired_minutes',
    ),
    'description': 'QRIS Manual: upload QR static di menu QRIS Gateway.',
}),
```

### 8.2 QRISGatewayAdmin

```python
from .models import QRISGateway


@admin.register(QRISGateway)
class QRISGatewayAdmin(admin.ModelAdmin):
    list_display = ('label', 'is_active', 'used_count', 'max_use_count', 'created_at')
    list_filter = ('is_active',)
    search_fields = ('label', 'qris_raw_data')
    readonly_fields = ('used_count', 'created_at', 'updated_at')
    fieldsets = (
        (None, {
            'fields': ('label', 'is_active', 'max_use_count', 'used_count')
        }),
        ('QRIS Data', {
            'fields': ('qris_image', 'qris_raw_data'),
            'description': 'Upload gambar QR dan/atau paste raw QRIS string hasil scan (dimulai dengan 000201...). '
                           'QRIS static akan otomatis dikonversi jadi dynamic dengan nominal deposit saat user request.'
        }),
    )
```

### 8.3 DepositAdmin — tambahkan actions & display

```python
from django.contrib import messages
from django.db import transaction as db_transaction
from django.utils import timezone


class DepositAdmin(admin.ModelAdmin):
    # ... existing config ...
    actions = ['accept_qris_deposit', 'reject_qris_deposit']

    @admin.display(description='Jumlah', ordering='amount')
    def amount_display(self, obj):
        val = obj.display_amount
        if obj.gateway == 'QRIS' and obj.unique_code:
            return f'Rp {val:,.0f} (kode: {obj.unique_code})'
        return f'Rp {val:,.0f}'

    @admin.display(description='Kode Unik')
    def unique_code(self, obj):
        return obj.unique_code or '-'

    @admin.display(description='Expired', ordering='expired_at')
    def expired_status(self, obj):
        if obj.expired_at:
            if obj.is_expired:
                return 'EXPIRED'
            return obj.expired_at.strftime('%H:%M')
        return '-'

    @admin.action(description='Terima deposit QRIS (credit saldo user)')
    def accept_qris_deposit(self, request, queryset):
        accepted = 0
        skipped_expired = 0
        for dep in queryset.filter(gateway='QRIS', status='PENDING'):
            if dep.is_expired:
                skipped_expired += 1
                continue
            trx = dep.transaction
            if not trx:
                continue
            with db_transaction.atomic():
                trx = type(trx).objects.select_for_update().get(pk=trx.pk)
                if trx.status == 'COMPLETED':
                    continue
                _complete_deposit(trx, dep)  # pakai fungsi yang sama dengan view
                dep.callback_payload = {
                    "accepted_by": request.user.username,
                    "accepted_at": timezone.now().isoformat(),
                    "method": "admin_bulk_accept",
                }
                dep.callback_at = timezone.now()
                dep.save(update_fields=['callback_payload', 'callback_at'])
                accepted += 1
        if accepted:
            msg = f'{accepted} deposit QRIS berhasil diterima.'
            if skipped_expired:
                msg += f' {skipped_expired} expired dilewati.'
            self.message_user(request, msg, messages.SUCCESS)
        else:
            self.message_user(request, 'Tidak ada deposit QRIS pending.', messages.WARNING)

    @admin.action(description='Tolak deposit QRIS')
    def reject_qris_deposit(self, request, queryset):
        rejected = 0
        for dep in queryset.filter(gateway='QRIS', status='PENDING'):
            trx = dep.transaction
            if not trx:
                continue
            _mark_deposit_failed(trx, dep, reason='Ditolak admin')
            dep.callback_payload = {
                "rejected_by": request.user.username,
                "rejected_at": timezone.now().isoformat(),
                "reason": "Ditolak admin",
            }
            dep.callback_at = timezone.now()
            dep.save(update_fields=['callback_payload', 'callback_at'])
            rejected += 1
        if rejected:
            self.message_user(request, f'{rejected} deposit QRIS ditolak.', messages.SUCCESS)
        else:
            self.message_user(request, 'Tidak ada deposit QRIS pending.', messages.WARNING)
```

### 8.4 GatewaySettings — singleton enforcement

```python
class GatewaySettingsAdmin(admin.ModelAdmin):
    # ... existing config ...

    def has_add_permission(self, request):
        # Singleton: jangan izinkan tambah record baru kalau sudah ada
        return not GatewaySettings.objects.exists()
```

---

## 9. Migration

Buat 1 file migration (contoh: `0018_qris_gateway.py`) yang mencakup SEMUA perubahan:

```python
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deposits', '0017_extend_payment_url'),  # sesuaikan dengan migration terakhir
    ]

    operations = [
        # GatewaySettings: enable + min/max/expired
        migrations.AddField(
            model_name='gatewaysettings',
            name='qris_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='gatewaysettings',
            name='qris_min_deposit_amount',
            field=models.DecimalField(
                decimal_places=2, default=10000,
                help_text='Minimal nominal deposit QRIS', max_digits=15
            ),
        ),
        migrations.AddField(
            model_name='gatewaysettings',
            name='qris_max_deposit_amount',
            field=models.DecimalField(
                decimal_places=2, default=5000000,
                help_text='Maksimal nominal deposit QRIS (0 = tidak dibatasi)', max_digits=15
            ),
        ),
        migrations.AddField(
            model_name='gatewaysettings',
            name='qris_expired_minutes',
            field=models.PositiveIntegerField(
                default=30, help_text='QR kadaluarsa setelah berapa menit (0 = tidak kadaluarsa)'
            ),
        ),
        # Deposit: expired_at + update gateway choices
        migrations.AddField(
            model_name='deposit',
            name='expired_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='deposit',
            name='gateway',
            field=models.CharField(
                choices=[
                    ('JAYAPAY', 'Jayapay'),
                    ('JAYAPAY_PH', 'Jayapay Philippines'),
                    ('KLIKPAY', 'Klikpay'),
                    ('USD_GATEWAY', 'USD Gateway'),
                    ('PPAYPROS', 'PPay Pros'),
                    ('CLIENTHUB', 'ClientHub'),
                    ('SITRANSFERHUB', 'SiTransfer Hub'),
                    ('ATPAY', 'ATPAY'),
                    ('BANKPAY', 'BankPay'),
                    ('QRIS', 'QRIS Manual'),
                ],
                max_length=20
            ),
        ),
        # QRISGateway model
        migrations.CreateModel(
            name='QRISGateway',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('label', models.CharField(help_text='Label/nama QRIS', max_length=100)),
                ('qris_image', models.ImageField(blank=True, help_text='Upload gambar QRIS static', null=True, upload_to='qris/images/')),
                ('qris_raw_data', models.TextField(blank=True, default='', help_text='Raw QRIS string hasil scan (0002010102...)')),
                ('is_active', models.BooleanField(default=True, help_text='Aktifkan QR ini untuk digunakan')),
                ('max_use_count', models.PositiveIntegerField(default=0, help_text='Maksimal penggunaan (0 = unlimited)')),
                ('used_count', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'QRIS Gateway',
                'verbose_name_plural': 'QRIS Gateway',
                'ordering': ['-created_at'],
                'db_table': 'deposits_qris_gateway',
            },
        ),
    ]
```

Jalankan:

```bash
python manage.py migrate deposits
```

---

## 10. Settings — `config/settings.py`

Pastikan sudah ada:

```python
MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
```

Dan di `config/urls.py`:

```python
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # ... url patterns ...
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

---

## 11. REST_FRAMEWORK Auth — `config/settings.py`

Pastikan menggunakan custom `SessionAuthentication`:

```python
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'accounts.auth.BannedAwareJWTAuthentication',
        'accounts.auth.BannedAwareSessionAuthentication',  # <-- custom
    ],
    # ...
}
```

---

## 12. API Endpoints

### 12.1 Initiate Deposit QRIS

```
POST /api/deposits/qris/initiate/
Authorization: Bearer <jwt_token>
Content-Type: application/json

{
    "amount": 10000,
    "wallet_type": "BALANCE"    // optional, default: BALANCE
}
```

**Response (200):**

```json
{
    "order_num": "DQRS260808120000A1B2C3",
    "unique_code": 112,
    "amount": "10000.00",
    "qris_amount": 10112,
    "qris_label": "QRIS BCA",
    "qr_image": "/media/qris/dynamic/DQRS260808120000A1B2C3.png",
    "expired_at": "2026-08-08T12:30:00+07:00",
    "expired_minutes": 30,
    "message": "Silakan transfer tepat Rp 10,112 (kode unik: 112)"
}
```

### 12.2 Accept Deposit (Admin)

```
POST /api/deposits/qris/accept/
Authorization: Bearer <admin_jwt>

{
    "order_num": "DQRS260808120000A1B2C3"
}
```

### 12.3 Reject Deposit (Admin)

```
POST /api/deposits/qris/reject/
Authorization: Bearer <admin_jwt>

{
    "order_num": "DQRS260808120000A1B2C3",
    "reason": "Pembayaran tidak sesuai"
}
```

---

## 13. Cara Pakai di Admin Panel

1. **Aktifkan QRIS**: Buka `Gateway Settings` → centang `qris_enabled` → atur min/max/expired → Save.

2. **Upload QR static**:
   - Buka `QRIS Gateway` → Add
   - Isi label (misal: "QRIS BCA")
   - Upload gambar QR (atau paste raw string `0002010102...` langsung)
   - Set `max_use_count` jika ingin batasi (0 = unlimited)
   - Save → sistem otomatis decode QR dari gambar

3. **Verifikasi deposit**:
   - Buka menu `Deposits`
   - Filter `gateway = QRIS`, `status = PENDING`
   - Cek nominal + kode unik
   - Pilih deposit → Action dropdown → "Terima deposit QRIS" / "Tolak deposit QRIS"
   - Atau buka detail deposit → ubah status manual

---

## 14. Catatan Penting

- **QRIS TLV Format**: Data QRIS adalah string TLV (`[tag 2 digit][length 2 digit][value]`). `sanitize_qris_string()` hanya menghapus newline, **tidak** menghapus spasi karena spasi adalah karakter valid dalam value (nama merchant, kota).
- **CRC16-CCITT**: Polynomial `0x1021`, Init `0xFFFF`. CRC dihitung ulang setiap konversi static→dynamic.
- **Konversi Static→Dynamic**: Mengubah tag `01` dari `11` ke `12`, menyisipkan tag `54` (amount) sebelum tag `58`, menghapus tag `63` lama lalu recalculate.
- **File gambar QR**: Disimpan di `MEDIA_ROOT/qris/dynamic/` sebagai PNG, bukan base64 di DB.
- **Docker**: Butuh `libgl1` + `libglib2.0-0` untuk OpenCV (`cv2.QRCodeDetector`). Di Debian 12 ke bawah pakai `libgl1-mesa-glx`.
