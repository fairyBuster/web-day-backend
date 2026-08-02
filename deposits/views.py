from django.conf import settings
from django.utils import timezone
from django.db import transaction as db_transaction
from django.shortcuts import redirect
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework import status, permissions
from drf_spectacular.utils import extend_schema, OpenApiParameter, OpenApiTypes, OpenApiExample
from decimal import Decimal, InvalidOperation
import random
import uuid
import requests
import hashlib
import hmac
import time as pytime
import logging
import json
import re
from django.http import HttpResponse
from urllib.parse import urlparse, parse_qs

from products.models import Transaction
from products.serializers import TransactionSerializer
from .models import GatewaySettings, Deposit
from .integrations.ppaypros import (
    amount_to_points as ppaypros_amount_to_points,
    extract_payment_data as ppaypros_extract_payment_data,
    generate_sign as ppaypros_generate_sign,
    parse_data_field as ppaypros_parse_data_field,
    points_to_amount as ppaypros_points_to_amount,
    post_json as ppaypros_post_json,
    verify_sign as ppaypros_verify_sign,
)
from .integrations.clienthub import (
    build_create_transaction_payload as clienthub_build_create_transaction_payload,
    dumps_raw_json as clienthub_dumps_raw_json,
    post_create_transaction as clienthub_post_create_transaction,
    sign_client_request as clienthub_sign_client_request,
    verify_callback_signature as clienthub_verify_callback_signature,
)
from .integrations.sitransferhub import (
    build_create_transaction_payload as sitransferhub_build_create_transaction_payload,
    dumps_raw_json as sitransferhub_dumps_raw_json,
    post_create_transaction as sitransferhub_post_create_transaction,
    sign_client_request as sitransferhub_sign_client_request,
    verify_callback_signature as sitransferhub_verify_callback_signature,
)
from .integrations.atpay import (
    build_deposit_payload as atpay_build_deposit_payload,
    build_deposit_query_payload as atpay_build_deposit_query_payload,
    map_deposit_trade_status as atpay_map_deposit_trade_status,
    normalize_amount as atpay_normalize_amount,
    normalize_sign_type as atpay_normalize_sign_type,
    post_json as atpay_post_json,
    sign_payload as atpay_sign_payload,
    verify_payload as atpay_verify_payload,
    fetch_wowpayidr_va as atpay_fetch_wowpayidr_va,
)
from withdrawal.integrations.jayapay import sign_params_legacy
from .integrations.klikpay import build_params as klikpay_build_params, sign_params as klikpay_sign_params, send_prepaid_request as klikpay_send_prepaid
from .utils import verify_jayapay_signature
from django.db.models import Q
from zoneinfo import ZoneInfo
from datetime import datetime, time, timedelta

logger = logging.getLogger(__name__)


def format_datetime(dt):
    return dt.strftime('%Y%m%d%H%M%S')

def _now_wib():
    now = timezone.now()
    if timezone.is_aware(now):
        return timezone.localtime(now, ZoneInfo("Asia/Jakarta"))
    return now


def _get_client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR")
    if xff:
        return xff.split(",")[0].strip()
    return (request.META.get("REMOTE_ADDR") or "").strip()


def _strip_backticks(value: str) -> str:
    return (value or "").replace("`", "").strip()


