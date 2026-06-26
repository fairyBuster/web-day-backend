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
import uuid
import requests
import hashlib
import hmac
import time as pytime
import logging
import json
import re
from django.http import HttpResponse

from products.models import Transaction
from products.serializers import TransactionSerializer
from .models import GatewaySettings, Deposit
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
            payment_url = data.get('url')
            if payment_url:
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
                return Response({'detail': 'Gateway tidak mengembalikan URL pembayaran'}, status=status.HTTP_502_BAD_GATEWAY)
        else:
            trx.status = 'FAILED'
            trx.save(update_fields=['status'])
            dep.response_payload = data
            dep.status = 'FAILED'
            dep.save(update_fields=['response_payload', 'status'])
            return Response({'detail': data.get('platRespMessage') or 'Pembayaran gagal'}, status=status.HTTP_400_BAD_REQUEST)


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
            OpenApiParameter(name='gateway', type=str, description='Filter gateway (JAYAPAY/KLIKPAY/USD_GATEWAY)'),
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