def _redact_provider_payload_for_log(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if k == "sign":
                out[k] = "<redacted>"
                continue
            out[k] = _redact_provider_payload_for_log(v)
        return out
    if isinstance(value, list):
        return [_redact_provider_payload_for_log(v) for v in value]
    return value


def _convert_amount_to_main_currency(amount: Decimal, from_currency_code: str):
    from accounts.models import GeneralSetting

    from_code = (from_currency_code or "IDR").strip().upper()
    gs = GeneralSetting.objects.order_by("-updated_at").first()
    main_code = (getattr(gs, "currency_code", None) or "IDR").strip().upper() if gs else "IDR"
    secondary_code = (getattr(gs, "secondary_currency_code", None) or "").strip().upper() if gs else ""
    secondary_per_main = getattr(gs, "secondary_rate_per_main", None) if gs else None

    if from_code == main_code:
        return amount, main_code, Decimal("1"), Decimal("0")


def _grant_deposit_cashback(user, deposit_trx: Transaction, credited_amount: Decimal, currency_code: str):
    from accounts.models import GeneralSetting, User

    gs = GeneralSetting.objects.order_by("-updated_at").first()
    if not gs or not bool(getattr(gs, "deposit_cashback_enabled", False)):
        return Decimal("0.00")

    try:
        percent = Decimal(str(getattr(gs, "deposit_cashback_percent", 0) or 0))
    except Exception:
        percent = Decimal("0")
    if percent <= 0:
        return Decimal("0.00")

    cashback_amount = (Decimal(str(credited_amount or 0)) * percent / Decimal("100")).quantize(Decimal("0.01"))
    if cashback_amount <= 0:
        return Decimal("0.00")

    exists = Transaction.objects.filter(
        type="CASHBACK_DEPOSIT",
        related_transaction=deposit_trx,
    ).exists()
    if exists:
        return Decimal("0.00")

    with db_transaction.atomic():
        user_locked = User.objects.select_for_update().get(pk=user.pk)
        exists2 = Transaction.objects.filter(
            type="CASHBACK_DEPOSIT",
            related_transaction=deposit_trx,
        ).exists()
        if exists2:
            return Decimal("0.00")
        current_val = getattr(user_locked, "balance_cashback", Decimal("0")) or Decimal("0")
        user_locked.balance_cashback = current_val + cashback_amount
        user_locked.save(update_fields=["balance_cashback"])
        Transaction.objects.create(
            user=user_locked,
            type="CASHBACK_DEPOSIT",
            amount=cashback_amount,
            description=f"Deposit cashback {percent}% from deposit {deposit_trx.trx_id}",
            status="COMPLETED",
            wallet_type="BALANCE_CASHBACK",
            currency_code=(currency_code or "").strip().upper(),
            related_transaction=deposit_trx,
        )
    return cashback_amount

    if secondary_code and secondary_code != main_code and from_code == secondary_code:
        try:
            rate = Decimal(str(secondary_per_main or "0"))
        except Exception:
            rate = Decimal("0")
        if rate > 0:
            converted = (Decimal(str(amount)) / rate).quantize(Decimal("0.01"))
            return converted, main_code, rate, Decimal("0")

    return amount, from_code, Decimal("0"), Decimal("0")


def _extract_payment_url(value):
    preferred_keys = (
        "payUrl",
        "pay_url",
        "paymentUrl",
        "payment_url",
        "cashierUrl",
        "cashier_url",
        "h5Url",
        "h5_url",
        "redirectUrl",
        "redirect_url",
        "url",
    )
    ignore_keys = {"notifyUrl", "notify_url", "pageUrl", "page_url", "sign"}
    if isinstance(value, dict):
        for k in preferred_keys:
            v = value.get(k)
            if isinstance(v, str) and v.strip().lower().startswith(("http://", "https://")):
                return v.strip(), k
        for k, v in value.items():
            if k in ignore_keys:
                continue
            found, path = _extract_payment_url(v)
            if found:
                return found, f"{k}.{path}" if path else k
        return "", ""
    if isinstance(value, list):
        for i, item in enumerate(value):
            found, path = _extract_payment_url(item)
            if found:
                return found, f"[{i}].{path}" if path else f"[{i}]"
        return "", ""
    if isinstance(value, str):
        s = value.strip()
        if s.startswith("{") and s.endswith("}"):
            try:
                parsed = json.loads(s)
                return _extract_payment_url(parsed)
            except Exception:
                pass
        m = re.search(r"https?://[^\s\"'<>]+", s)
        if m:
            return m.group(0), ""
    return "", ""


def _scrape_qr_image_from_url(url: str, timeout: int = 30) -> str | None:
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        html = resp.text
    except Exception as e:
        logger.warning("Gagal fetch QR page: url=%s error=%s", url, str(e))
        return None
    m = re.search(r'<img[^>]*\ssrc="(data:image/[^"]*base64,[^"]+)"', html, re.IGNORECASE)
    if m:
        return m.group(1)
    return None


def _usd_gateway_sign(payload: dict, sign_key: str, *, hex_key: bool = False) -> str:
    sign_key = (sign_key or "").strip()
    if hex_key:
        try:
            key_bytes = bytes.fromhex(sign_key)
        except Exception:
            key_bytes = sign_key.encode("utf-8")
    else:
        key_bytes = sign_key.encode("utf-8")
    items = []
    for k in sorted(payload.keys()):
        if k == "sign":
            continue
        v = payload.get(k)
        if v is None or v == "":
            continue
        items.append(f"{k}={v}")
    raw = "&".join(items)
    return hmac.new(key_bytes, raw.encode("utf-8"), hashlib.sha256).hexdigest()


JAYAPAY_ID_PAYMENT_METHODS = [
    "BCA",
    "MANDIRI",
    "PERMATA",
    "CIMB",
    "BNI",
    "MAYBANK",
    "DANAMON",
    "BRI",
    "BSI",
    "BNC",
    "OVO",
    "DANA",
    "DANA_QRIS",
    "LINKAJA",
    "SHOPEEPAY",
    "QRIS",
    "GOPAY_QRIS",
    "ALFAMART",
    "TRANSFER_BCA",
]

CLIENTHUB_ORDER_ITEM_CODES = [
    f"{prefix}{number:03d}"
    for prefix in ("PRM", "CHN", "BKK")
    for number in range(1, 101)
]
CLIENTHUB_ORDER_ITEM_LABELS = [
    "Tagihan supplier dress wanita",
    "Tagihan supplier blouse wanita",
    "Tagihan supplier lingerie wanita",
    "Tagihan supplier set pakaian wanita",
    "Pembelian dress wanita",
    "Pembelian blouse wanita",
    "Pembelian lingerie wanita",
    "Pembelian pakaian seksi wanita",
    "Pembelian koleksi fashion wanita",
    "Pembelian outfit wanita",
]
CLIENTHUB_ITEM_MIN_PRICE = 50000
CLIENTHUB_ITEM_MAX_PRICE = 500000


def _build_clienthub_order_item(amount: Decimal) -> dict:
    total_amount = int(Decimal(str(amount or 0)).quantize(Decimal("1")))
    item_code = random.choice(CLIENTHUB_ORDER_ITEM_CODES)
    item_name = f"{random.choice(CLIENTHUB_ORDER_ITEM_LABELS)} {item_code}"

    if total_amount <= 100000:
        quantity = 1
    else:
        min_quantity = max(1, (total_amount + CLIENTHUB_ITEM_MAX_PRICE - 1) // CLIENTHUB_ITEM_MAX_PRICE)
        max_quantity = max(1, total_amount // CLIENTHUB_ITEM_MIN_PRICE)
        target_quantity = min(max(1, total_amount // 90000), max_quantity)
        candidate_quantities = [
            qty
            for qty in range(min_quantity, max_quantity + 1)
            if total_amount % qty == 0 and CLIENTHUB_ITEM_MIN_PRICE <= (total_amount // qty) <= CLIENTHUB_ITEM_MAX_PRICE
        ]
        if candidate_quantities:
            quantity = min(candidate_quantities, key=lambda qty: abs(qty - target_quantity))
        else:
            quantity = 1

    unit_price = max(1, total_amount // quantity)

    return {
        "sku": item_code,
        "name": item_name,
        "price": unit_price,
        "quantity": quantity,
    }


def _extract_jayapay_plat_order_num_from_payment_url(payment_url: str) -> str:
    try:
        parsed = urlparse(payment_url or "")
        qs = parse_qs(parsed.query or "")
        value = qs.get("orderNum") or qs.get("ordernum") or []
        if value and value[0]:
            return str(value[0]).strip()
    except Exception:
        return ""
    return ""


def _jayapay_cash_detail_endpoint(payment_url: str) -> str:
    parsed = urlparse(payment_url or "")
    if not parsed.scheme or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/gateway/order/detail/v2"


def _fetch_jayapay_cash_order_detail(payment_url: str, plat_order_num: str, merchant_order_num: str = "", method: str = "") -> dict:
    payment_url = _strip_backticks(payment_url)
    endpoint = _jayapay_cash_detail_endpoint(payment_url)
    if not endpoint or not plat_order_num:
        return {}

    method = (method or "").strip().upper()
    parsed = urlparse(payment_url or "")
    origin = f"{parsed.scheme}://{parsed.netloc}" if parsed.scheme and parsed.netloc else ""
    qs = parse_qs(parsed.query or "")
    md = (qs.get("MD") or [""])[0]
    sg = (qs.get("SG") or [""])[0]
    sx = (qs.get("SX") or [""])[0]
    sv = (qs.get("SV") or [""])[0]
    sn = (qs.get("SN") or [""])[0]

    fingerprint_seed = f"{plat_order_num}{md}{sg}{sx}{sv}{sn}"
    fingerprint = hashlib.md5(fingerprint_seed.encode("utf-8")).hexdigest()
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "ordernum": plat_order_num,
        "browser-fingerprint": fingerprint,
        "origin": origin,
        "referer": payment_url,
        "user-agent": "Mozilla/5.0",
        "accept-language": "en-GB,en-US;q=0.9,en;q=0.8,id;q=0.7",
    }

    json_bodies = [
        {"orderNum": plat_order_num, "method": method} if method else {"orderNum": plat_order_num},
        {"orderNum": plat_order_num, "MD": md, "SG": sg, "SX": sx, "SV": sv, "SN": sn, "method": method} if method else {"orderNum": plat_order_num, "MD": md, "SG": sg, "SX": sx, "SV": sv, "SN": sn},
    ]
    last_error = None
    best_error = None
    attempts = []
    session = requests.Session()
    try:
        session.get(
            payment_url,
            headers={
                "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "user-agent": headers["user-agent"],
            },
            timeout=15,
            allow_redirects=True,
        )
    except Exception as e:
        last_error = {"step": "warmup_get", "error": str(e)}

    def _choose_best_error(err: dict):
        nonlocal best_error
        if not best_error:
            best_error = err
            return
        def _score(e: dict) -> int:
            http_status = int(e.get("http_status") or 0) if str(e.get("http_status") or "").isdigit() else 0
            payload = e.get("payload") if isinstance(e.get("payload"), dict) else {}
            code = payload.get("code")
            msg = str(payload.get("msg") or "")
            step = str(e.get("step") or "")
            kind = str(e.get("request_kind") or "")
            score = 0
            if step == "provider_response":
                score += 100
            if http_status == 200:
                score += 50
            if code is not None:
                score += 20
            if "ordernum" in msg.lower():
                score += 10
            if kind == "json":
                score += 5
            if kind == "query":
                score += 3
            if kind == "form":
                score += 1
            return score
        if _score(err) >= _score(best_error):
            best_error = err

    def _handle_response(resp, *, request_kind: str, request_meta: dict):
        nonlocal last_error
        content_type = (resp.headers.get("content-type") or "").lower()
        try:
            data = resp.json() if resp.content else {}
        except Exception as e:
            text_head = (resp.text or "")[:240]
            last_error = {
                "step": "json_decode",
                "request_kind": request_kind,
                "request_meta": request_meta,
                "http_status": resp.status_code,
                "content_type": content_type,
                "text_head": text_head,
                "error": str(e),
            }
            _choose_best_error(last_error)
            return None

        if isinstance(data, dict) and (data.get("code") == 0 or str(data.get("msg") or "").lower() == "success"):
            return data
        if isinstance(data, dict) and isinstance(data.get("data"), dict) and data.get("data"):
            return data

        last_error = {
            "step": "provider_response",
            "request_kind": request_kind,
            "request_meta": request_meta,
            "http_status": resp.status_code,
            "content_type": content_type,
            "payload": data,
        }
        _choose_best_error(last_error)
        return None

    for body in json_bodies:
        try:
            resp = session.post(endpoint, json=body, headers=headers, timeout=15)
        except Exception as e:
            last_error = {"step": "post", "request_kind": "json", "request_meta": body, "error": str(e)}
            _choose_best_error(last_error)
            continue
        attempts.append({"request_kind": "json", "request_meta": body, "http_status": resp.status_code})
        out = _handle_response(resp, request_kind="json", request_meta=body)
        if out is not None:
            return out
    error_out = best_error or last_error
    if error_out:
        return {"_fetch_error": error_out, "_attempts": attempts[:8]}
    return {}


class JayapayDepositInitiateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'deposit_initiate'

    @extend_schema(
        summary="Inisiasi deposit via Jayapay",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "example": 100000},
                    "wallet_type": {"type": "string", "enum": ["BALANCE", "BALANCE_DEPOSIT"], "example": "BALANCE"},
                },
                "required": ["amount"],
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "order_num": {"type": "string", "example": "DEP-20250101XXXX-ABC123"},
                    "payment_url": {"type": "string", "example": "https://gateway.example/pay?id=..."},
                    "plat_order_num": {"type": "string", "example": "PTXXXXXXXXXXXX"},
                    "order_detail": {"type": "object"},
                },
            },
            400: {"description": "Permintaan tidak valid"},
            502: {"description": "Gagal menghubungi gateway"},
        },
    )
    def post(self, request):
        gs = GatewaySettings.objects.order_by('-updated_at').first()
        # Gunakan konfigurasi dari admin saja (tanpa fallback .env)
        jayapay_enabled = bool(gs and gs.jayapay_enabled)
        merchant_code = (gs.jayapay_merchant_code or '').strip() if gs else ''
        private_key = (gs.jayapay_private_key or '').strip() if gs else ''
        app_domain = (gs.app_domain or '').strip() if gs else ''
        min_deposit_amount = (gs.min_deposit_amount or Decimal('0')) if gs else Decimal('0')
        max_deposit_amount = (gs.max_deposit_amount or Decimal('0')) if gs else Decimal('0')

        if not jayapay_enabled:
            return Response({'detail': 'Jayapay tidak aktif'}, status=status.HTTP_400_BAD_REQUEST)
        if not merchant_code or not private_key:
            return Response({'detail': 'Konfigurasi Jayapay belum lengkap'}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({'detail': 'Konfigurasi domain untuk callback belum diisi'}, status=status.HTTP_400_BAD_REQUEST)

        wallet_type = (gs.default_wallet_type if gs and gs.default_wallet_type else 'BALANCE')
        if wallet_type not in ('BALANCE', 'BALANCE_DEPOSIT'):
            return Response({'detail': 'wallet_type tidak valid'}, status=status.HTTP_400_BAD_REQUEST)

        amount_raw = request.data.get('amount')
        try:
            amount = Decimal(str(amount_raw))
            if amount <= 0:
                raise InvalidOperation()
        except Exception:
            return Response({'detail': 'amount tidak valid'}, status=status.HTTP_400_BAD_REQUEST)
        
        if min_deposit_amount and min_deposit_amount > 0 and amount < min_deposit_amount:
            return Response({'detail': f'Minimal deposit adalah {min_deposit_amount}'}, status=status.HTTP_400_BAD_REQUEST)
        if max_deposit_amount and max_deposit_amount > 0 and amount > max_deposit_amount:
            return Response({'detail': f'Maksimal deposit adalah {max_deposit_amount}'}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        order_num = f"DEP-{_now_wib().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

        # Buat Transaction PENDING untuk deposit ini
        trx = Transaction.objects.create(
            user=user,
            product=None,
            type='DEPOSIT',
            amount=amount,
            currency_code='IDR',
            description=f'Deposit via Jayapay ({wallet_type})',
            status='PENDING',
            wallet_type=wallet_type,
            trx_id=order_num,
        )

        # Jayapay membutuhkan jumlah integer string
        pay_money = str(int(round(float(amount))))
        now = _now_wib()
        # Notify URL: gunakan endpoint statis agar konsisten
        notify_url = f"https://{app_domain}/api/deposits/jayapay/callback/"

        # Payload lengkap untuk prepaid order
        params = {
            'merchantCode': merchant_code,
            'orderType': '0',
            'method': '',
            'orderNum': order_num,
            'payMoney': pay_money,
            'name': user.full_name or user.username,
            'email': getattr(user, 'email', '') or '',
            'phone': getattr(user, 'phone', '') or '',
            'notifyUrl': notify_url,
            'dateTime': format_datetime(now),
            'expiryPeriod': '1000',
            'productDetail': 'Top Up Saldo',
        }

        try:
            # Tanda tangan gaya lama: private-encrypt berchunk atas seluruh nilai terurut
            sign = sign_params_legacy(params, private_key)
        except Exception as e:
            trx.status = 'FAILED'
            trx.save(update_fields=['status'])
            return Response({'detail': f'Gagal membuat signature: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        params['sign'] = sign

        # Catat Deposit sebelum request
        dep = Deposit.objects.create(
            user=user,
            gateway='JAYAPAY',
            order_num=order_num,
            amount=amount,
            amount_currency_code='IDR',
            wallet_type=wallet_type,
            status='PENDING',
            transaction=trx,
            request_params=params,
        )

        # Kirim ke Jayapay prepaidOrder
        try:
            jayapay_url = (gs.jayapay_api_url or '').strip() if gs else ''
            api_url = jayapay_url or 'https://openapi.jayapayment.com/gateway/prepaidOrder'
            resp = requests.post(api_url, json=params, timeout=30)
            data = resp.json()
        except Exception as e:
            trx.status = 'FAILED'
            trx.save(update_fields=['status'])
            dep.response_payload = {'error': str(e)}
            dep.status = 'FAILED'
            dep.save(update_fields=['response_payload', 'status'])
            return Response({'detail': f'Gagal menghubungi gateway: {str(e)}'}, status=status.HTTP_502_BAD_GATEWAY)

        if data.get('platRespCode') == 'SUCCESS':
            payment_url = _strip_backticks(data.get('url'))
            if payment_url:
                plat_order_num = _extract_jayapay_plat_order_num_from_payment_url(payment_url)
                order_detail = _fetch_jayapay_cash_order_detail(payment_url, plat_order_num, merchant_order_num=order_num)
                dep.payment_url = payment_url
                dep.response_payload = {"gateway": data, "plat_order_num": plat_order_num, "order_detail": order_detail}
                dep.save(update_fields=['payment_url', 'response_payload'])
                va_number, qris_payload = "", ""
                if isinstance(order_detail, dict):
                    od = order_detail.get("data") if isinstance(order_detail.get("data"), dict) else {}
                    va_raw = str(od.get("vaNumber") or "").strip()
                    if va_raw.startswith("000201"):
                        qris_payload = va_raw
                    else:
                        va_number = va_raw
                return Response({'order_num': order_num, 'payment_url': payment_url, 'plat_order_num': plat_order_num, 'order_detail': order_detail, 'va_number': va_number or None, 'qris_payload': qris_payload or None}, status=status.HTTP_200_OK)
            else:
                trx.status = 'FAILED'
                trx.save(update_fields=['status'])
                dep.response_payload = {"gateway": data}
                dep.status = 'FAILED'
                dep.save(update_fields=['response_payload', 'status'])
                return Response({'detail': 'Gateway tidak mengembalikan URL pembayaran'}, status=status.HTTP_502_BAD_GATEWAY)
        else:
            trx.status = 'FAILED'
            trx.save(update_fields=['status'])
            dep.response_payload = {"gateway": data}
            dep.status = 'FAILED'
            dep.save(update_fields=['response_payload', 'status'])
            return Response({'detail': data.get('platRespMessage') or 'Pembayaran gagal'}, status=status.HTTP_400_BAD_REQUEST)


class JayapayDepositInitiateDirectMethodView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'deposit_initiate'

    @extend_schema(
        summary="Inisiasi deposit via Jayapay (langsung pilih metode pembayaran)",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "example": 100000},
                    "method": {"type": "string", "enum": JAYAPAY_ID_PAYMENT_METHODS, "example": "BCA"},
                    "wallet_type": {"type": "string", "enum": ["BALANCE", "BALANCE_DEPOSIT"], "example": "BALANCE"},
                },
                "required": ["amount", "method"],
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "order_num": {"type": "string", "example": "DEP-20250101XXXX-ABC123"},
                    "payment_url": {"type": "string", "example": "https://gateway.example/pay?id=..."},
                    "plat_order_num": {"type": "string", "example": "PTXXXXXXXXXXXX"},
                    "order_detail": {"type": "object"},
                },
            },
            400: {"description": "Permintaan tidak valid"},
            502: {"description": "Gagal menghubungi gateway"},
        },
    )
    def post(self, request):
        gs = GatewaySettings.objects.order_by('-updated_at').first()
        jayapay_enabled = bool(gs and gs.jayapay_enabled)
        merchant_code = (gs.jayapay_merchant_code or '').strip() if gs else ''
        private_key = (gs.jayapay_private_key or '').strip() if gs else ''
        app_domain = (gs.app_domain or '').strip() if gs else ''
        min_deposit_amount = (gs.min_deposit_amount or Decimal('0')) if gs else Decimal('0')
        max_deposit_amount = (gs.max_deposit_amount or Decimal('0')) if gs else Decimal('0')

        if not jayapay_enabled:
            return Response({'detail': 'Jayapay tidak aktif'}, status=status.HTTP_400_BAD_REQUEST)
        if not merchant_code or not private_key:
            return Response({'detail': 'Konfigurasi Jayapay belum lengkap'}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({'detail': 'Konfigurasi domain untuk callback belum diisi'}, status=status.HTTP_400_BAD_REQUEST)

        wallet_type_raw = request.data.get('wallet_type')
        wallet_type = (str(wallet_type_raw).strip().upper() if wallet_type_raw else (gs.default_wallet_type if gs and gs.default_wallet_type else 'BALANCE'))
        if wallet_type not in ('BALANCE', 'BALANCE_DEPOSIT'):
            return Response({'detail': 'wallet_type tidak valid'}, status=status.HTTP_400_BAD_REQUEST)

        method_raw = request.data.get('method')
        method = (str(method_raw).strip().upper() if method_raw is not None else '')
        if not method:
            return Response({'detail': 'method wajib diisi'}, status=status.HTTP_400_BAD_REQUEST)
        if len(method) > 16:
            return Response({'detail': 'method terlalu panjang'}, status=status.HTTP_400_BAD_REQUEST)
        if method not in JAYAPAY_ID_PAYMENT_METHODS:
            return Response({'detail': 'method tidak valid'}, status=status.HTTP_400_BAD_REQUEST)

        amount_raw = request.data.get('amount')
        try:
            amount = Decimal(str(amount_raw))
            if amount <= 0:
                raise InvalidOperation()
        except Exception:
            return Response({'detail': 'amount tidak valid'}, status=status.HTTP_400_BAD_REQUEST)

        if min_deposit_amount and min_deposit_amount > 0 and amount < min_deposit_amount:
            return Response({'detail': f'Minimal deposit adalah {min_deposit_amount}'}, status=status.HTTP_400_BAD_REQUEST)
        if max_deposit_amount and max_deposit_amount > 0 and amount > max_deposit_amount:
            return Response({'detail': f'Maksimal deposit adalah {max_deposit_amount}'}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        order_num = f"DEP-{_now_wib().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

        trx = Transaction.objects.create(
            user=user,
            product=None,
            type='DEPOSIT',
            amount=amount,
            currency_code='IDR',
            description=f'Deposit via Jayapay ({wallet_type})',
            status='PENDING',
            wallet_type=wallet_type,
            trx_id=order_num,
        )

        pay_money = str(int(round(float(amount))))
        now = _now_wib()
        notify_url = f"https://{app_domain}/api/deposits/jayapay/callback/"

        params = {
            'merchantCode': merchant_code,
            'orderType': '0',
            'method': method,
            'orderNum': order_num,
            'payMoney': pay_money,
            'name': user.full_name or user.username,
            'email': getattr(user, 'email', '') or '',
            'phone': getattr(user, 'phone', '') or '',
            'notifyUrl': notify_url,
            'dateTime': format_datetime(now),
            'expiryPeriod': '1000',
            'productDetail': 'Top Up Saldo',
        }

        try:
            sign = sign_params_legacy(params, private_key)
        except Exception as e:
            trx.status = 'FAILED'
            trx.save(update_fields=['status'])
            return Response({'detail': f'Gagal membuat signature: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
        params['sign'] = sign

        dep = Deposit.objects.create(
            user=user,
            gateway='JAYAPAY',
            order_num=order_num,
            amount=amount,
            amount_currency_code='IDR',
            wallet_type=wallet_type,
            status='PENDING',
            transaction=trx,
            request_params=params,
        )

        try:
            jayapay_url = (gs.jayapay_api_url or '').strip() if gs else ''
            api_url = jayapay_url or 'https://openapi.jayapayment.com/gateway/prepaidOrder'
            resp = requests.post(api_url, json=params, timeout=30)
            data = resp.json()
        except Exception as e:
            trx.status = 'FAILED'
            trx.save(update_fields=['status'])
            dep.response_payload = {'error': str(e)}
            dep.status = 'FAILED'
            dep.save(update_fields=['response_payload', 'status'])
            return Response({'detail': f'Gagal menghubungi gateway: {str(e)}'}, status=status.HTTP_502_BAD_GATEWAY)

        if data.get('platRespCode') == 'SUCCESS':
            payment_url = _strip_backticks(data.get('url'))
            if payment_url:
                plat_order_num = _extract_jayapay_plat_order_num_from_payment_url(payment_url)
                order_detail = _fetch_jayapay_cash_order_detail(payment_url, plat_order_num, merchant_order_num=order_num, method=method)
                dep.payment_url = payment_url
                dep.response_payload = {"gateway": data, "plat_order_num": plat_order_num, "order_detail": order_detail, "method": method}
                dep.save(update_fields=['payment_url', 'response_payload'])
                va_number, qris_payload = "", ""
                if isinstance(order_detail, dict):
                    od = order_detail.get("data") if isinstance(order_detail.get("data"), dict) else {}
                    va_raw = str(od.get("vaNumber") or "").strip()
                    if va_raw.startswith("000201"):
                        qris_payload = va_raw
                    else:
                        va_number = va_raw
                return Response({'order_num': order_num, 'payment_url': payment_url, 'plat_order_num': plat_order_num, 'order_detail': order_detail, 'va_number': va_number or None, 'qris_payload': qris_payload or None}, status=status.HTTP_200_OK)
            trx.status = 'FAILED'
            trx.save(update_fields=['status'])
            dep.response_payload = {"gateway": data}
            dep.status = 'FAILED'
            dep.save(update_fields=['response_payload', 'status'])
            return Response({'detail': 'Gateway tidak mengembalikan URL pembayaran'}, status=status.HTTP_502_BAD_GATEWAY)

        trx.status = 'FAILED'
        trx.save(update_fields=['status'])
        dep.response_payload = {"gateway": data}
        dep.status = 'FAILED'
        dep.save(update_fields=['response_payload', 'status'])
        return Response({'detail': data.get('platRespMessage') or 'Pembayaran gagal'}, status=status.HTTP_400_BAD_REQUEST)


class JayapayDepositOrderDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "deposit_initiate"

    @extend_schema(
        summary="Ambil detail pembayaran Jayapay berdasarkan order_num deposit",
        parameters=[
            OpenApiParameter(name="order_num", type=OpenApiTypes.STR, required=True, location=OpenApiParameter.QUERY),
        ],
        responses={
            200: {
                "type": "object",
                "properties": {
                    "order_num": {"type": "string"},
                    "payment_url": {"type": "string"},
                    "plat_order_num": {"type": "string"},
                    "order_detail": {"type": "object"},
                },
            },
            400: {"description": "Permintaan tidak valid"},
            404: {"description": "Deposit tidak ditemukan"},
        },
    )
    def get(self, request):
        order_num = (request.query_params.get("order_num") or "").strip()
        if not order_num:
            return Response({"detail": "order_num wajib diisi"}, status=status.HTTP_400_BAD_REQUEST)

        dep = Deposit.objects.filter(user=request.user, order_num=order_num, gateway="JAYAPAY").first()
        if not dep:
            return Response({"detail": "Deposit tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)

        payment_url = (dep.payment_url or "").strip()
        plat_order_num = _extract_jayapay_plat_order_num_from_payment_url(payment_url)
        method = ""
        if isinstance(dep.response_payload, dict):
            method = str(dep.response_payload.get("method") or "").strip().upper()
        order_detail = _fetch_jayapay_cash_order_detail(payment_url, plat_order_num, merchant_order_num=dep.order_num, method=method)

        dep.response_payload = (dep.response_payload or {}) if isinstance(dep.response_payload, dict) else {}
        dep.response_payload["plat_order_num"] = plat_order_num
        dep.response_payload["order_detail"] = order_detail
        dep.save(update_fields=["response_payload"])

        va_number, qris_payload = "", ""
        if isinstance(order_detail, dict):
            od = order_detail.get("data") if isinstance(order_detail.get("data"), dict) else {}
            va_raw = str(od.get("vaNumber") or "").strip()
            if va_raw.startswith("000201"):
                qris_payload = va_raw
            else:
                va_number = va_raw

        return Response(
            {"order_num": dep.order_num, "payment_url": payment_url, "plat_order_num": plat_order_num, "order_detail": order_detail, "va_number": va_number or None, "qris_payload": qris_payload or None},
            status=status.HTTP_200_OK,
        )


class JayapayDepositCallbackView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'gateway_callback'

    def post(self, request):
        gs = GatewaySettings.objects.order_by('-updated_at').first()
        callback = request.data
        code = callback.get('code')
        msg = callback.get('msg')
        order_num = callback.get('orderNum')

        # Jayapay selalu expect 'SUCCESS' di response
        if not order_num:
            return Response('SUCCESS')

        try:
            trx = Transaction.objects.get(trx_id=order_num)
        except Transaction.DoesNotExist:
            # Unknown order, acknowledge to avoid retry storms
            return Response('SUCCESS')

        # Update Deposit callback payload
        try:
            dep = Deposit.objects.get(order_num=order_num)
            dep.callback_payload = callback
            dep.callback_at = timezone.now()
            dep.save(update_fields=['callback_payload', 'callback_at'])
        except Deposit.DoesNotExist:
            pass

        # Jika sudah selesai, abaikan
        if trx.status == 'COMPLETED':
            return Response('SUCCESS')

        if code == '00' and msg == 'SUCCESS':
            # Verify callback signature using Public Key
            is_valid = False
            try:
                public_key = (gs.jayapay_public_key or '').strip() if gs else ''
                
                if public_key:
                    is_valid = verify_jayapay_signature(callback, public_key)
                else:
                    # If public key missing, we cannot verify. Fail safe.
                    # Or check if private key exists (maybe user put it there?)
                    # But per docs, we need PLATFORM PUBLIC KEY.
                    is_valid = False
            except Exception:
                is_valid = False
            
            if not is_valid:
                # Log spoof attempt or configuration error
                if trx.status in ('PENDING', 'PROCESSING'):
                    trx.status = 'FAILED'
                    trx.description += " [Invalid Callback Signature]"
                    trx.save(update_fields=['status', 'description'])
                    try:
                        dep = Deposit.objects.get(order_num=order_num)
                        dep.status = 'FAILED'
                        dep.save(update_fields=['status'])
                    except Deposit.DoesNotExist:
                        pass
                return Response('SUCCESS')

            user = trx.user
            wallet_field = 'balance' if trx.wallet_type == 'BALANCE' else 'balance_deposit'
            credited_amount = trx.amount
            currency_code = (trx.currency_code or "IDR").strip().upper() or "IDR"
            with db_transaction.atomic():
                current_balance = getattr(user, wallet_field)
                setattr(user, wallet_field, current_balance + credited_amount)
                user.save(update_fields=[wallet_field])
                trx.status = 'COMPLETED'
                trx.currency_code = currency_code
                trx.save(update_fields=['status', 'currency_code'])
                try:
                    from roulette.services import grant_tickets_for_self_deposit
                    grant_tickets_for_self_deposit(user, trx, deposit_amount=credited_amount)
                except Exception:
                    pass
                try:
                    _grant_deposit_cashback(user, trx, credited_amount=credited_amount, currency_code=trx.currency_code or currency_code)
                except Exception:
                    pass
                # Mark deposit completed
                try:
                    dep = Deposit.objects.get(order_num=order_num)
                    dep.status = 'COMPLETED'
                    dep.credited_amount = credited_amount
                    dep.credited_currency_code = trx.currency_code or currency_code
                    if not dep.amount_currency_code:
                        dep.amount_currency_code = "IDR"
                    dep.save(update_fields=['status', 'credited_amount', 'credited_currency_code', 'amount_currency_code'])
                except Deposit.DoesNotExist:
                    pass
            return Response('SUCCESS')
        else:
            # Mark as failed only if previously pending/processing
            if trx.status in ('PENDING', 'PROCESSING'):
                trx.status = 'FAILED'
                trx.save(update_fields=['status'])
                try:
                    dep = Deposit.objects.get(order_num=order_num)
                    dep.status = 'FAILED'
                    dep.save(update_fields=['status'])
                except Deposit.DoesNotExist:
                    pass
            return Response('SUCCESS')


class JayapayPhDepositInitiateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'deposit_initiate'

    @extend_schema(
        summary="Inisiasi deposit Philippines via Jayapay (Pay-In prePay)",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "example": 100},
                    "method": {"type": "string", "enum": ["GCASH", "GCASH_WAP", "MAYA", "MAYA_WAP"], "example": "GCASH"},
                    "wallet_type": {"type": "string", "enum": ["BALANCE", "BALANCE_DEPOSIT"], "example": "BALANCE"},
                },
                "required": ["amount"],
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "order_num": {"type": "string"},
                    "payment_url": {"type": "string"},
                },
            },
            400: {"description": "Permintaan tidak valid"},
            502: {"description": "Gagal menghubungi gateway"},
        },
    )
    def post(self, request):
        gs = GatewaySettings.objects.order_by('-updated_at').first()
        enabled = bool(gs and gs.jayapay_ph_enabled)
        api_url = (gs.jayapay_ph_api_url or '').strip() if gs else ''
        mch_no = (gs.jayapay_ph_mch_no or '').strip() if gs else ''
        private_key = (gs.jayapay_ph_private_key or '').strip() if gs else ''
        redirect_url = (gs.jayapay_ph_redirect_url or '').strip() if gs else ''
        default_method = (gs.jayapay_ph_default_method or '').strip() if gs else ''
        app_domain = (gs.app_domain or '').strip() if gs else ''

        if not enabled:
            return Response({'detail': 'Jayapay PH tidak aktif'}, status=status.HTTP_400_BAD_REQUEST)
        if not mch_no or not private_key:
            return Response({'detail': 'Konfigurasi Jayapay PH belum lengkap'}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({'detail': 'Konfigurasi domain untuk callback belum diisi'}, status=status.HTTP_400_BAD_REQUEST)

        api_url = api_url or "https://global-ph-openapi.jayapayment.com/ph/pay/prePay"

        wallet_type = (request.data.get('wallet_type') or gs.default_wallet_type or 'BALANCE')
        if wallet_type not in ('BALANCE', 'BALANCE_DEPOSIT'):
            return Response({'detail': 'wallet_type tidak valid'}, status=status.HTTP_400_BAD_REQUEST)

        amount_raw = request.data.get('amount')
        try:
            amount = Decimal(str(amount_raw)).quantize(Decimal("0.01"))
            if amount <= 0:
                raise InvalidOperation()
        except Exception:
            return Response({'detail': 'amount tidak valid'}, status=status.HTTP_400_BAD_REQUEST)

        method = (request.data.get("method") or default_method or "GCASH").strip().upper()
        method = method.replace("-", "_").replace(" ", "_")
        if not method:
            method = "GCASH"

        allowed_methods = {"GCASH", "GCASH_WAP", "MAYA", "MAYA_WAP", "PAY_MAYA", "PAY_MAYA_WAP"}
        if method not in allowed_methods:
            return Response(
                {'detail': f"method tidak valid (pilih: {', '.join(sorted({'GCASH','GCASH_WAP','MAYA','MAYA_WAP'}))})"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if method.startswith("PAY_MAYA"):
            method = method.replace("PAY_MAYA", "MAYA", 1)

        user = request.user
        order_num = f"DEP-PH-{_now_wib().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

        trx = Transaction.objects.create(
            user=user,
            product=None,
            type='DEPOSIT',
            amount=amount,
            currency_code='PHP',
            description=f'Deposit PH via Jayapay ({method}) ({wallet_type})',
            status='PENDING',
            wallet_type=wallet_type,
            trx_id=order_num,
        )

        timestamp_ms = str(int(pytime.time() * 1000))
        notify_url = f"https://{app_domain}/api/deposits/jayapay-ph/callback/"
        expiry_period = 1440
        amount_value = int(amount) if amount == amount.to_integral() else float(amount)

        payload = {
            "mchNo": mch_no,
            "orderNum": order_num,
            "amount": amount_value,
            "productDetail": "Top Up Saldo",
            "method": method,
            "timestamp": timestamp_ms,
            "customerName": user.full_name or user.username,
            "customerEmail": getattr(user, "email", "") or "",
            "customerPhone": getattr(user, "phone", "") or "",
            "expiryPeriod": expiry_period,
            "downNotifyUrl": notify_url,
            "redirectUrl": redirect_url or "",
        }

        try:
            payload["sign"] = sign_params_legacy(payload, private_key)
        except Exception as e:
            trx.status = 'FAILED'
            trx.save(update_fields=['status'])
            return Response({'detail': f'Gagal membuat signature: {str(e)}'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        dep = Deposit.objects.create(
            user=user,
            gateway='JAYAPAY_PH',
            order_num=order_num,
            amount=amount,
            amount_currency_code='PHP',
            wallet_type=wallet_type,
            status='PENDING',
            transaction=trx,
            request_params=payload,
        )

        try:
            resp = requests.post(api_url, json=payload, timeout=30)
            data = resp.json() if resp.content else {}
        except Exception as e:
            trx.status = 'FAILED'
            trx.save(update_fields=['status'])
            dep.response_payload = {'error': str(e)}
            dep.status = 'FAILED'
            dep.save(update_fields=['response_payload', 'status'])
            return Response({'detail': f'Gagal menghubungi gateway: {str(e)}'}, status=status.HTTP_502_BAD_GATEWAY)

        dep.response_payload = data
        dep.save(update_fields=['response_payload'])

        success = bool(data.get("success")) and str(data.get("code") or "").strip() == "9999"
        pay_url, _path = _extract_payment_url(data.get("data") if isinstance(data.get("data"), dict) else data)

        if success:
            if pay_url:
                dep.payment_url = pay_url
                dep.save(update_fields=['payment_url'])
            return Response({'order_num': order_num, 'payment_url': pay_url}, status=status.HTTP_200_OK)

        trx.status = 'FAILED'
        trx.save(update_fields=['status'])
        dep.status = 'FAILED'
        dep.save(update_fields=['status'])
        return Response({'detail': data.get('msg') or 'Pembayaran gagal', 'provider': data}, status=status.HTTP_400_BAD_REQUEST)


class JayapayPhDepositCallbackView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'gateway_callback'

    def post(self, request):
        gs = GatewaySettings.objects.order_by('-updated_at').first()
        callback = request.data if isinstance(request.data, dict) else {}
        logger.info(f"Jayapay PH Deposit callback received: {callback}")
        order_num = callback.get("orderNum") or callback.get("order_no") or callback.get("orderNum".lower())

        if not order_num:
            return HttpResponse('SUCCESS', content_type='text/plain')

        try:
            trx = Transaction.objects.get(trx_id=order_num)
        except Transaction.DoesNotExist:
            return HttpResponse('SUCCESS', content_type='text/plain')

        try:
            dep = Deposit.objects.get(order_num=order_num)
            dep.callback_payload = callback
            dep.callback_at = timezone.now()
            dep.save(update_fields=['callback_payload', 'callback_at'])
        except Deposit.DoesNotExist:
            dep = None

        if trx.status == 'COMPLETED':
            return HttpResponse('SUCCESS', content_type='text/plain')

        status_val = str(callback.get("status") or "").strip().upper()
        logger.info(f"Jayapay PH callback status_val: {status_val} for order {order_num}")
        if status_val != "SUCCESS":
            logger.warning(f"Jayapay PH callback: status is not SUCCESS ({status_val}) for order {order_num}")
            if trx.status in ('PENDING', 'PROCESSING'):
                trx.status = 'FAILED'
                trx.save(update_fields=['status'])
                if dep:
                    dep.status = 'FAILED'
                    dep.save(update_fields=['status'])
            return HttpResponse('SUCCESS', content_type='text/plain')

        is_valid = False
        try:
            public_key = (gs.jayapay_ph_public_key or '').strip() if gs else ''
            if public_key:
                is_valid = verify_jayapay_signature(callback, public_key, signature_field="sign")
                logger.info(f"Jayapay PH callback signature verification result: {is_valid} for order {order_num}")
            else:
                logger.warning(f"Jayapay PH callback: public key missing for order {order_num}")
        except Exception as e:
            logger.error(f"Jayapay PH callback: signature verification error: {e} for order {order_num}")
            is_valid = False

        if not is_valid:
            logger.warning(f"Jayapay PH callback: invalid signature for order {order_num}")
            if trx.status in ('PENDING', 'PROCESSING'):
                trx.status = 'FAILED'
                trx.description = (trx.description or '') + " [Invalid Callback Signature]"
                trx.save(update_fields=['status', 'description'])
                if dep:
                    dep.status = 'FAILED'
                    dep.save(update_fields=['status'])
            return HttpResponse('SUCCESS', content_type='text/plain')

        user = trx.user
        wallet_field = 'balance' if trx.wallet_type == 'BALANCE' else 'balance_deposit'
        original_amount = trx.amount
        credited_amount = trx.amount
        credited_currency_code = (trx.currency_code or "PHP").strip().upper() or "PHP"
        try:
            credited_amount, credited_currency_code, conversion_rate, _unused = _convert_amount_to_main_currency(trx.amount, credited_currency_code)
        except Exception:
            credited_amount = trx.amount
            credited_currency_code = (trx.currency_code or "PHP").strip().upper() or "PHP"
        with db_transaction.atomic():
            current_balance = getattr(user, wallet_field)
            setattr(user, wallet_field, current_balance + credited_amount)
            user.save(update_fields=[wallet_field])
            trx.status = 'COMPLETED'
            if credited_currency_code and credited_currency_code != (trx.currency_code or "PHP").strip().upper():
                trx.original_amount = original_amount
                trx.original_currency_code = (trx.currency_code or "PHP").strip().upper() or "PHP"
                trx.conversion_rate = conversion_rate if conversion_rate and conversion_rate > 0 else None
                trx.amount = credited_amount
                trx.currency_code = credited_currency_code
                main_code = credited_currency_code
                orig_code = trx.original_currency_code
                trx.description = (trx.description or '') + f" [Converted from {orig_code} to {main_code} at rate {conversion_rate}]"
                trx.save(update_fields=['status', 'amount', 'currency_code', 'original_amount', 'original_currency_code', 'conversion_rate', 'description'])
            else:
                trx.currency_code = credited_currency_code or (trx.currency_code or "PHP")
                trx.amount = credited_amount
                trx.save(update_fields=['status', 'currency_code', 'amount'])
            if dep:
                dep.status = 'COMPLETED'
                dep.credited_amount = credited_amount
                dep.credited_currency_code = trx.currency_code or credited_currency_code or "PHP"
                if not dep.amount_currency_code:
                    dep.amount_currency_code = getattr(trx, "original_currency_code", None) or (trx.currency_code or "PHP")
                dep.save(update_fields=['status', 'credited_amount', 'credited_currency_code', 'amount_currency_code'])
        try:
            _grant_deposit_cashback(user, trx, credited_amount=credited_amount, currency_code=trx.currency_code or credited_currency_code)
        except Exception:
            pass

        return HttpResponse('SUCCESS', content_type='text/plain')


class KlikpayDepositInitiateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'deposit_initiate'

    @extend_schema(
        summary="Inisiasi deposit via Klikpay",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "example": 50000},
                    "wallet_type": {"type": "string", "enum": ["BALANCE", "BALANCE_DEPOSIT"], "example": "BALANCE"},
                },
                "required": ["amount"],
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "order_num": {"type": "string", "example": "DEP-20250101XXXX-XYZ789"},
                    "payment_url": {"type": "string", "example": "https://klikpay.example/pay?id=..."},
                },
            },
            400: {"description": "Permintaan tidak valid"},
            502: {"description": "Gagal menghubungi gateway"},
        },
    )
    def post(self, request):
        gs = GatewaySettings.objects.order_by('-updated_at').first()
        klikpay_enabled = bool(gs and gs.klikpay_enabled)
        api_url = (gs.klikpay_api_url or '').strip() if gs else ''
        merchant_code = (gs.klikpay_merchant_code or '').strip() if gs else ''
        private_key = (gs.klikpay_private_key or '').strip() if gs else ''
        redirect_url = (gs.klikpay_redirect_url or '').strip() if gs else ''
        app_domain = (gs.app_domain or '').strip() if gs else ''
        min_deposit_amount = (gs.min_deposit_amount or Decimal('0')) if gs else Decimal('0')
        max_deposit_amount = (gs.max_deposit_amount or Decimal('0')) if gs else Decimal('0')

        if not klikpay_enabled:
            return Response({'detail': 'Klikpay tidak aktif'}, status=status.HTTP_400_BAD_REQUEST)
        if not api_url or not merchant_code or not private_key:
            return Response({'detail': 'Konfigurasi Klikpay belum lengkap'}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({'detail': 'Konfigurasi domain untuk callback belum diisi'}, status=status.HTTP_400_BAD_REQUEST)
        
        wallet_type = 'BALANCE_DEPOSIT'

        amount_raw = request.data.get('amount')
        try:
            amount = Decimal(str(amount_raw))
            if amount <= 0:
                raise InvalidOperation()
        except Exception:
            return Response({'detail': 'amount tidak valid'}, status=status.HTTP_400_BAD_REQUEST)
        
        if min_deposit_amount and min_deposit_amount > 0 and amount < min_deposit_amount:
            return Response({'detail': f'Minimal deposit adalah {min_deposit_amount}'}, status=status.HTTP_400_BAD_REQUEST)
        if max_deposit_amount and max_deposit_amount > 0 and amount > max_deposit_amount:
            return Response({'detail': f'Maksimal deposit adalah {max_deposit_amount}'}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        order_num = f"DEP-{_now_wib().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

        trx = Transaction.objects.create(
            user=user,
            product=None,
            type='DEPOSIT',
            amount=amount,
            currency_code='IDR',
            description=f'Deposit via Klikpay ({wallet_type})',
            status='PENDING',
            wallet_type=wallet_type,
            trx_id=order_num,
        )

        amount_int = str(int(round(float(amount))))
        notify_url = f"https://{app_domain}/api/deposits/klikpay/callback/"
        params = klikpay_build_params(
            order_num=order_num,
            amount_int=amount_int,
            user_name=user.full_name or user.username,
            user_email=getattr(user, 'email', '') or '',
            user_phone=getattr(user, 'phone', '') or '',
            notify_url=notify_url,
            redirect_url=redirect_url,
            expiry_period='1440',
            product_detail='Top Up Saldo',
        )
        params["merchantCode"] = merchant_code
        params["sign"] = klikpay_sign_params(params, private_key)

        dep = Deposit.objects.create(
            user=user,
            gateway='KLIKPAY',
            order_num=order_num,
            amount=amount,
            amount_currency_code='IDR',
            wallet_type=wallet_type,
            status='PENDING',
            transaction=trx,
            request_params=params,
        )
        try:
            api_url = api_url or 'https://idvs.klysnv.com/gateway/prepaidOrder'
            data = klikpay_send_prepaid(api_url, params)
        except Exception as e:
            trx.status = 'FAILED'
            trx.save(update_fields=['status'])
            dep.response_payload = {'error': str(e)}
            dep.status = 'FAILED'
            dep.save(update_fields=['response_payload', 'status'])
            return Response({'detail': f'Gagal menghubungi gateway: {str(e)}'}, status=status.HTTP_502_BAD_GATEWAY)

        # Placeholder success detection; adjust per Klikpay response format
        payment_url = data.get('payment_url') or data.get('url')
        resp_code = str(data.get('code') or data.get('status') or '').upper()
        is_success = resp_code in ('SUCCESS', '00', '200') or bool(payment_url)
        if is_success and payment_url:
            dep.payment_url = payment_url
            dep.response_payload = data
            dep.save(update_fields=['payment_url', 'response_payload'])
            return Response({'order_num': order_num, 'payment_url': payment_url}, status=status.HTTP_200_OK)
        else:
            trx.status = 'FAILED'
            trx.save(update_fields=['status'])
            dep.response_payload = data
            dep.status = 'FAILED'
            dep.save(update_fields=['response_payload', 'status'])
            return Response({'detail': data.get('message') or 'Pembayaran gagal'}, status=status.HTTP_400_BAD_REQUEST)


class KlikpayDepositCallbackView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'gateway_callback'

    def post(self, request):
        gs = GatewaySettings.objects.first()
        callback = request.data
        order_num = callback.get('orderNum') or callback.get('order_id') or callback.get('orderId')
        status_val = str(callback.get('status') or '').upper()
        code = str(callback.get('code') or '').upper()
        msg = str(callback.get('msg') or '').upper()

        if not order_num:
            return Response('SUCCESS')

        try:
            trx = Transaction.objects.get(trx_id=order_num)
        except Transaction.DoesNotExist:
            return Response('SUCCESS')

        try:
            dep = Deposit.objects.get(order_num=order_num)
            dep.callback_payload = callback
            dep.callback_at = timezone.now()
            dep.save(update_fields=['callback_payload', 'callback_at'])
        except Deposit.DoesNotExist:
            pass

        if trx.status == 'COMPLETED':
            return Response('SUCCESS')

        success = status_val in ('SUCCESS', 'COMPLETED') or (code in ('00', '200') and msg in ('SUCCESS', 'OK'))
        if success:
            user = trx.user
            wallet_field = 'balance' if trx.wallet_type == 'BALANCE' else 'balance_deposit'
            credited_amount = trx.amount
            currency_code = (trx.currency_code or "IDR").strip().upper() or "IDR"
            with db_transaction.atomic():
                current_balance = getattr(user, wallet_field)
                setattr(user, wallet_field, current_balance + credited_amount)
                user.save(update_fields=[wallet_field])
                trx.status = 'COMPLETED'
                trx.currency_code = currency_code
                trx.save(update_fields=['status', 'currency_code'])
                try:
                    from roulette.services import grant_tickets_for_self_deposit
                    grant_tickets_for_self_deposit(user, trx, deposit_amount=credited_amount)
                except Exception:
                    pass
                try:
                    _grant_deposit_cashback(user, trx, credited_amount=credited_amount, currency_code=trx.currency_code or currency_code)
                except Exception:
                    pass
                try:
                    dep = Deposit.objects.get(order_num=order_num)
                    dep.status = 'COMPLETED'
                    dep.credited_amount = credited_amount
                    dep.credited_currency_code = trx.currency_code or currency_code
                    if not dep.amount_currency_code:
                        dep.amount_currency_code = "IDR"
                    dep.save(update_fields=['status', 'credited_amount', 'credited_currency_code', 'amount_currency_code'])
                except Deposit.DoesNotExist:
                    pass
            return Response('SUCCESS')
        else:
            if trx.status in ('PENDING', 'PROCESSING'):
                trx.status = 'FAILED'
                trx.save(update_fields=['status'])
                try:
                    dep = Deposit.objects.get(order_num=order_num)
                    dep.status = 'FAILED'
                    dep.save(update_fields=['status'])
                except Deposit.DoesNotExist:
                    pass
            return Response('SUCCESS')


class UsdGatewayDepositInitiateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'deposit_initiate'

    @extend_schema(
        summary="Inisiasi deposit USD via createOrder",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "amount": {"type": "string", "example": "10.00", "description": "Amount USD, 2 decimals"},
                    "busi_code": {"type": "string", "example": "122001", "description": "Fixed Payment Type Code (122001)"},
                    "wallet_type": {"type": "string", "enum": ["BALANCE", "BALANCE_DEPOSIT"], "example": "BALANCE"},
                },
                "required": ["amount"],
            }
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "order_num": {"type": "string"},
                    "payment_url": {"type": "string"},
                },
            },
            400: {"description": "Permintaan tidak valid"},
            502: {"description": "Gagal menghubungi gateway"},
        },
    )
    def post(self, request):
        gs = GatewaySettings.objects.order_by('-updated_at').first()
        enabled = bool(gs and gs.usd_gateway_enabled)
        api_url = _strip_backticks((gs.usd_gateway_api_url or "").strip()) if gs else ""
        mer_no = (gs.usd_gateway_mer_no or "").strip() if gs else ""
        sign_key = (gs.usd_gateway_sign_key or "").strip() if gs else ""
        redirect_url = _strip_backticks((gs.usd_gateway_redirect_url or "").strip()) if gs else ""
        app_domain = _strip_backticks((gs.app_domain or "").strip()) if gs else ""
        min_deposit_amount = (gs.usd_gateway_min_deposit_amount or Decimal('0')) if gs else Decimal('0')
        max_deposit_amount = (gs.usd_gateway_max_deposit_amount or Decimal('0')) if gs else Decimal('0')

        if not enabled:
            return Response({'detail': 'USD Gateway tidak aktif'}, status=status.HTTP_400_BAD_REQUEST)
        if not api_url or not mer_no or not sign_key:
            return Response({'detail': 'Konfigurasi USD Gateway belum lengkap'}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({'detail': 'Konfigurasi domain untuk callback belum diisi'}, status=status.HTTP_400_BAD_REQUEST)
        if not redirect_url:
            return Response({'detail': 'Redirect URL belum diisi'}, status=status.HTTP_400_BAD_REQUEST)

        wallet_type = (request.data.get('wallet_type') or gs.default_wallet_type or 'BALANCE')
        if wallet_type not in ('BALANCE', 'BALANCE_DEPOSIT'):
            return Response({'detail': 'wallet_type tidak valid'}, status=status.HTTP_400_BAD_REQUEST)

        amount_raw = request.data.get('amount')
        try:
            amount = Decimal(str(amount_raw)).quantize(Decimal("0.01"))
            if amount <= 0:
                raise InvalidOperation()
        except Exception:
            return Response({'detail': 'amount tidak valid'}, status=status.HTTP_400_BAD_REQUEST)

        if min_deposit_amount and min_deposit_amount > 0 and amount < min_deposit_amount:
            return Response({'detail': f'Minimal deposit USD adalah {min_deposit_amount}'}, status=status.HTTP_400_BAD_REQUEST)
        if max_deposit_amount and max_deposit_amount > 0 and amount > max_deposit_amount:
            return Response({'detail': f'Maksimal deposit USD adalah {max_deposit_amount}'}, status=status.HTTP_400_BAD_REQUEST)

        busi_code = "122001"

        user = request.user
        email = (getattr(user, "email", "") or "").strip() or f"user{user.id}@example.com"

        order_num = f"DEP-{_now_wib().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

        trx = Transaction.objects.create(
            user=user,
            product=None,
            type='DEPOSIT',
            amount=amount,
            currency_code='USD',
            description=f'Deposit USD Gateway ({wallet_type})',
            status='PENDING',
            wallet_type=wallet_type,
            trx_id=order_num,
        )

        notify_url = f"https://{app_domain}/api/deposits/usd/callback/"
        timestamp_ms = str(int(pytime.time() * 1000))

        name = (user.full_name or user.username or "USER").strip()
        name_letters = "".join([c for c in name if c.isalpha() or c.isspace()]).strip() or "USER"
        phone_digits = "".join([c for c in (getattr(user, "phone", "") or "") if c.isdigit()]) or "0000000000"
        bank_code_override = (request.data.get("bank_code") or request.data.get("bankCode") or "").strip()
        client_ip = _get_client_ip(request) or "127.0.0.1"
        bank_code = (bank_code_override or (gs.usd_gateway_bank_code if gs else "") or "").strip() or client_ip

        payload = {
            "bankCode": bank_code,
            "merNo": mer_no,
            "merOrderNo": order_num,
            "name": name_letters,
            "email": email,
            "phone": phone_digits,
            "orderAmount": f"{amount:.2f}",
            "currency": "USD",
            "busiCode": busi_code,
            "pageUrl": redirect_url,
            "notifyUrl": notify_url,
            "timestamp": timestamp_ms,
        }
        payload["sign"] = _usd_gateway_sign(payload, sign_key)

        dep = Deposit.objects.create(
            user=user,
            gateway='USD_GATEWAY',
            order_num=order_num,
            amount=amount,
            amount_currency_code='USD',
            wallet_type=wallet_type,
            status='PENDING',
            transaction=trx,
            request_params=payload,
        )

        try:
            logger.warning(
                "USD_GATEWAY createOrder request: order=%s merNo=***%s bankCode=%s amount=%s currency=USD busiCode=%s pageUrl=%s notifyUrl=%s timestamp=%s sign=%s",
                order_num,
                mer_no[-6:],
                bank_code,
                f"{amount:.2f}",
                busi_code,
                redirect_url,
                notify_url,
                timestamp_ms,
                str(payload.get("sign") or "")[:10],
            )
            resp = requests.post(api_url, json=payload, timeout=30)
            data = resp.json() if resp.content else {}
            logger.warning(
                "USD_GATEWAY FULL RESPONSE: %s",
                json.dumps(_redact_provider_payload_for_log(data), ensure_ascii=False),
            )
            msg = str(data.get("msg") or data.get("message") or "").strip()
            code_val = str(data.get("code") or "").strip()
            key_is_hex = len(sign_key) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in sign_key)
            if key_is_hex and (code_val == "901007" or "signature verification failed" in msg.lower()):
                payload["sign"] = _usd_gateway_sign(payload, sign_key, hex_key=True)
                dep.request_params = payload
                dep.save(update_fields=["request_params"])
                logger.warning(
                    "USD_GATEWAY createOrder retry(hex_key): order=%s sign=%s",
                    order_num,
                    str(payload.get("sign") or "")[:10],
                )
                resp = requests.post(api_url, json=payload, timeout=30)
                data = resp.json() if resp.content else {}
                logger.warning(
                    "USD_GATEWAY FULL RESPONSE (retry): %s",
                    json.dumps(_redact_provider_payload_for_log(data), ensure_ascii=False),
                )
                msg = str(data.get("msg") or data.get("message") or "").strip()
                code_val = str(data.get("code") or "").strip()
        except Exception as e:
            trx.status = 'FAILED'
            trx.save(update_fields=['status'])
            dep.response_payload = {'error': str(e)}
            dep.status = 'FAILED'
            dep.save(update_fields=['response_payload', 'status'])
            logger.exception("USD_GATEWAY createOrder request error: order=%s", order_num)
            return Response({'detail': f'Gagal menghubungi gateway: {str(e)}'}, status=status.HTTP_502_BAD_GATEWAY)

        dep.response_payload = data
        dep.save(update_fields=['response_payload'])

        code = str(data.get("code") or "").strip()
        success = code == "200" or code == 200 or data.get("status") is True
        pay_url, pay_url_path = _extract_payment_url(data.get("data") if isinstance(data.get("data"), dict) else data)

        if success:
            if pay_url:
                dep.payment_url = pay_url
                dep.save(update_fields=['payment_url'])
            logger.warning(
                "USD_GATEWAY createOrder response: order=%s code=%s msg=%s hasPayUrl=%s dataKeys=%s",
                order_num,
                code,
                str(data.get("msg") or data.get("message") or "").strip(),
                bool(pay_url),
                sorted(list(data.get("data", {}).keys())) if isinstance(data.get("data"), dict) else None,
            )
            return Response(
                {
                    'order_num': order_num,
                    'payment_url': pay_url,
                    'provider_code': code,
                    'provider_msg': data.get("msg") or data.get("message") or "",
                    'busi_code': busi_code,
                    'payment_url_path': pay_url_path,
                },
                status=status.HTTP_200_OK
            )

        trx.status = 'FAILED'
        trx.save(update_fields=['status'])
        dep.status = 'FAILED'
        dep.save(update_fields=['status'])
        logger.warning(
            "USD_GATEWAY createOrder failed: order=%s code=%s msg=%s",
            order_num,
            code,
            str(data.get("msg") or data.get("message") or "").strip(),
        )
        return Response(
            {
                'detail': data.get("msg") or data.get("message") or 'Pembayaran gagal',
                'provider_code': code,
                'provider_msg': data.get("msg") or data.get("message") or "",
                'busi_code': busi_code,
                'payment_url_path': pay_url_path,
            },
            status=status.HTTP_400_BAD_REQUEST
        )


class UsdGatewayDepositCallbackView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'gateway_callback'

    def post(self, request):
        gs = GatewaySettings.objects.order_by('-updated_at').first()
        sign_key = (gs.usd_gateway_sign_key or "").strip() if gs else ""
        payload = request.data if isinstance(request.data, dict) else {}

        order_num = payload.get("merOrderNo") or payload.get("mer_order_no") or payload.get("orderNum") or payload.get("order_no")
        if not order_num:
            return HttpResponse('SUCCESS', content_type='text/plain')

        mer_no = str(payload.get("merNo") or payload.get("mer_no") or "").strip()
        configured_mer_no = (gs.usd_gateway_mer_no or "").strip() if gs else ""
        if configured_mer_no and mer_no and mer_no != configured_mer_no:
            return HttpResponse('SUCCESS', content_type='text/plain')

        signature_valid = True
        provided_sign = str(payload.get("sign") or "").strip()
        if sign_key and provided_sign:
            expected = _usd_gateway_sign(payload, sign_key)
            if expected.lower() != provided_sign.lower():
                key_is_hex = len(sign_key) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in sign_key)
                if key_is_hex:
                    expected_hex = _usd_gateway_sign(payload, sign_key, hex_key=True)
                    if expected_hex.lower() != provided_sign.lower():
                        signature_valid = False
                else:
                    signature_valid = False

        try:
            trx = Transaction.objects.get(trx_id=order_num)
        except Transaction.DoesNotExist:
            return HttpResponse('SUCCESS', content_type='text/plain')

        try:
            dep = Deposit.objects.get(order_num=order_num)
            callback_payload = dict(payload)
            callback_payload["_signature_valid"] = signature_valid
            dep.callback_payload = callback_payload
            dep.callback_at = timezone.now()
            dep.save(update_fields=['callback_payload', 'callback_at'])
        except Deposit.DoesNotExist:
            dep = None

        if trx.status == 'COMPLETED':
            return HttpResponse('SUCCESS', content_type='text/plain')

        if not signature_valid:
            logger.warning(
                "USD_GATEWAY callback invalid signature: order=%s merNo=***%s payload=%s",
                order_num,
                mer_no[-6:] if mer_no else "",
                json.dumps(_redact_provider_payload_for_log(payload), ensure_ascii=False),
            )
            return HttpResponse('SUCCESS', content_type='text/plain')

        try:
            status_int = int(payload.get("status"))
        except Exception:
            status_int = None

        order_amount_raw = (
            payload.get("payAmount")
            or payload.get("pay_amount")
            or payload.get("orderAmount")
            or payload.get("order_amount")
            or payload.get("amount")
        )
        amount_ok = True
        if order_amount_raw is not None and str(order_amount_raw).strip() != "":
            try:
                paid_amount = Decimal(str(order_amount_raw)).quantize(Decimal("0.01"))
                amount_ok = paid_amount == trx.amount
            except Exception:
                amount_ok = False

        is_success = status_int in {5, 7}
        is_failed = status_int in {2, 4, 8}

        if is_success and amount_ok:
            user = trx.user
            wallet_field = 'balance' if trx.wallet_type == 'BALANCE' else 'balance_deposit'
            original_amount = trx.amount
            original_currency_code = (trx.currency_code or "USD").strip().upper() or "USD"
            credited_amount = trx.amount
            credited_currency_code = original_currency_code
            try:
                credited_amount, credited_currency_code, conversion_rate, _unused = _convert_amount_to_main_currency(trx.amount, original_currency_code)
            except Exception:
                credited_amount = trx.amount
                credited_currency_code = original_currency_code
            with db_transaction.atomic():
                current_balance = getattr(user, wallet_field)
                setattr(user, wallet_field, current_balance + credited_amount)
                user.save(update_fields=[wallet_field])
                trx.status = 'COMPLETED'
                if credited_currency_code and credited_currency_code != original_currency_code:
                    trx.original_amount = original_amount
                    trx.original_currency_code = original_currency_code
                    trx.conversion_rate = conversion_rate if conversion_rate and conversion_rate > 0 else None
                    trx.amount = credited_amount
                    trx.currency_code = credited_currency_code
                    trx.description = (trx.description or '') + f" [Converted from {original_currency_code} to {credited_currency_code} at rate {conversion_rate}]"
                    trx.save(update_fields=['status', 'amount', 'currency_code', 'original_amount', 'original_currency_code', 'conversion_rate', 'description'])
                else:
                    trx.currency_code = original_currency_code or "USD"
                    trx.amount = credited_amount
                    trx.save(update_fields=['status', 'currency_code', 'amount'])
                if dep:
                    dep.status = 'COMPLETED'
                    dep.credited_amount = credited_amount
                    dep.credited_currency_code = trx.currency_code or credited_currency_code or "USD"
                    if not dep.amount_currency_code:
                        dep.amount_currency_code = original_currency_code or "USD"
                    dep.save(update_fields=['status', 'credited_amount', 'credited_currency_code', 'amount_currency_code'])
            try:
                _grant_deposit_cashback(user, trx, credited_amount=credited_amount, currency_code=trx.currency_code or credited_currency_code)
            except Exception:
                pass
            logger.warning(
                "USD_GATEWAY callback success: order=%s status=%s amount_ok=%s",
                order_num,
                status_int,
                amount_ok,
            )
            return HttpResponse('SUCCESS', content_type='text/plain')

        if is_success and not amount_ok and trx.status in ('PENDING', 'PROCESSING'):
            trx.status = 'FAILED'
            trx.description = (trx.description or '') + " [Amount mismatch]"
            trx.save(update_fields=['status', 'description'])
            if dep:
                dep.status = 'FAILED'
                dep.save(update_fields=['status'])
            logger.warning(
                "USD_GATEWAY callback amount mismatch: order=%s status=%s",
                order_num,
                status_int,
            )
            return HttpResponse('SUCCESS', content_type='text/plain')

        if is_failed and trx.status in ('PENDING', 'PROCESSING'):
            trx.status = 'FAILED'
            trx.save(update_fields=['status'])
            if dep:
                dep.status = 'FAILED'
                dep.save(update_fields=['status'])
        logger.warning(
            "USD_GATEWAY callback ignored/fail: order=%s status=%s amount_ok=%s",
            order_num,
            status_int,
            amount_ok,
        )
        return HttpResponse('SUCCESS', content_type='text/plain')


def _ppaypros_collect_payload(request):
    payload = {}
    sources = [request.query_params, request.data]
    for source in sources:
        if not source:
            continue
        if hasattr(source, "lists"):
            iterator = source.lists()
            for key, values in iterator:
                if values:
                    payload[key] = values[-1]
        elif isinstance(source, dict):
            for key, value in source.items():
                payload[key] = value
    return payload


def _ppaypros_mark_deposit_failed(trx: Transaction, dep: Deposit | None, reason: str = ""):
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


def _ppaypros_complete_deposit(trx: Transaction, dep: Deposit | None, paid_amount: Decimal | None = None):
    if trx.status == "COMPLETED":
        return

    expected_amount = Decimal(str(trx.amount or 0)).quantize(Decimal("0.01"))
    if paid_amount is not None and paid_amount > 0 and paid_amount != expected_amount:
        _ppaypros_mark_deposit_failed(trx, dep, reason="Amount mismatch")
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
            dep.save(update_fields=["status", "credited_amount", "credited_currency_code", "amount_currency_code"])

    try:
        _grant_deposit_cashback(trx.user, trx, credited_amount=credited_amount, currency_code=currency_code)
    except Exception:
        pass


def _ppaypros_apply_payin_state(trx: Transaction, dep: Deposit | None, state_value, amount_points=None):
    try:
        state_int = int(state_value)
    except Exception:
        state_int = None

    paid_amount = None
    if amount_points not in (None, ""):
        try:
            paid_amount = ppaypros_points_to_amount(amount_points)
        except Exception:
            paid_amount = None

    if state_int == 2:
        _ppaypros_complete_deposit(trx, dep, paid_amount=paid_amount)
    elif state_int in (3, 4, 6):
        _ppaypros_mark_deposit_failed(trx, dep)
    elif state_int in (0, 1, 7):
        if trx.status == "PENDING":
            trx.status = "PROCESSING"
            trx.save(update_fields=["status"])
        if dep and dep.status == "PENDING":
            dep.status = "PROCESSING"
            dep.save(update_fields=["status"])


class PPayProsDepositInitiateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "deposit_initiate"

    @extend_schema(
        summary="Inisiasi deposit via PPay Pros",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "example": 100000},
                    "wallet_type": {"type": "string", "enum": ["BALANCE", "BALANCE_DEPOSIT"], "example": "BALANCE"},
                    "wayCode": {"type": "string", "example": "809"},
                    "extParam": {"type": "string", "example": "DANA"},
                },
                "required": ["amount"],
            }
        },
    )
    def post(self, request):
        gs = GatewaySettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.ppaypros_enabled)
        api_url = (gs.ppaypros_api_url or "").strip() if gs else ""
        mch_no = (gs.ppaypros_mch_no or "").strip() if gs else ""
        app_id = (gs.ppaypros_app_id or "").strip() if gs else ""
        private_key = (gs.ppaypros_private_key or "").strip() if gs else ""
        app_domain = (gs.app_domain or "").strip() if gs else ""
        default_way_code = (gs.ppaypros_way_code or "").strip() if gs else ""
        default_ext_param = (gs.ppaypros_ext_param or "").strip() if gs else ""
        return_url = (gs.ppaypros_return_url or "").strip() if gs else ""
        min_deposit_amount = (gs.min_deposit_amount or Decimal("0")) if gs else Decimal("0")
        max_deposit_amount = (gs.max_deposit_amount or Decimal("0")) if gs else Decimal("0")

        if not enabled:
            return Response({"detail": "PPay Pros tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not api_url or not mch_no or not app_id or not private_key:
            return Response({"detail": "Konfigurasi PPay Pros belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({"detail": "Konfigurasi domain untuk callback belum diisi"}, status=status.HTTP_400_BAD_REQUEST)

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

        if min_deposit_amount and min_deposit_amount > 0 and amount < min_deposit_amount:
            return Response({"detail": f"Minimal deposit adalah {min_deposit_amount}"}, status=status.HTTP_400_BAD_REQUEST)
        if max_deposit_amount and max_deposit_amount > 0 and amount > max_deposit_amount:
            return Response({"detail": f"Maksimal deposit adalah {max_deposit_amount}"}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        order_num = f"DPP{_now_wib().strftime('%y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
        way_code = (request.data.get("wayCode") or default_way_code or "").strip()
        ext_param = (request.data.get("extParam") or default_ext_param or "").strip()
        notify_url = f"https://{app_domain}/api/deposits/ppaypros/callback/"

        trx = Transaction.objects.create(
            user=user,
            product=None,
            type="DEPOSIT",
            amount=amount,
            currency_code="IDR",
            description=f"Deposit via PPay Pros ({wallet_type})",
            status="PENDING",
            wallet_type=wallet_type,
            trx_id=order_num,
        )

        payload = {
            "mchNo": mch_no,
            "appId": app_id,
            "mchOrderNo": order_num,
            "amount": ppaypros_amount_to_points(amount),
            "customerName": (user.full_name or user.username or f"User {user.pk}")[:64],
            "customerEmail": (getattr(user, "email", "") or f"user{user.pk}@example.com")[:64],
            "customerPhone": (getattr(user, "phone", "") or "")[:64],
            "notifyUrl": notify_url,
        }
        if way_code:
            payload["wayCode"] = way_code
        if ext_param:
            payload["extParam"] = ext_param
        if return_url:
            payload["returnUrl"] = return_url
        payload["sign"] = ppaypros_generate_sign(payload, private_key)

        logger.warning(
            "PPAYPROS payin request: order=%s mchNo=***%s appId=***%s amount_points=%s wayCode=%s extParam=%s notifyUrl=%s payload=%s",
            order_num,
            mch_no[-6:] if mch_no else "",
            app_id[-6:] if app_id else "",
            payload.get("amount"),
            payload.get("wayCode") or "",
            payload.get("extParam") or "",
            notify_url,
            json.dumps(_redact_provider_payload_for_log(payload), ensure_ascii=False),
        )

        dep = Deposit.objects.create(
            user=user,
            gateway="PPAYPROS",
            order_num=order_num,
            amount=amount,
            amount_currency_code="IDR",
            wallet_type=wallet_type,
            status="PENDING",
            transaction=trx,
            request_params=payload,
        )

        response_payload = ppaypros_post_json(f"{api_url.rstrip('/')}/api/pay/pay", payload)
        sign_valid = None
        if response_payload.get("sign"):
            sign_valid = ppaypros_verify_sign(response_payload, private_key)
            response_payload["_sign_valid"] = sign_valid

        logger.warning(
            "PPAYPROS payin response: order=%s code=%s msg=%s body=%s",
            order_num,
            response_payload.get("code"),
            response_payload.get("msg"),
            json.dumps(_redact_provider_payload_for_log(response_payload), ensure_ascii=False),
        )

        dep.response_payload = response_payload
        dep.save(update_fields=["response_payload"])

        if str(response_payload.get("code")) == "0":
            data = ppaypros_parse_data_field(response_payload)
            pay_data_type, pay_data, pay_order_id = ppaypros_extract_payment_data(data)
            payment_url, _path = _extract_payment_url({"payData": pay_data, **data})
            if payment_url:
                dep.payment_url = payment_url
                dep.save(update_fields=["payment_url"])
            return Response(
                {
                    "order_num": order_num,
                    "payment_url": payment_url or None,
                    "pay_order_id": pay_order_id or None,
                    "pay_data_type": pay_data_type or None,
                    "pay_data": pay_data or None,
                    "provider": response_payload,
                },
                status=status.HTTP_200_OK,
            )

        _ppaypros_mark_deposit_failed(trx, dep)
        logger.warning(
            "PPAYPROS payin rejected locally: order=%s detail=%s provider=%s",
            order_num,
            response_payload.get("msg") or "PPay Pros payin gagal",
            json.dumps(_redact_provider_payload_for_log(response_payload), ensure_ascii=False),
        )
        return Response(
            {"detail": response_payload.get("msg") or "PPay Pros payin gagal", "provider": response_payload},
            status=status.HTTP_400_BAD_REQUEST,
        )


class PPayProsDepositInitiateQRView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "deposit_initiate"

    @extend_schema(
        summary="Inisiasi deposit via PPay Pros + QR image",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "example": 100000},
                    "wallet_type": {"type": "string", "enum": ["BALANCE", "BALANCE_DEPOSIT"], "example": "BALANCE"},
                    "wayCode": {"type": "string", "example": "809"},
                    "extParam": {"type": "string", "example": "DANA"},
                },
                "required": ["amount"],
            }
        },
    )
    def post(self, request):
        gs = GatewaySettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.ppaypros_enabled)
        api_url = (gs.ppaypros_api_url or "").strip() if gs else ""
        mch_no = (gs.ppaypros_mch_no or "").strip() if gs else ""
        app_id = (gs.ppaypros_app_id or "").strip() if gs else ""
        private_key = (gs.ppaypros_private_key or "").strip() if gs else ""
        app_domain = (gs.app_domain or "").strip() if gs else ""
        default_way_code = (gs.ppaypros_way_code or "").strip() if gs else ""
        default_ext_param = (gs.ppaypros_ext_param or "").strip() if gs else ""
        return_url = (gs.ppaypros_return_url or "").strip() if gs else ""
        min_deposit_amount = (gs.min_deposit_amount or Decimal("0")) if gs else Decimal("0")
        max_deposit_amount = (gs.max_deposit_amount or Decimal("0")) if gs else Decimal("0")

        if not enabled:
            return Response({"detail": "PPay Pros tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not api_url or not mch_no or not app_id or not private_key:
            return Response({"detail": "Konfigurasi PPay Pros belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({"detail": "Konfigurasi domain untuk callback belum diisi"}, status=status.HTTP_400_BAD_REQUEST)

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

        if min_deposit_amount and min_deposit_amount > 0 and amount < min_deposit_amount:
            return Response({"detail": f"Minimal deposit adalah {min_deposit_amount}"}, status=status.HTTP_400_BAD_REQUEST)
        if max_deposit_amount and max_deposit_amount > 0 and amount > max_deposit_amount:
            return Response({"detail": f"Maksimal deposit adalah {max_deposit_amount}"}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        order_num = f"DPP{_now_wib().strftime('%y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
        way_code = (request.data.get("wayCode") or default_way_code or "").strip()
        ext_param = (request.data.get("extParam") or default_ext_param or "").strip()
        notify_url = f"https://{app_domain}/api/deposits/ppaypros/callback/"

        trx = Transaction.objects.create(
            user=user,
            product=None,
            type="DEPOSIT",
            amount=amount,
            currency_code="IDR",
            description=f"Deposit via PPay Pros ({wallet_type})",
            status="PENDING",
            wallet_type=wallet_type,
            trx_id=order_num,
        )

        payload = {
            "mchNo": mch_no,
            "appId": app_id,
            "mchOrderNo": order_num,
            "amount": ppaypros_amount_to_points(amount),
            "customerName": (user.full_name or user.username or f"User {user.pk}")[:64],
            "customerEmail": (getattr(user, "email", "") or f"user{user.pk}@example.com")[:64],
            "customerPhone": (getattr(user, "phone", "") or "")[:64],
            "notifyUrl": notify_url,
        }
        if way_code:
            payload["wayCode"] = way_code
        if ext_param:
            payload["extParam"] = ext_param
        if return_url:
            payload["returnUrl"] = return_url
        payload["sign"] = ppaypros_generate_sign(payload, private_key)

        logger.warning(
            "PPAYPROS-QR payin request: order=%s mchNo=***%s appId=***%s amount_points=%s wayCode=%s extParam=%s notifyUrl=%s payload=%s",
            order_num,
            mch_no[-6:] if mch_no else "",
            app_id[-6:] if app_id else "",
            payload.get("amount"),
            payload.get("wayCode") or "",
            payload.get("extParam") or "",
            notify_url,
            json.dumps(_redact_provider_payload_for_log(payload), ensure_ascii=False),
        )

        dep = Deposit.objects.create(
            user=user,
            gateway="PPAYPROS",
            order_num=order_num,
            amount=amount,
            amount_currency_code="IDR",
            wallet_type=wallet_type,
            status="PENDING",
            transaction=trx,
            request_params=payload,
        )

        response_payload = ppaypros_post_json(f"{api_url.rstrip('/')}/api/pay/pay", payload)
        sign_valid = None
        if response_payload.get("sign"):
            sign_valid = ppaypros_verify_sign(response_payload, private_key)
            response_payload["_sign_valid"] = sign_valid

        logger.warning(
            "PPAYPROS-QR payin response: order=%s code=%s msg=%s body=%s",
            order_num,
            response_payload.get("code"),
            response_payload.get("msg"),
            json.dumps(_redact_provider_payload_for_log(response_payload), ensure_ascii=False),
        )

        dep.response_payload = response_payload
        dep.save(update_fields=["response_payload"])

        if str(response_payload.get("code")) == "0":
            data = ppaypros_parse_data_field(response_payload)
            pay_data_type, pay_data, pay_order_id = ppaypros_extract_payment_data(data)
            payment_url, _path = _extract_payment_url({"payData": pay_data, **data})
            if payment_url:
                dep.payment_url = payment_url
                dep.save(update_fields=["payment_url"])

            qr_image = _scrape_qr_image_from_url(payment_url) if payment_url else None

            return Response(
                {
                    "order_num": order_num,
                    "amount": str(amount),
                    "payment_url": payment_url or None,
                    "pay_order_id": pay_order_id or None,
                    "pay_data_type": pay_data_type or None,
                    "pay_data": pay_data or None,
                    "qr_image": qr_image or "",
                    "provider": response_payload,
                },
                status=status.HTTP_200_OK,
            )

        _ppaypros_mark_deposit_failed(trx, dep)
        logger.warning(
            "PPAYPROS-QR payin rejected locally: order=%s detail=%s provider=%s",
            order_num,
            response_payload.get("msg") or "PPay Pros payin gagal",
            json.dumps(_redact_provider_payload_for_log(response_payload), ensure_ascii=False),
        )
        return Response(
            {"detail": response_payload.get("msg") or "PPay Pros payin gagal", "provider": response_payload},
            status=status.HTTP_400_BAD_REQUEST,
        )


class PPayProsDepositCallbackView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "gateway_callback"

    def post(self, request):
        gs = GatewaySettings.objects.order_by("-updated_at").first()
        private_key = (gs.ppaypros_private_key or "").strip() if gs else ""
        payload = _ppaypros_collect_payload(request)
        order_num = str(payload.get("mchOrderNo") or "").strip()
        if not order_num:
            return HttpResponse("success", content_type="text/plain")

        trx = Transaction.objects.filter(trx_id=order_num).first()
        if not trx:
            return HttpResponse("success", content_type="text/plain")

        dep = Deposit.objects.filter(order_num=order_num, gateway="PPAYPROS").first()
        sign_valid = ppaypros_verify_sign(payload, private_key) if private_key else False
        if dep:
            callback_payload = dict(payload)
            callback_payload["_sign_valid"] = sign_valid
            dep.callback_payload = callback_payload
            dep.callback_at = timezone.now()
            dep.save(update_fields=["callback_payload", "callback_at"])

        if not sign_valid:
            return HttpResponse("success", content_type="text/plain")

        _ppaypros_apply_payin_state(
            trx,
            dep,
            payload.get("state") or payload.get("orderState"),
            amount_points=payload.get("amount"),
        )
        return HttpResponse("success", content_type="text/plain")


class PPayProsDepositQueryView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "deposit_initiate"

    @extend_schema(
        summary="Query status deposit PPay Pros",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "order_num": {"type": "string", "example": "DPP260716123456ABCD1234"},
                    "payOrderId": {"type": "string", "example": "P1234567890"},
                },
            }
        },
    )
    def post(self, request):
        gs = GatewaySettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.ppaypros_enabled)
        api_url = (gs.ppaypros_api_url or "").strip() if gs else ""
        mch_no = (gs.ppaypros_mch_no or "").strip() if gs else ""
        app_id = (gs.ppaypros_app_id or "").strip() if gs else ""
        private_key = (gs.ppaypros_private_key or "").strip() if gs else ""
        if not enabled:
            return Response({"detail": "PPay Pros tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not api_url or not mch_no or not app_id or not private_key:
            return Response({"detail": "Konfigurasi PPay Pros belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)

        order_num = (request.data.get("order_num") or request.data.get("mchOrderNo") or "").strip()
        pay_order_id = (request.data.get("payOrderId") or "").strip()
        if not order_num and not pay_order_id:
            return Response({"detail": "order_num atau payOrderId wajib diisi"}, status=status.HTTP_400_BAD_REQUEST)
        if not request.user.is_staff and not order_num:
            return Response({"detail": "User biasa wajib mengirim order_num"}, status=status.HTTP_400_BAD_REQUEST)

        dep = None
        if order_num:
            dep_qs = Deposit.objects.filter(order_num=order_num, gateway="PPAYPROS")
            if not request.user.is_staff:
                dep_qs = dep_qs.filter(user=request.user)
            dep = dep_qs.select_related("transaction").first()
            if not dep:
                return Response({"detail": "Deposit tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)

        payload = {"mchNo": mch_no, "appId": app_id}
        if pay_order_id:
            payload["payOrderId"] = pay_order_id
        if order_num:
            payload["mchOrderNo"] = order_num
        payload["sign"] = ppaypros_generate_sign(payload, private_key)

        response_payload = ppaypros_post_json(f"{api_url.rstrip('/')}/api/pay/query", payload)
        if response_payload.get("sign"):
            response_payload["_sign_valid"] = ppaypros_verify_sign(response_payload, private_key)
        data = ppaypros_parse_data_field(response_payload)

        if not dep:
            remote_order_num = str(data.get("mchOrderNo") or "").strip()
            dep_qs = Deposit.objects.filter(order_num=remote_order_num, gateway="PPAYPROS")
            if not request.user.is_staff:
                dep_qs = dep_qs.filter(user=request.user)
            dep = dep_qs.select_related("transaction").first()
            if not dep:
                return Response({"detail": "Deposit tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)

        dep.response_payload = {
            **(dep.response_payload if isinstance(dep.response_payload, dict) else {}),
            "_last_query": response_payload,
        }
        dep.save(update_fields=["response_payload"])

        if str(response_payload.get("code")) == "0":
            _ppaypros_apply_payin_state(
                dep.transaction,
                dep,
                data.get("state") or data.get("orderState"),
                amount_points=data.get("amount"),
            )

        return Response(
            {
                "local_status": dep.status,
                "order_num": dep.order_num,
                "provider": response_payload,
                "provider_data": data,
            },
            status=status.HTTP_200_OK,
        )


def _atpay_collect_payload(request):
    payload = {}
    for source in [request.query_params, request.data]:
        if not source:
            continue
        if hasattr(source, "lists"):
            for key, values in source.lists():
                if values:
                    payload[key] = values[-1]
        elif isinstance(source, dict):
            for key, value in source.items():
                payload[key] = value
    return payload


def _atpay_apply_payin_status(trx: Transaction, dep: Deposit | None, trade_status, amount_value=None):
    mapped_status = atpay_map_deposit_trade_status(trade_status)
    if mapped_status == "COMPLETED":
        if dep is not None and amount_value not in (None, ""):
            try:
                callback_amount = atpay_normalize_amount(amount_value)
            except Exception:
                logger.warning("ATPAY callback amount invalid: order=%s amount=%s", getattr(dep, "order_num", ""), amount_value)
                return
            if callback_amount != atpay_normalize_amount(dep.amount):
                logger.warning(
                    "ATPAY callback amount mismatch: order=%s expected=%s got=%s",
                    dep.order_num,
                    dep.amount,
                    callback_amount,
                )
                return
        _ppaypros_complete_deposit(trx, dep)
    elif mapped_status == "FAILED":
        _ppaypros_mark_deposit_failed(trx, dep)
    elif mapped_status == "PROCESSING":
        if trx.status == "PENDING":
            trx.status = "PROCESSING"
            trx.save(update_fields=["status"])
        if dep and dep.status == "PENDING":
            dep.status = "PROCESSING"
            dep.save(update_fields=["status"])


class AtpayDepositInitiateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "deposit_initiate"

    @extend_schema(
        summary="Initiate deposit via ATPAY",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "amount": {"type": "string", "example": "100.00"},
                    "wallet_type": {"type": "string", "enum": ["BALANCE", "BALANCE_DEPOSIT"]},
                },
                "required": ["amount"],
            }
        },
    )
    def post(self, request):
        gs = GatewaySettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.atpay_enabled)
        api_url = (gs.atpay_api_url or "").strip() if gs else ""
        merchant_no = (gs.atpay_merchant_no or "").strip() if gs else ""
        sign_type = atpay_normalize_sign_type((gs.atpay_sign_type or "MD5").strip() if gs else "MD5")
        secret_key = (gs.atpay_secret_key or "").strip() if gs else ""
        private_key = (gs.atpay_private_key or "").strip() if gs else ""
        public_key = (gs.atpay_public_key or "").strip() if gs else ""
        app_domain = (gs.app_domain or "").strip() if gs else ""
        return_url = (gs.atpay_return_url or "").strip() if gs else ""
        min_deposit_amount = (gs.min_deposit_amount or Decimal("0")) if gs else Decimal("0")
        max_deposit_amount = (gs.max_deposit_amount or Decimal("0")) if gs else Decimal("0")

        if not enabled:
            return Response({"detail": "ATPAY tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not api_url or not merchant_no:
            return Response({"detail": "Konfigurasi ATPAY belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)
        if sign_type == "MD5" and not secret_key:
            return Response({"detail": "Secret key ATPAY belum diisi"}, status=status.HTTP_400_BAD_REQUEST)
        if sign_type == "MD5withRsa" and (not private_key or not public_key):
            return Response({"detail": "Private/Public key ATPAY belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({"detail": "Konfigurasi domain untuk callback belum diisi"}, status=status.HTTP_400_BAD_REQUEST)

        wallet_type = (request.data.get("wallet_type") or gs.default_wallet_type or "BALANCE").strip().upper()
        if wallet_type not in ("BALANCE", "BALANCE_DEPOSIT"):
            return Response({"detail": "wallet_type tidak valid"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            amount = atpay_normalize_amount(request.data.get("amount"))
            if amount <= 0:
                raise InvalidOperation()
        except Exception:
            return Response({"detail": "amount tidak valid"}, status=status.HTTP_400_BAD_REQUEST)

        if min_deposit_amount and min_deposit_amount > 0 and amount < min_deposit_amount:
            return Response({"detail": f"Minimal deposit adalah {min_deposit_amount}"}, status=status.HTTP_400_BAD_REQUEST)
        if max_deposit_amount and max_deposit_amount > 0 and amount > max_deposit_amount:
            return Response({"detail": f"Maksimal deposit adalah {max_deposit_amount}"}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        order_num = f"DAT{_now_wib().strftime('%y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
        callback_url = f"https://{app_domain}/api/deposits/atpay/callback/"
        title = _build_clienthub_order_item(amount)["name"][:200]

        trx = Transaction.objects.create(
            user=user,
            product=None,
            type="DEPOSIT",
            amount=amount,
            currency_code="IDR",
            description=f"Deposit via ATPAY ({wallet_type})",
            status="PENDING",
            wallet_type=wallet_type,
            trx_id=order_num,
        )
        dep = Deposit.objects.create(
            user=user,
            gateway="ATPAY",
            order_num=order_num,
            amount=amount,
            amount_currency_code="IDR",
            wallet_type=wallet_type,
            status="PENDING",
            transaction=trx,
        )

        payload = atpay_build_deposit_payload(
            merchant_no=merchant_no,
            out_trade_sn=order_num,
            title=title,
            amount=amount,
            attach=wallet_type,
            notify_url=callback_url,
            return_url=return_url,
            sign_type=sign_type,
        )
        payload["sign"] = atpay_sign_payload(payload, sign_type, secret_key=secret_key, private_key=private_key)
        dep.request_params = payload
        dep.save(update_fields=["request_params"])

        try:
            response_payload = atpay_post_json(f"{api_url.rstrip('/')}/gw-api/deposit/create", payload)
        except Exception as exc:
            dep.response_payload = {"error": str(exc)}
            dep.save(update_fields=["response_payload"])
            _ppaypros_mark_deposit_failed(trx, dep, reason="ATPAY request error")
            return Response({"detail": f"Gagal menghubungi ATPAY: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

        if response_payload.get("sign"):
            response_payload["_sign_valid"] = atpay_verify_payload(
                response_payload,
                response_payload.get("sign_type") or sign_type,
                secret_key=secret_key,
                public_key=public_key,
            )

        dep.response_payload = response_payload
        dep.save(update_fields=["response_payload"])

        if str(response_payload.get("code") or "").strip() == "100":
            data = response_payload.get("data") if isinstance(response_payload.get("data"), dict) else {}
            payment_url = str(data.get("trade_url") or "").strip()
            if payment_url:
                dep.payment_url = payment_url
                dep.save(update_fields=["payment_url"])
            return Response(
                {
                    "order_num": order_num,
                    "amount": f"{amount:.2f}",
                    "order_sn": data.get("order_sn"),
                    "payment_url": payment_url,
                    "provider": response_payload,
                },
                status=status.HTTP_200_OK,
            )

        _ppaypros_mark_deposit_failed(trx, dep, reason="ATPAY create failed")
        return Response(
            {"detail": response_payload.get("message") or "ATPAY create deposit gagal", "provider": response_payload},
            status=status.HTTP_400_BAD_REQUEST,
        )


class AtpayDepositInitiateDirectVAView(APIView):
    """
    Initiate deposit via ATPAY dan langsung menghasilkan VA (tanpa trade_url browser).
    Mirror dari AtpayDepositInitiateView, tapi backend fetch wowpayidr checkout
    secara internal dan mengembalikan VA number langsung.
    """
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "deposit_initiate"

    @extend_schema(
        summary="Initiate deposit via ATPAY — langsung return VA",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "amount": {"type": "string", "example": "100.00"},
                    "wallet_type": {"type": "string", "enum": ["BALANCE", "BALANCE_DEPOSIT"]},
                    "method": {
                        "type": "string",
                        "enum": ["BRI", "MANDIRI", "PERMATA", "DANAMON"],
                        "description": "Metode pembayaran VA yang dipilih",
                    },
                },
                "required": ["amount", "method"],
            }
        },
    )
    def post(self, request):
        gs = GatewaySettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.atpay_enabled)
        api_url = (gs.atpay_api_url or "").strip() if gs else ""
        merchant_no = (gs.atpay_merchant_no or "").strip() if gs else ""
        sign_type = atpay_normalize_sign_type((gs.atpay_sign_type or "MD5").strip() if gs else "MD5")
        secret_key = (gs.atpay_secret_key or "").strip() if gs else ""
        private_key = (gs.atpay_private_key or "").strip() if gs else ""
        public_key = (gs.atpay_public_key or "").strip() if gs else ""
        app_domain = (gs.app_domain or "").strip() if gs else ""
        return_url = (gs.atpay_return_url or "").strip() if gs else ""
        min_deposit_amount = (gs.min_deposit_amount or Decimal("0")) if gs else Decimal("0")
        max_deposit_amount = (gs.max_deposit_amount or Decimal("0")) if gs else Decimal("0")

        if not enabled:
            return Response({"detail": "ATPAY tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not api_url or not merchant_no:
            return Response({"detail": "Konfigurasi ATPAY belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)
        if sign_type == "MD5" and not secret_key:
            return Response({"detail": "Secret key ATPAY belum diisi"}, status=status.HTTP_400_BAD_REQUEST)
        if sign_type == "MD5withRsa" and (not private_key or not public_key):
            return Response({"detail": "Private/Public key ATPAY belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({"detail": "Konfigurasi domain untuk callback belum diisi"}, status=status.HTTP_400_BAD_REQUEST)

        wallet_type = (request.data.get("wallet_type") or gs.default_wallet_type or "BALANCE").strip().upper()
        if wallet_type not in ("BALANCE", "BALANCE_DEPOSIT"):
            return Response({"detail": "wallet_type tidak valid"}, status=status.HTTP_400_BAD_REQUEST)

        method = (request.data.get("method") or "").strip().upper()
        valid_methods = {"BRI", "MANDIRI", "PERMATA", "DANAMON"}
        if method not in valid_methods:
            return Response({"detail": f"method tidak valid. Pilih: {', '.join(sorted(valid_methods))}"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            amount = atpay_normalize_amount(request.data.get("amount"))
            if amount <= 0:
                raise InvalidOperation()
        except Exception:
            return Response({"detail": "amount tidak valid"}, status=status.HTTP_400_BAD_REQUEST)

        if min_deposit_amount and min_deposit_amount > 0 and amount < min_deposit_amount:
            return Response({"detail": f"Minimal deposit adalah {min_deposit_amount}"}, status=status.HTTP_400_BAD_REQUEST)
        if max_deposit_amount and max_deposit_amount > 0 and amount > max_deposit_amount:
            return Response({"detail": f"Maksimal deposit adalah {max_deposit_amount}"}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        order_num = f"DAT{_now_wib().strftime('%y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
        callback_url = f"https://{app_domain}/api/deposits/atpay/callback/"
        title = _build_clienthub_order_item(amount)["name"][:200]

        trx = Transaction.objects.create(
            user=user,
            product=None,
            type="DEPOSIT",
            amount=amount,
            currency_code="IDR",
            description=f"Deposit via ATPAY ({wallet_type})",
            status="PENDING",
            wallet_type=wallet_type,
            trx_id=order_num,
        )
        dep = Deposit.objects.create(
            user=user,
            gateway="ATPAY",
            order_num=order_num,
            amount=amount,
            amount_currency_code="IDR",
            wallet_type=wallet_type,
            status="PENDING",
            transaction=trx,
        )

        payload = atpay_build_deposit_payload(
            merchant_no=merchant_no,
            out_trade_sn=order_num,
            title=title,
            amount=amount,
            attach=wallet_type,
            notify_url=callback_url,
            return_url=return_url,
            sign_type=sign_type,
        )
        payload["sign"] = atpay_sign_payload(payload, sign_type, secret_key=secret_key, private_key=private_key)
        dep.request_params = payload
        dep.save(update_fields=["request_params"])

        try:
            response_payload = atpay_post_json(f"{api_url.rstrip('/')}/gw-api/deposit/create", payload)
        except Exception as exc:
            dep.response_payload = {"error": str(exc)}
            dep.save(update_fields=["response_payload"])
            _ppaypros_mark_deposit_failed(trx, dep, reason="ATPAY request error")
            return Response({"detail": f"Gagal menghubungi ATPAY: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

        if response_payload.get("sign"):
            response_payload["_sign_valid"] = atpay_verify_payload(
                response_payload,
                response_payload.get("sign_type") or sign_type,
                secret_key=secret_key,
                public_key=public_key,
            )

        dep.response_payload = response_payload
        dep.save(update_fields=["response_payload"])

        if str(response_payload.get("code") or "").strip() != "100":
            _ppaypros_mark_deposit_failed(trx, dep, reason="ATPAY create failed")
            return Response(
                {"detail": response_payload.get("message") or "ATPAY create deposit gagal", "provider": response_payload},
                status=status.HTTP_400_BAD_REQUEST,
            )

        data = response_payload.get("data") if isinstance(response_payload.get("data"), dict) else {}
        payment_url = str(data.get("trade_url") or "").strip()
        if not payment_url:
            _ppaypros_mark_deposit_failed(trx, dep, reason="ATPAY trade_url kosong")
            return Response({"detail": "ATPAY tidak mengembalikan trade_url"}, status=status.HTTP_400_BAD_REQUEST)

        # Save payment_url to deposit
        dep.payment_url = payment_url
        dep.save(update_fields=["payment_url"])

        # Fetch VA internally via wowpayidr
        va_result = atpay_fetch_wowpayidr_va(payment_url, method)

        if va_result.get("error"):
            logger.error(f"ATPAY VA fetch error for order {order_num}: {va_result['error']}")
            return Response({
                "order_num": order_num,
                "amount": f"{amount:.2f}",
                "order_sn": data.get("order_sn"),
                "payment_url": payment_url,
                "detail": va_result["error"],
                "available_methods": va_result.get("available_methods"),
                "provider": response_payload,
            }, status=status.HTTP_400_BAD_REQUEST)

        return Response(
            {
                "order_num": order_num,
                "amount": f"{amount:.2f}",
                "order_sn": data.get("order_sn"),
                "payment_url": payment_url,
                "va": va_result.get("va"),
                "selected_method": va_result.get("selected_method"),
                "merchant_reference_id": va_result.get("merchant_reference_id"),
                "expire_time": va_result.get("expire_time"),
                "msn": va_result.get("msn"),
                "additional_info": va_result.get("additional_info") or {},
                "method_guide": va_result.get("method_guide") or [],
                "provider": response_payload,
            },
            status=status.HTTP_200_OK,
        )


class AtpayDepositCallbackView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "gateway_callback"

    def post(self, request):
        gs = GatewaySettings.objects.order_by("-updated_at").first()
        secret_key = (gs.atpay_secret_key or "").strip() if gs else ""
        public_key = (gs.atpay_public_key or "").strip() if gs else ""
        payload = _atpay_collect_payload(request)
        order_num = str(payload.get("out_trade_sn") or "").strip()
        if not order_num:
            return HttpResponse("success", content_type="text/plain")

        trx = Transaction.objects.filter(trx_id=order_num).first()
        dep = Deposit.objects.filter(order_num=order_num, gateway="ATPAY").first()
        sign_type = payload.get("sign_type") or (gs.atpay_sign_type if gs else "MD5")
        sign_valid = atpay_verify_payload(payload, sign_type, secret_key=secret_key, public_key=public_key)

        if dep:
            dep.callback_payload = {**payload, "_sign_valid": sign_valid}
            dep.callback_at = timezone.now()
            dep.save(update_fields=["callback_payload", "callback_at"])

        if not trx or not sign_valid:
            return HttpResponse("success", content_type="text/plain")

        _atpay_apply_payin_status(trx, dep, payload.get("trade_status"), payload.get("amount"))
        return HttpResponse("success", content_type="text/plain")


class AtpayDepositQueryView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "deposit_initiate"

    @extend_schema(summary="Query status deposit ATPAY")
    def post(self, request):
        gs = GatewaySettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.atpay_enabled)
        api_url = (gs.atpay_api_url or "").strip() if gs else ""
        merchant_no = (gs.atpay_merchant_no or "").strip() if gs else ""
        sign_type = atpay_normalize_sign_type((gs.atpay_sign_type or "MD5").strip() if gs else "MD5")
        secret_key = (gs.atpay_secret_key or "").strip() if gs else ""
        private_key = (gs.atpay_private_key or "").strip() if gs else ""
        public_key = (gs.atpay_public_key or "").strip() if gs else ""
        if not enabled:
            return Response({"detail": "ATPAY tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not api_url or not merchant_no:
            return Response({"detail": "Konfigurasi ATPAY belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)

        order_num = str(request.data.get("order_num") or "").strip()
        order_sn = str(request.data.get("order_sn") or "").strip()
        if not request.user.is_staff and not order_num:
            return Response({"detail": "User biasa wajib mengirim order_num"}, status=status.HTTP_400_BAD_REQUEST)

        dep = None
        if order_num:
            dep_qs = Deposit.objects.filter(order_num=order_num, gateway="ATPAY")
            if not request.user.is_staff:
                dep_qs = dep_qs.filter(user=request.user)
            dep = dep_qs.select_related("transaction").first()
            if not dep:
                return Response({"detail": "Deposit tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)
            if not order_sn and isinstance(dep.response_payload, dict):
                data = dep.response_payload.get("data")
                if isinstance(data, dict):
                    order_sn = str(data.get("order_sn") or "").strip()

        if not order_num or not order_sn:
            return Response({"detail": "order_num dan order_sn wajib tersedia"}, status=status.HTTP_400_BAD_REQUEST)

        payload = atpay_build_deposit_query_payload(
            merchant_no=merchant_no,
            out_trade_sn=order_num,
            order_sn=order_sn,
            sign_type=sign_type,
        )
        payload["sign"] = atpay_sign_payload(payload, sign_type, secret_key=secret_key, private_key=private_key)

        response_payload = atpay_post_json(f"{api_url.rstrip('/')}/gw-api/deposit/query", payload)
        if response_payload.get("sign"):
            response_payload["_sign_valid"] = atpay_verify_payload(
                response_payload,
                response_payload.get("sign_type") or sign_type,
                secret_key=secret_key,
                public_key=public_key,
            )

        data = response_payload.get("data") if isinstance(response_payload.get("data"), dict) else {}
        dep.response_payload = {
            **(dep.response_payload if isinstance(dep.response_payload, dict) else {}),
            "_last_query": response_payload,
        }
        dep.save(update_fields=["response_payload"])

        if str(response_payload.get("code") or "").strip() == "100":
            _atpay_apply_payin_status(dep.transaction, dep, data.get("trade_status"), data.get("amount"))

        return Response(
            {
                "local_status": dep.status,
                "order_num": dep.order_num,
                "provider": response_payload,
                "provider_data": data,
            },
            status=status.HTTP_200_OK,
        )


def _clienthub_apply_callback_status(trx: Transaction, dep: Deposit | None, provider_status):
    status_value = str(provider_status or "").strip().upper()
    if status_value in ("PAID", "SETTLED"):
        _ppaypros_complete_deposit(trx, dep)
    elif status_value in ("EXPIRED", "FAILED", "CANCELLED", "VOID", "REFUND"):
        _ppaypros_mark_deposit_failed(trx, dep)
    elif status_value in ("UNPAID", "PENDING"):
        if trx.status == "PENDING":
            trx.status = "PROCESSING"
            trx.save(update_fields=["status"])
        if dep and dep.status == "PENDING":
            dep.status = "PROCESSING"
            dep.save(update_fields=["status"])


class ClientHubDepositInitiateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "deposit_initiate"

    @extend_schema(
        summary="Initiate deposit via ClientHub",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "amount": {"type": "string", "example": "100000"},
                    "wallet_type": {"type": "string", "enum": ["BALANCE", "BALANCE_DEPOSIT"]},
                    "method": {"type": "string", "example": "BRIVA"},
                },
                "required": ["amount"],
            }
        },
    )
    def post(self, request):
        gs = GatewaySettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.clienthub_enabled)
        base_url = (gs.clienthub_base_url or "").strip() if gs else ""
        client_id = (gs.clienthub_client_id or "").strip() if gs else ""
        secret_key = (gs.clienthub_secret_key or "").strip() if gs else ""
        app_domain = (gs.app_domain or "").strip() if gs else ""
        default_method = (gs.clienthub_method or "").strip() if gs else ""
        return_url = (gs.clienthub_return_url or "").strip() if gs else ""
        expired_minutes = int(getattr(gs, "clienthub_expired_minutes", 60) or 60) if gs else 60
        min_deposit_amount = (gs.min_deposit_amount or Decimal("0")) if gs else Decimal("0")
        max_deposit_amount = (gs.max_deposit_amount or Decimal("0")) if gs else Decimal("0")

        if not enabled:
            return Response({"detail": "ClientHub tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not base_url or not client_id or not secret_key:
            return Response({"detail": "Konfigurasi ClientHub belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({"detail": "Konfigurasi domain untuk callback belum diisi"}, status=status.HTTP_400_BAD_REQUEST)

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

        if amount != amount.quantize(Decimal("1")):
            return Response({"detail": "amount ClientHub harus bilangan bulat"}, status=status.HTTP_400_BAD_REQUEST)
        if min_deposit_amount and min_deposit_amount > 0 and amount < min_deposit_amount:
            return Response({"detail": f"Minimal deposit adalah {min_deposit_amount}"}, status=status.HTTP_400_BAD_REQUEST)
        if max_deposit_amount and max_deposit_amount > 0 and amount > max_deposit_amount:
            return Response({"detail": f"Maksimal deposit adalah {max_deposit_amount}"}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        order_num = f"DCH{_now_wib().strftime('%y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
        method = (request.data.get("method") or default_method or "BRIVA").strip()
        callback_url = f"https://{app_domain}/api/deposits/clienthub/callback/"
        expired_time = int(pytime.time()) + max(expired_minutes, 1) * 60

        trx = Transaction.objects.create(
            user=user,
            product=None,
            type="DEPOSIT",
            amount=amount,
            currency_code="IDR",
            description=f"Deposit via ClientHub ({wallet_type})",
            status="PENDING",
            wallet_type=wallet_type,
            trx_id=order_num,
        )

        order_item = _build_clienthub_order_item(amount)
        payload = clienthub_build_create_transaction_payload(
            method=method,
            merchant_ref=order_num,
            amount=int(amount),
            customer_name=((getattr(user, "full_name", "") or user.username or f"User {user.pk}")[:100]),
            customer_email=((getattr(user, "email", "") or f"user{user.pk}@example.com")[:100]),
            customer_phone=((getattr(user, "phone", "") or "")[:32]),
            client_callback_url=callback_url,
            return_url=return_url,
            expired_time=expired_time,
            order_items=[order_item],
        )
        raw_body = clienthub_dumps_raw_json(payload)
        timestamp = str(int(pytime.time()))
        signature = clienthub_sign_client_request(
            client_id=client_id,
            timestamp=timestamp,
            raw_body=raw_body,
            secret_key=secret_key,
        )

        logger.warning(
            "CLIENTHUB payin request: order=%s client_id=%s method=%s callback_url=%s payload=%s",
            order_num,
            client_id,
            method,
            callback_url,
            raw_body,
        )

        dep = Deposit.objects.create(
            user=user,
            gateway="CLIENTHUB",
            order_num=order_num,
            amount=amount,
            amount_currency_code="IDR",
            wallet_type=wallet_type,
            status="PENDING",
            transaction=trx,
            request_params={
                **payload,
                "_clienthub_timestamp": timestamp,
            },
        )

        try:
            response_payload = clienthub_post_create_transaction(
                base_url=base_url,
                client_id=client_id,
                timestamp=timestamp,
                signature=signature,
                raw_body=raw_body,
            )
        except requests.HTTPError as exc:
            body = exc.response.text if exc.response is not None else str(exc)
            dep.response_payload = {"error": body}
            dep.save(update_fields=["response_payload"])
            _ppaypros_mark_deposit_failed(trx, dep, reason="ClientHub HTTP error")
            return Response({"detail": f"Gagal membuat transaksi ClientHub: {body}"}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception as exc:
            dep.response_payload = {"error": str(exc)}
            dep.save(update_fields=["response_payload"])
            _ppaypros_mark_deposit_failed(trx, dep, reason="ClientHub request error")
            return Response({"detail": f"Gagal menghubungi ClientHub: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

        logger.warning(
            "CLIENTHUB payin response: order=%s body=%s",
            order_num,
            json.dumps(_redact_provider_payload_for_log(response_payload), ensure_ascii=False),
        )

        dep.response_payload = response_payload
        dep.save(update_fields=["response_payload"])

        if bool(response_payload.get("success")):
            data = response_payload.get("data") if isinstance(response_payload.get("data"), dict) else {}
            payment_url = (data.get("checkout_url") or data.get("checkoutUrl") or "").strip()
            if not payment_url:
                payment_url, _ = _extract_payment_url(response_payload)
            if payment_url:
                dep.payment_url = payment_url
                dep.save(update_fields=["payment_url"])
            _clienthub_apply_callback_status(trx, dep, data.get("status"))
            return Response(
                {
                    "order_num": order_num,
                    "amount": data.get("amount"),
                    "reference": data.get("reference"),
                    "payment_method": data.get("payment_method"),
                    "payment_name": data.get("payment_name"),
                    "pay_code": data.get("pay_code"),
                    "status": data.get("status"),
                    "expired_time": data.get("expired_time"),
                },
                status=status.HTTP_200_OK,
            )

        _ppaypros_mark_deposit_failed(trx, dep, reason="ClientHub create failed")
        return Response(
            {"detail": response_payload.get("message") or "ClientHub create transaction gagal", "provider": response_payload},
            status=status.HTTP_400_BAD_REQUEST,
        )


class ClientHubDepositCallbackView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "gateway_callback"

    def post(self, request):
        gs = GatewaySettings.objects.order_by("-updated_at").first()
        secret_key = (gs.clienthub_secret_key or "").strip() if gs else ""
        raw_body = request.body or b""
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception:
            payload = {}

        order_num = str(payload.get("merchant_ref") or "").strip()
        if not order_num:
            return Response({"ok": True}, status=status.HTTP_200_OK)

        trx = Transaction.objects.filter(trx_id=order_num).first()
        dep = Deposit.objects.filter(order_num=order_num, gateway="CLIENTHUB").first()
        if dep:
            callback_payload = payload if isinstance(payload, dict) else {}
            callback_payload["_signature"] = (request.headers.get("X-Hub-Signature", "") or "").strip()
            callback_payload["_sign_valid"] = clienthub_verify_callback_signature(
                secret_key=secret_key,
                raw_body=raw_body,
                signature=request.headers.get("X-Hub-Signature", ""),
            ) if secret_key else False
            dep.callback_payload = callback_payload
            dep.callback_at = timezone.now()
            dep.save(update_fields=["callback_payload", "callback_at"])

        if not trx or not secret_key:
            return Response({"ok": True}, status=status.HTTP_200_OK)

        sign_valid = clienthub_verify_callback_signature(
            secret_key=secret_key,
            raw_body=raw_body,
            signature=request.headers.get("X-Hub-Signature", ""),
        )
        if not sign_valid:
            return Response({"ok": True}, status=status.HTTP_200_OK)

        _clienthub_apply_callback_status(trx, dep, payload.get("status"))
        return Response({"ok": True}, status=status.HTTP_200_OK)


def _sitransferhub_extract_status(payload: dict) -> str:
    if not isinstance(payload, dict):
        return ""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    gateway_status = payload.get("gateway_status") if isinstance(payload.get("gateway_status"), dict) else {}
    gateway_status_data = gateway_status.get("data") if isinstance(gateway_status.get("data"), dict) else {}
    gateway_callback = payload.get("gateway_callback") if isinstance(payload.get("gateway_callback"), dict) else {}
    gateway_callback_data = gateway_callback.get("data") if isinstance(gateway_callback.get("data"), dict) else {}
    for source in (data, gateway_status_data, gateway_callback_data, payload):
        value = str(source.get("status") or "").strip()
        if value:
            return value
    return ""


def _sitransferhub_apply_callback_status(trx: Transaction, dep: Deposit | None, provider_status):
    status_value = str(provider_status or "").strip().lower()
    if status_value in ("success", "paid", "completed", "settled"):
        _ppaypros_complete_deposit(trx, dep)
    elif status_value in ("failed", "cancelled", "expired", "void", "error"):
        _ppaypros_mark_deposit_failed(trx, dep)
    elif status_value in ("pending", "unpaid", "waiting", "process", "processing"):
        if trx.status == "PENDING":
            trx.status = "PROCESSING"
            trx.save(update_fields=["status"])
        if dep and dep.status == "PENDING":
            dep.status = "PROCESSING"
            dep.save(update_fields=["status"])


class SiTransferHubDepositInitiateView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = "deposit_initiate"

    @extend_schema(
        summary="Initiate deposit via SiTransfer Hub",
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "amount": {"type": "string", "example": "100000"},
                    "wallet_type": {"type": "string", "enum": ["BALANCE", "BALANCE_DEPOSIT"]},
                    "channel": {"type": "string", "enum": ["QRIS", "DANA"], "example": "QRIS"},
                },
                "required": ["amount"],
            }
        },
    )
    def post(self, request):
        gs = GatewaySettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.sitransferhub_enabled)
        base_url = (gs.sitransferhub_base_url or "").strip() if gs else ""
        client_id = (gs.sitransferhub_client_id or "").strip() if gs else ""
        secret_key = (gs.sitransferhub_secret_key or "").strip() if gs else ""
        app_domain = (gs.app_domain or "").strip() if gs else ""
        default_channel = (gs.sitransferhub_channel or "").strip() if gs else ""
        min_deposit_amount = (gs.min_deposit_amount or Decimal("0")) if gs else Decimal("0")
        max_deposit_amount = (gs.max_deposit_amount or Decimal("0")) if gs else Decimal("0")

        if not enabled:
            return Response({"detail": "SiTransfer Hub tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not base_url or not client_id or not secret_key:
            return Response({"detail": "Konfigurasi SiTransfer Hub belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({"detail": "Konfigurasi domain untuk callback belum diisi"}, status=status.HTTP_400_BAD_REQUEST)

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

        if amount != amount.quantize(Decimal("1")):
            return Response({"detail": "amount SiTransfer Hub harus bilangan bulat"}, status=status.HTTP_400_BAD_REQUEST)
        if min_deposit_amount and min_deposit_amount > 0 and amount < min_deposit_amount:
            return Response({"detail": f"Minimal deposit adalah {min_deposit_amount}"}, status=status.HTTP_400_BAD_REQUEST)
        if max_deposit_amount and max_deposit_amount > 0 and amount > max_deposit_amount:
            return Response({"detail": f"Maksimal deposit adalah {max_deposit_amount}"}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user
        order_num = f"DSH{_now_wib().strftime('%y%m%d%H%M%S')}{uuid.uuid4().hex[:8].upper()}"
        channel = (request.data.get("channel") or default_channel or "QRIS").strip().upper()
        if channel not in ("QRIS", "DANA"):
            return Response({"detail": "channel harus QRIS atau DANA"}, status=status.HTTP_400_BAD_REQUEST)
        callback_url = f"https://{app_domain}/api/deposits/sitransferhub/callback/"
        player_username = str(
            getattr(user, "username", "")
            or getattr(user, "phone", "")
            or f"user{user.pk}"
        ).strip()[:100]

        trx = Transaction.objects.create(
            user=user,
            product=None,
            type="DEPOSIT",
            amount=amount,
            currency_code="IDR",
            description=f"Deposit via SiTransfer Hub ({wallet_type})",
            status="PENDING",
            wallet_type=wallet_type,
            trx_id=order_num,
        )

        payload = sitransferhub_build_create_transaction_payload(
            merchant_ref=order_num,
            channel=channel,
            amount=int(amount),
            player_username=player_username,
            client_callback_url=callback_url,
        )
        raw_body = sitransferhub_dumps_raw_json(payload)
        timestamp = str(int(pytime.time()))
        signature = sitransferhub_sign_client_request(
            client_id=client_id,
            timestamp=timestamp,
            raw_body=raw_body,
            secret_key=secret_key,
        )

        logger.warning(
            "SITRANSFERHUB payin request: order=%s client_id=%s channel=%s callback_url=%s payload=%s",
            order_num,
            client_id,
            channel,
            callback_url,
            raw_body,
        )

        dep = Deposit.objects.create(
            user=user,
            gateway="SITRANSFERHUB",
            order_num=order_num,
            amount=amount,
            amount_currency_code="IDR",
            wallet_type=wallet_type,
            status="PENDING",
            transaction=trx,
            request_params={**payload, "_sitransferhub_timestamp": timestamp},
        )

        try:
            response_payload = sitransferhub_post_create_transaction(
                base_url=base_url,
                client_id=client_id,
                timestamp=timestamp,
                signature=signature,
                raw_body=raw_body,
            )
        except requests.HTTPError as exc:
            body = exc.response.text if exc.response is not None else str(exc)
            dep.response_payload = {"error": body}
            dep.save(update_fields=["response_payload"])
            _ppaypros_mark_deposit_failed(trx, dep, reason="SiTransfer Hub HTTP error")
            return Response({"detail": f"Gagal membuat transaksi SiTransfer Hub: {body}"}, status=status.HTTP_502_BAD_GATEWAY)
        except Exception as exc:
            dep.response_payload = {"error": str(exc)}
            dep.save(update_fields=["response_payload"])
            _ppaypros_mark_deposit_failed(trx, dep, reason="SiTransfer Hub request error")
            return Response({"detail": f"Gagal menghubungi SiTransfer Hub: {exc}"}, status=status.HTTP_502_BAD_GATEWAY)

        logger.warning(
            "SITRANSFERHUB payin response: order=%s body=%s",
            order_num,
            json.dumps(_redact_provider_payload_for_log(response_payload), ensure_ascii=False),
        )

        dep.response_payload = response_payload
        dep.save(update_fields=["response_payload"])

        if bool(response_payload.get("success")):
            data = response_payload.get("data") if isinstance(response_payload.get("data"), dict) else {}
            payment_url = str(data.get("payment_url") or "").strip()
            qris_image = str(data.get("qris_image") or "").strip()
            if payment_url:
                dep.payment_url = payment_url
                dep.save(update_fields=["payment_url"])
            elif qris_image:
                dep.payment_url = qris_image
                dep.save(update_fields=["payment_url"])
            return Response(
                {
                    "order_num": order_num,
                    "amount": data.get("amount"),
                    "transaction_id": data.get("transaction_id"),
                    "channel": data.get("type") or channel,
                    "expired_at": data.get("expired_at"),
                    "instruction": data.get("instruction"),
                    "qris_image": data.get("qris_image"),
                    "qris_data": data.get("qris_data"),
                    "payment_url": data.get("payment_url"),
                },
                status=status.HTTP_200_OK,
            )

        _ppaypros_mark_deposit_failed(trx, dep, reason="SiTransfer Hub create failed")
        return Response(
            {"detail": response_payload.get("message") or "SiTransfer Hub create transaction gagal", "provider": response_payload},
            status=status.HTTP_400_BAD_REQUEST,
        )


class SiTransferHubDepositCallbackView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "gateway_callback"

    def post(self, request):
        gs = GatewaySettings.objects.order_by("-updated_at").first()
        secret_key = (gs.sitransferhub_secret_key or "").strip() if gs else ""
        raw_body = request.body or b""
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception:
            payload = {}

        order_num = str(payload.get("merchant_ref") or "").strip()
        if not order_num:
            return Response({"ok": True}, status=status.HTTP_200_OK)

        trx = Transaction.objects.filter(trx_id=order_num).first()
        dep = Deposit.objects.filter(order_num=order_num, gateway="SITRANSFERHUB").first()
        if dep:
            callback_payload = payload if isinstance(payload, dict) else {}
            callback_payload["_signature"] = (request.headers.get("X-Hub-Signature", "") or "").strip()
            callback_payload["_sign_valid"] = sitransferhub_verify_callback_signature(
                secret_key=secret_key,
                raw_body=raw_body,
                signature=request.headers.get("X-Hub-Signature", ""),
            ) if secret_key else False
            dep.callback_payload = callback_payload
            dep.callback_at = timezone.now()
            dep.save(update_fields=["callback_payload", "callback_at"])

        if not trx or not secret_key:
            return Response({"ok": True}, status=status.HTTP_200_OK)

        sign_valid = sitransferhub_verify_callback_signature(
            secret_key=secret_key,
            raw_body=raw_body,
            signature=request.headers.get("X-Hub-Signature", ""),
        )
        if not sign_valid:
            return Response({"ok": True}, status=status.HTTP_200_OK)

        _sitransferhub_apply_callback_status(trx, dep, _sitransferhub_extract_status(payload))
        return Response({"ok": True}, status=status.HTTP_200_OK)


class DepositTransactionsListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'transactions'

    @extend_schema(
        summary="Daftar transaksi Deposit",
        parameters=[
            OpenApiParameter(name='status', type=str, description='Filter status transaksi'),
            OpenApiParameter(name='wallet_type', type=str, description='Filter wallet (BALANCE/BALANCE_DEPOSIT)'),
            OpenApiParameter(name='start_date', type=str, description='Tanggal mulai (YYYY-MM-DD)'),
            OpenApiParameter(name='end_date', type=str, description='Tanggal akhir (YYYY-MM-DD)'),
            OpenApiParameter(name='gateway', type=str, description='Filter gateway (JAYAPAY/KLIKPAY/USD_GATEWAY/PPAYPROS/CLIENTHUB)'),
            OpenApiParameter(name='order_num', type=str, description='Filter berdasarkan nomor order'),
            OpenApiParameter(name='page', type=int, description='A page number within the paginated result set.'),
        ],
        responses=TransactionSerializer(many=True),
        description='Mengambil daftar transaksi bertipe DEPOSIT untuk user saat ini atau semua jika admin.'
    )
    def get(self, request):
        # Base queryset: admin melihat semua; user melihat miliknya atau referral
        if request.user.is_staff:
            queryset = Transaction.objects.all()
        else:
            queryset = Transaction.objects.filter(Q(user=request.user) | Q(upline_user=request.user))
        
        # Optimize queries to avoid N+1
        queryset = queryset.select_related('user', 'product', 'upline_user').prefetch_related('related_withdrawal')

        # Hanya transaksi bertipe DEPOSIT
        queryset = queryset.filter(type='DEPOSIT')

        # Query params
        status_param = request.query_params.get('status')
        wallet_type = request.query_params.get('wallet_type')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        gateway = request.query_params.get('gateway')
        order_num = request.query_params.get('order_num')

        # Filter langsung di Transaction
        if status_param:
            queryset = queryset.filter(status=status_param)
        if wallet_type:
            queryset = queryset.filter(wallet_type=wallet_type)
        tz = ZoneInfo('Asia/Jakarta')
        if start_date:
            try:
                sd = datetime.strptime(start_date, '%Y-%m-%d').date()
                start_dt = datetime.combine(sd, time.min, tz)
                queryset = queryset.filter(created_at__gte=start_dt)
            except ValueError:
                pass
        if end_date:
            try:
                ed = datetime.strptime(end_date, '%Y-%m-%d').date()
                end_exclusive = datetime.combine(ed + timedelta(days=1), time.min, tz)
                queryset = queryset.filter(created_at__lt=end_exclusive)
            except ValueError:
                pass

        # Filter melalui relasi Deposit (gateway, order_num)
        if gateway or order_num:
            dep_qs = Deposit.objects.all() if request.user.is_staff else Deposit.objects.filter(user=request.user)
            if gateway:
                dep_qs = dep_qs.filter(gateway=gateway)
            if order_num:
                dep_qs = dep_qs.filter(order_num=order_num)
            queryset = queryset.filter(id__in=dep_qs.values_list('transaction_id', flat=True))

        queryset = queryset.order_by('-created_at')
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = TransactionSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)
