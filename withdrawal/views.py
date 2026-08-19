from rest_framework import generics, permissions, status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema, OpenApiParameter
from .models import Withdrawal, WithdrawalSettings, WithdrawalService
from .serializers import WithdrawalSerializer, WithdrawalSettingsSerializer, WithdrawalServiceSerializer
from django.conf import settings
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
import logging
import time as pytime
from rest_framework.views import APIView
from django.http import HttpResponse

from .integrations.jayapay import build_params, sign_params_legacy, send_cash_request
from .models import JayapayWithdrawal, JayapayPhPayoutWithdrawal, UsdPayoutWithdrawal, PPayProsWithdrawal, AtpayWithdrawal, BankPayWithdrawal, ReepayWithdrawal
from products.models import Transaction
from products.serializers import TransactionSerializer
from django.db.models import Q
from zoneinfo import ZoneInfo
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import json
import requests

from .integrations.usd_payout import build_payload as usd_build_payload, sign_hmac_sha256, sign_hmac_sha256_then_rsa_base64, send_single_order
from .integrations.ppaypros import build_payout_payload as ppaypros_build_payout_payload, map_payout_state as ppaypros_map_payout_state, normalize_amount as ppaypros_normalize_amount
from deposits.integrations.ppaypros import amount_to_points as ppaypros_amount_to_points, generate_sign as ppaypros_generate_sign, parse_data_field as ppaypros_parse_data_field, post_json as ppaypros_post_json, verify_sign as ppaypros_verify_sign
from deposits.integrations.atpay import (
    build_bank_code_payload as atpay_build_bank_code_payload,
    build_payout_payload as atpay_build_payout_payload,
    build_payout_query_payload as atpay_build_payout_query_payload,
    map_payout_trade_status as atpay_map_payout_trade_status,
    normalize_amount as atpay_normalize_amount,
    normalize_sign_type as atpay_normalize_sign_type,
    post_json as atpay_post_json,
    sign_payload as atpay_sign_payload,
    verify_payload as atpay_verify_payload,
)
from deposits.integrations.bankpay import (
    generate_sign as bankpay_generate_sign,
    verify_sign as bankpay_verify_sign,
    post_form as bankpay_post_form,
    build_payout_payload as bankpay_build_payout_payload,
    map_payout_returncode as bankpay_map_payout_returncode,
)
from deposits.integrations.reepay import (
    post_json as reepay_post_json,
    verify_callback_signature as reepay_verify_callback_signature,
    extract_callback_field as reepay_extract_callback_field,
)
from deposits.utils import verify_jayapay_signature
from .integrations.jayapay_ph_banks import JAYAPAY_PH_PAYOUT_BANKS

logger = logging.getLogger(__name__)

def _resolve_app_domain(gs: WithdrawalSettings | None) -> str:
    domain = (getattr(gs, "app_domain", "") or "").strip() if gs else ""
    if domain:
        return domain
    try:
        from deposits.models import GatewaySettings
        ggs = GatewaySettings.objects.order_by("-updated_at").first()
        return (getattr(ggs, "app_domain", "") or "").strip() if ggs else ""
    except Exception:
        return ""


def _ppaypros_collect_payload(request):
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


def _ppaypros_store_trace(trace: PPayProsWithdrawal | None, payload: dict):
    if not trace:
        return
    current = trace.response_payload if isinstance(trace.response_payload, dict) else {}
    current.update(payload or {})
    trace.response_payload = current
    trace.save(update_fields=["response_payload"])

class WithdrawalSettingsView(generics.RetrieveAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = WithdrawalSettingsSerializer

    @extend_schema(summary='Get withdrawal settings')
    def get_object(self):
        return WithdrawalSettings.objects.order_by('-updated_at').first()


class WithdrawalServiceListView(generics.ListAPIView):
    permission_classes = [permissions.AllowAny]
    serializer_class = WithdrawalServiceSerializer
    throttle_scope = 'withdrawals'

    @extend_schema(summary='List withdrawal services (active)')
    def get_queryset(self):
        return WithdrawalService.objects.filter(is_active=True).order_by('sort_order', 'duration_hours', 'name')


class WithdrawalListCreateView(generics.ListCreateAPIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = WithdrawalSerializer
    throttle_scope = 'withdrawals'

    def get_queryset(self):
        return Withdrawal.objects.filter(user=self.request.user).order_by('-created_at')

    @extend_schema(summary='List user withdrawals')
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    @extend_schema(
        summary='Request withdrawal',
        parameters=[
            OpenApiParameter(name='bank_account_id', description='UserBank ID (optional, default account used if omitted)', required=False, type=int),
        ],
        request={
            'application/json': {
                'type': 'object',
                'properties': {
                    'amount': {'type': 'string', 'description': 'Withdrawal amount'},
                    'bank_account_id': {'type': 'integer', 'nullable': True},
                    'pin': {'type': 'string', 'description': '6-digit PIN if required', 'nullable': True},
                    'service_id': {'type': 'integer', 'description': 'ID jasa withdraw', 'nullable': True},
                },
                'required': ['amount']
            }
        }
    )
    def post(self, request, *args, **kwargs):
        return super().post(request, *args, **kwargs)


class JayapayInitiateView(APIView):
    permission_classes = [permissions.IsAdminUser]
    throttle_scope = 'withdraw_admin_initiate'

    @extend_schema(
        summary="Inisiasi withdraw otomatis via Jayapay (admin)",
        parameters=[
            OpenApiParameter(name="pk", description="Withdrawal ID", required=True, type=int),
        ],
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "bankCode": {"type": "string"},
                    "accountNumber": {"type": "string"},
                    "accountName": {"type": "string"},
                },
                "required": ["bankCode", "accountNumber", "accountName"],
            }
        },
    )
    def post(self, request, pk: int):
        gs = WithdrawalSettings.objects.first()
        jayapay_enabled = bool(gs and gs.jayapay_enabled)
        merchant_code = (gs.jayapay_merchant_code or '').strip() if gs else ''
        private_key = (gs.jayapay_private_key or '').strip() if gs else ''
        app_domain = _resolve_app_domain(gs)

        if not jayapay_enabled:
            return Response({"detail": "Jayapay tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not merchant_code or not private_key:
            return Response({"detail": "Konfigurasi Jayapay belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({"detail": "Konfigurasi domain untuk callback belum diisi"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            withdrawal = Withdrawal.objects.select_related("user").get(pk=pk)
        except Withdrawal.DoesNotExist:
            return Response({"detail": "Withdrawal tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)

        if withdrawal.status not in ["PENDING", "PROCESSING"]:
            return Response({"detail": "Status withdrawal tidak valid untuk inisiasi"}, status=status.HTTP_400_BAD_REQUEST)

        bank_code = request.data.get("bankCode")
        account_number = request.data.get("accountNumber")
        account_name = request.data.get("accountName")
        if not bank_code or not account_number or not account_name:
            return Response({"detail": "bankCode, accountNumber, accountName wajib diisi"}, status=status.HTTP_400_BAD_REQUEST)

        notify_url = f"https://{app_domain}/api/withdrawals/jayapay/callback/"
        params = build_params(
            withdrawal,
            merchant_code=merchant_code,
            bank_code=bank_code,
            account_number=account_number,
            account_name=account_name,
            notify_url=notify_url,
        )

        try:
            params["sign"] = sign_params_legacy(params, private_key)
        except Exception as e:
            logger.error(f"Jayapay signature creation failed for withdrawal {pk}: {e}", exc_info=True)
            return Response({"detail": f"Gagal membuat tanda tangan: {e}"}, status=status.HTTP_400_BAD_REQUEST)

        # Ensure JayapayWithdrawal record exists for traceability
        jp_withdrawal, _ = JayapayWithdrawal.objects.get_or_create(
            withdrawal=withdrawal,
            defaults={"request_params": params}
        )
        if jp_withdrawal and not jp_withdrawal.request_params:
            jp_withdrawal.request_params = params
            jp_withdrawal.save(update_fields=["request_params"])

        try:
            logger.info(f"Sending Jayapay request for withdrawal {pk} with params: {{k: v for k, v in params.items() if k != 'sign'}}")
            resp = send_cash_request(params)
            logger.info(f"Jayapay response for withdrawal {pk}: {resp}")
        except Exception as e:
            withdrawal.status = "PROCESSING"
            withdrawal.save()
            jp_withdrawal.response_payload = {'error': str(e)}
            jp_withdrawal.save(update_fields=['response_payload'])
            logger.error(f"Jayapay request failed for withdrawal {pk}: {e}", exc_info=True)
            return Response({"detail": f"Gagal kirim ke Jayapay: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        jp_withdrawal.response_payload = resp
        jp_withdrawal.save(update_fields=['response_payload'])

        withdrawal.status = "PROCESSING"
        withdrawal.save()
        return Response({"jayapay": resp, "submitted_params": {k: v for k, v in params.items() if k != "sign"}}, status=status.HTTP_200_OK)


@method_decorator(csrf_exempt, name="dispatch")
class JayapayCallbackView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'gateway_callback'

    @extend_schema(summary="Callback Jayapay untuk update status withdraw")
    def post(self, request, *args, **kwargs):
        data = request.data if isinstance(request.data, dict) else {}
        # Logging payload masuk untuk diagnosa callback
        try:
            logger.info(f"Jayapay callback received: {data}")
        except Exception:
            logger.warning("Jayapay callback: failed to log payload")
        order_num = data.get("orderNum") or data.get("order_no") or ""
        status_str = str(data.get("status") or data.get("order_status") or "").lower()
        status_msg = str(data.get("statusMsg") or data.get("status_msg") or "").lower()

        # Support unified code WD-... and legacy W<withdrawal.id>...
        wid = None
        if order_num.startswith("WD-"):
            # Find withdrawal via linked transaction.trx_id
            try:
                from products.models import Transaction
                trx = Transaction.objects.filter(trx_id=order_num).first()
                if trx:
                    linked = Withdrawal.objects.filter(transaction=trx).first()
                    if linked:
                        wid = linked.pk
                        withdrawal = linked
                    else:
                        withdrawal = None
                else:
                    withdrawal = None
            except Exception:
                withdrawal = None
        elif order_num.startswith("W"):
            # Legacy path: extract numeric digits after 'W' as withdrawal.id
            wid_digits = []
            for ch in order_num[1:]:
                if ch.isdigit():
                    wid_digits.append(ch)
                else:
                    break
            if wid_digits:
                try:
                    wid = int("".join(wid_digits))
                    withdrawal = Withdrawal.objects.get(pk=wid)
                except Exception:
                    withdrawal = None
            else:
                withdrawal = None
        else:
            return Response({"detail": "orderNum tidak valid"}, status=status.HTTP_400_BAD_REQUEST)

        if not withdrawal:
            logger.warning(f"Jayapay callback: withdrawal not found for order {order_num}")
            return Response("SUCCESS")

        mapped = None
        # Jayapay status normalization per spec:
        # 0: Pending processing -> PROCESSING
        # 1: Processing -> PROCESSING
        # 2: Payment successful -> COMPLETED
        # 4: Payment failed -> REJECTED
        # 5: Bank payment in progress -> PROCESSING
        if status_str in {"success", "sukses", "completed", "finish", "done", "2"}:
            mapped = "COMPLETED"
        elif status_str in {"failed", "gagal", "reject", "rejected", "4"}:
            mapped = "REJECTED"
        elif status_str in {"processing", "pending", "0", "1", "5"} or status_msg in {"apply", "applied", "processing", "pending"}:
            mapped = "PROCESSING"

        if not mapped:
            logger.warning(f"Jayapay callback: unrecognized status for order {order_num}: status={status_str} statusMsg={status_msg}")
            return HttpResponse("SUCCESS", content_type="text/plain")

        withdrawal.status = mapped
        withdrawal.save()
        # Per JayaPay spec, always respond plain text "SUCCESS" to stop retries
        return HttpResponse("SUCCESS", content_type="text/plain")


class UsdPayoutInitiateView(APIView):
    permission_classes = [permissions.IsAdminUser]
    throttle_scope = 'withdraw_admin_initiate'

    @extend_schema(
        summary="Inisiasi withdraw otomatis via USD payout gateway (admin)",
        parameters=[
            OpenApiParameter(name="pk", description="Withdrawal ID", required=True, type=int),
        ],
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "bankCode": {"type": "string"},
                    "accNo": {"type": "string"},
                    "accName": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                    "orderAmount": {"type": "string"},
                },
                "required": ["bankCode", "accNo", "accName"],
            }
        },
    )
    def post(self, request, pk: int):
        if not getattr(settings, "USD_PAYOUT_ENABLED", False):
            return Response({"detail": "USD payout gateway tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not settings.USD_PAYOUT_API_URL or not settings.USD_PAYOUT_MER_NO or not settings.USD_PAYOUT_SIGN_KEY or not settings.USD_PAYOUT_RSA_PRIVATE_KEY:
            return Response({"detail": "Konfigurasi USD payout gateway belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            wd = Withdrawal.objects.select_related("user", "bank_account__bank", "transaction").get(pk=pk)
        except Withdrawal.DoesNotExist:
            return Response({"detail": "Withdrawal tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)

        if wd.status not in ("PENDING", "PROCESSING"):
            return Response({"detail": "Status withdrawal tidak valid untuk inisiasi"}, status=status.HTTP_400_BAD_REQUEST)

        bank_code = (request.data.get("bankCode") or "").strip()
        acc_no = (request.data.get("accNo") or "").strip()
        acc_name = (request.data.get("accName") or "").strip()
        if not bank_code or not acc_no or not acc_name:
            return Response({"detail": "bankCode, accNo, accName wajib diisi"}, status=status.HTTP_400_BAD_REQUEST)

        allowed_bank_codes = {"ETH", "TRX", "MATIC", "BSC", "SOL", "ARBEVM", "CASH", "VENMO", "PAYPAL"}
        if bank_code not in allowed_bank_codes:
            return Response({"detail": f"bankCode tidak valid (pilih: {', '.join(sorted(allowed_bank_codes))})"}, status=status.HTTP_400_BAD_REQUEST)

        user = wd.user
        email = (request.data.get("email") or getattr(user, "email", "") or "").strip() or f"user{user.id}@example.com"
        phone = (request.data.get("phone") or getattr(user, "phone", "") or "").strip()
        phone_digits = "".join([c for c in phone if c.isdigit()]) or "0000000000"

        order_amount_raw = request.data.get("orderAmount")
        try:
            order_amount = Decimal(str(order_amount_raw)).quantize(Decimal("0.01")) if order_amount_raw is not None else Decimal(str(wd.net_amount or wd.amount)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError, TypeError):
            return Response({"detail": "orderAmount tidak valid"}, status=status.HTTP_400_BAD_REQUEST)

        mer_order_no = getattr(getattr(wd, "transaction", None), "trx_id", None) or f"W{wd.id}{int(pytime.time()*1000)}"
        notify_url = getattr(settings, "USD_PAYOUT_NOTIFY_URL", "")
        payload = usd_build_payload(
            acc_name=acc_name,
            acc_no=acc_no,
            bank_code=bank_code,
            busi_code="265001",
            currency="USD",
            email=email,
            mer_no=settings.USD_PAYOUT_MER_NO,
            mer_order_no=mer_order_no,
            notify_url=notify_url,
            order_amount=f"{order_amount:.2f}",
            phone=phone_digits,
        )
        sign_key = (settings.USD_PAYOUT_SIGN_KEY or "").strip()
        key_is_hex = len(sign_key) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in sign_key) and bool(sign_key)
        sign, sign_a, raw = sign_hmac_sha256_then_rsa_base64(
            payload,
            sign_key=sign_key,
            rsa_private_key_pem=settings.USD_PAYOUT_RSA_PRIVATE_KEY,
            hex_key=False,
        )
        payload["sign"] = sign

        trace, _ = UsdPayoutWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
        if trace and not trace.request_params:
            trace.request_params = payload
            trace.save(update_fields=["request_params"])

        logger.warning(
            "USD_PAYOUT singleOrder request: withdrawal=%s order=%s merNo=***%s bankCode=%s accNo=%s amount=%s raw=%s signA=%s sign=%s",
            wd.id,
            mer_order_no,
            settings.USD_PAYOUT_MER_NO[-6:],
            bank_code,
            acc_no[-4:] if acc_no else "",
            payload.get("orderAmount"),
            raw,
            sign_a[:10],
            sign[:10],
        )

        try:
            resp_data = send_single_order(settings.USD_PAYOUT_API_URL, payload)
        except Exception as e:
            wd.status = "PROCESSING"
            wd.save(update_fields=["status"])
            trace.response_payload = {"error": str(e)}
            trace.save(update_fields=["response_payload"])
            return Response({"detail": f"Gagal menghubungi gateway: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        code_first = str(resp_data.get("code") or "").strip()
        if code_first == "901007" and key_is_hex:
            payload_retry = dict(payload)
            sign2, sign_a2, raw2 = sign_hmac_sha256_then_rsa_base64(
                {k: v for k, v in payload_retry.items() if k != "sign"},
                sign_key=sign_key,
                rsa_private_key_pem=settings.USD_PAYOUT_RSA_PRIVATE_KEY,
                hex_key=True,
            )
            payload_retry["sign"] = sign2
            logger.warning(
                "USD_PAYOUT singleOrder retry (hex_key): withdrawal=%s order=%s raw=%s signA=%s sign=%s",
                wd.id,
                mer_order_no,
                raw2,
                sign_a2[:10],
                sign2[:10],
            )
            try:
                resp_retry = send_single_order(settings.USD_PAYOUT_API_URL, payload_retry)
                resp_data = resp_retry or resp_data
                payload = payload_retry
            except Exception:
                pass

        trace.response_payload = resp_data
        trace.save(update_fields=["response_payload"])

        code = str(resp_data.get("code") or "").strip()
        data = resp_data.get("data") if isinstance(resp_data.get("data"), dict) else {}
        try:
            status_int = int(data.get("status")) if data.get("status") is not None else None
        except Exception:
            status_int = None

        if code in ("200", "500"):
            if status_int == 7:
                wd.status = "COMPLETED"
            elif status_int in (6, 8, 2):
                wd.status = "REJECTED"
            else:
                wd.status = "PROCESSING"
            wd.save(update_fields=["status"])
            return Response({"gateway": resp_data, "submitted_params": {k: v for k, v in payload.items() if k != "sign"}}, status=status.HTTP_200_OK)

        wd.status = "REJECTED"
        wd.save(update_fields=["status"])
        return Response({"detail": resp_data.get("msg") or "Payout gagal", "gateway": resp_data}, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name="dispatch")
class UsdPayoutCallbackView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'gateway_callback'

    @extend_schema(summary="Callback USD payout gateway untuk update status withdraw")
    def post(self, request, *args, **kwargs):
        payload = request.data if isinstance(request.data, dict) else {}
        order_num = payload.get("merOrderNo") or payload.get("mer_order_no") or ""
        if not order_num:
            return HttpResponse("SUCCESS", content_type="text/plain")

        try:
            trx = Transaction.objects.filter(trx_id=order_num).first()
        except Exception:
            trx = None
        if not trx:
            return HttpResponse("SUCCESS", content_type="text/plain")

        withdrawal = Withdrawal.objects.filter(transaction=trx).first()
        if not withdrawal:
            return HttpResponse("SUCCESS", content_type="text/plain")

        provided_sign = str(payload.get("sign") or "").strip()
        signature_valid = True
        if getattr(settings, "USD_PAYOUT_SIGN_KEY", "") and provided_sign:
            sign_key = (settings.USD_PAYOUT_SIGN_KEY or "").strip()
            expected, _raw = sign_hmac_sha256(payload, sign_key, hex_key=False)
            if expected.lower() != provided_sign.lower():
                key_is_hex = len(sign_key) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in sign_key) and bool(sign_key)
                if key_is_hex:
                    expected2, _raw2 = sign_hmac_sha256(payload, sign_key, hex_key=True)
                    if expected2.lower() != provided_sign.lower():
                        signature_valid = False
                else:
                    signature_valid = False

        trace = UsdPayoutWithdrawal.objects.filter(withdrawal=withdrawal).first()
        if trace:
            trace.response_payload = {"callback": payload, "_signature_valid": signature_valid}
            trace.save(update_fields=["response_payload"])

        if not signature_valid:
            logger.warning("USD_PAYOUT callback invalid signature: order=%s payload=%s", order_num, json.dumps(payload, ensure_ascii=False))
            return HttpResponse("SUCCESS", content_type="text/plain")

        try:
            status_int = int(payload.get("status"))
        except Exception:
            status_int = None

        if status_int == 7:
            withdrawal.status = "COMPLETED"
            withdrawal.save(update_fields=["status"])
        elif status_int in (2, 8, 6):
            withdrawal.status = "REJECTED"
            withdrawal.save(update_fields=["status"])
        else:
            withdrawal.status = "PROCESSING"
            withdrawal.save(update_fields=["status"])

        return HttpResponse("SUCCESS", content_type="text/plain")


class JayapayPhPayoutInitiateView(APIView):
    permission_classes = [permissions.IsAdminUser]
    throttle_scope = 'withdraw_admin_initiate'

    @extend_schema(
        summary="Inisiasi withdraw otomatis via Jayapay Philippines (admin)",
        parameters=[
            OpenApiParameter(name="pk", description="Withdrawal ID", required=True, type=int),
        ],
        request={
            "application/json": {
                "type": "object",
                "properties": {
                    "bankCode": {"type": "string", "description": "PH bank/wallet code (lihat /api/withdrawals/jayapay-ph/banks/)"},
                    "bankCard": {"type": "string", "description": "Account/wallet number"},
                    "accountName": {"type": "string", "description": "Account name"},
                    "amount": {"type": "string", "description": "Optional override amount"},
                    "description": {"type": "string", "description": "Optional description"},
                    "feeType": {"type": "integer", "enum": [0, 1], "description": "0=deduct; 1=separate"},
                },
                "required": ["bankCode", "bankCard", "accountName"],
            }
        },
    )
    def post(self, request, pk: int):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.jayapay_ph_payout_enabled)
        mch_no = (gs.jayapay_ph_payout_mch_no or "").strip() if gs else ""
        private_key = (gs.jayapay_ph_payout_private_key or "").strip() if gs else ""
        api_url = (gs.jayapay_ph_payout_api_url or "").strip() if gs else ""
        app_domain = _resolve_app_domain(gs)

        if not enabled:
            return Response({"detail": "Jayapay PH payout tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not mch_no or not private_key:
            return Response({"detail": "Konfigurasi Jayapay PH payout belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({"detail": "Konfigurasi domain untuk callback belum diisi"}, status=status.HTTP_400_BAD_REQUEST)

        api_url = api_url or "https://global-ph-openapi.jayapayment.com/ph/disbursement/cash"

        try:
            wd = Withdrawal.objects.select_related("user", "transaction").get(pk=pk)
        except Withdrawal.DoesNotExist:
            return Response({"detail": "Withdrawal tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)

        if wd.status not in ("PENDING", "PROCESSING"):
            return Response({"detail": "Status withdrawal tidak valid untuk inisiasi"}, status=status.HTTP_400_BAD_REQUEST)

        bank_code = (request.data.get("bankCode") or "").strip().upper()
        bank_code = bank_code.replace("-", "_").replace(" ", "_")
        bank_card = (request.data.get("bankCard") or "").strip()
        account_name = (request.data.get("accountName") or "").strip()
        if not bank_code or not bank_card or not account_name:
            return Response({"detail": "bankCode, bankCard, accountName wajib diisi"}, status=status.HTTP_400_BAD_REQUEST)

        allowed_bank_codes = {item.get("bankCode") for item in (JAYAPAY_PH_PAYOUT_BANKS or []) if item.get("bankCode")}
        if "PAY_MAYA" in allowed_bank_codes and bank_code == "MAYA":
            bank_code = "PAY_MAYA"
        if "PAY_MAYA" in allowed_bank_codes and bank_code == "MAYA_WAP":
            bank_code = "MAYA_WAP"
        if allowed_bank_codes and bank_code not in allowed_bank_codes:
            return Response({"detail": "bankCode tidak valid"}, status=status.HTTP_400_BAD_REQUEST)

        fee_type_raw = request.data.get("feeType")
        try:
            fee_type = int(fee_type_raw) if fee_type_raw is not None else int(getattr(gs, "jayapay_ph_payout_fee_type", 1) or 1)
        except Exception:
            fee_type = int(getattr(gs, "jayapay_ph_payout_fee_type", 1) or 1)
        if fee_type not in (0, 1):
            fee_type = 1

        amount_raw = request.data.get("amount")
        try:
            amount = Decimal(str(amount_raw)).quantize(Decimal("0.01")) if amount_raw is not None else Decimal(str(wd.net_amount or wd.amount)).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError, TypeError):
            return Response({"detail": "amount tidak valid"}, status=status.HTTP_400_BAD_REQUEST)
        if amount <= 0:
            return Response({"detail": "amount tidak valid"}, status=status.HTTP_400_BAD_REQUEST)

        order_num = getattr(getattr(wd, "transaction", None), "trx_id", None) or f"WD-PH-{wd.id}-{int(pytime.time()*1000)}"
        if len(order_num) > 50:
            order_num = f"WD-PH-{wd.id}-{int(pytime.time()*1000)}"

        timestamp_ms = str(int(pytime.time() * 1000))
        notify_url = f"https://{app_domain}/api/withdrawals/jayapay-ph/callback/"
        description = (request.data.get("description") or wd.note or f"Withdrawal #{wd.id}").strip()[:255]

        amount_value = int(amount) if amount == amount.to_integral() else float(amount)
        payload = {
            "mchNo": mch_no,
            "orderNum": order_num,
            "amount": amount_value,
            "bankCode": bank_code,
            "bankCard": bank_card,
            "accountName": account_name,
            "description": description,
            "feeType": fee_type,
            "downNotifyUrl": notify_url,
            "timestamp": timestamp_ms,
        }

        try:
            payload["sign"] = sign_params_legacy(payload, private_key)
        except Exception as e:
            return Response({"detail": f"Gagal membuat signature: {e}"}, status=status.HTTP_400_BAD_REQUEST)

        trace, _ = JayapayPhPayoutWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
        if trace and not trace.request_params:
            trace.request_params = payload
            trace.save(update_fields=["request_params"])

        try:
            logger.info(
                "Jayapay PH payout initiate: withdrawal_id=%s orderNum=%s payload=%s",
                wd.pk,
                order_num,
                json.dumps({k: v for k, v in payload.items() if k != "sign"}, ensure_ascii=False),
            )
        except Exception:
            logger.info("Jayapay PH payout initiate: withdrawal_id=%s orderNum=%s", wd.pk, order_num)

        try:
            resp = requests.post(api_url, json=payload, timeout=30)
            resp_data = resp.json() if resp.content else {}
        except Exception as e:
            wd.status = "PROCESSING"
            wd.save(update_fields=["status"])
            trace.response_payload = {"error": str(e)}
            trace.save(update_fields=["response_payload"])
            return Response({"detail": f"Gagal menghubungi gateway: {e}"}, status=status.HTTP_502_BAD_GATEWAY)

        try:
            logger.info(
                "Jayapay PH payout response: withdrawal_id=%s orderNum=%s http_status=%s body=%s",
                wd.pk,
                order_num,
                getattr(resp, "status_code", None),
                json.dumps(resp_data, ensure_ascii=False),
            )
        except Exception:
            logger.info("Jayapay PH payout response: withdrawal_id=%s orderNum=%s", wd.pk, order_num)

        trace.response_payload = resp_data
        trace.save(update_fields=["response_payload"])

        success = bool(resp_data.get("success")) and str(resp_data.get("code") or "").strip() == "9999"
        if success:
            wd.status = "PROCESSING"
            wd.save(update_fields=["status"])
            return Response({"gateway": resp_data, "submitted_params": {k: v for k, v in payload.items() if k != "sign"}}, status=status.HTTP_200_OK)

        wd.status = "REJECTED"
        wd.save(update_fields=["status"])
        return Response({"detail": resp_data.get("msg") or "Payout gagal", "gateway": resp_data}, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name="dispatch")
class JayapayPhPayoutCallbackView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = 'gateway_callback'

    @extend_schema(summary="Callback Jayapay Philippines untuk update status withdraw")
    def post(self, request, *args, **kwargs):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        payload = request.data if isinstance(request.data, dict) else {}
        logger.info(f"Jayapay PH Payout callback received: {payload}")

        order_num = str(payload.get("orderNum") or "").strip()
        if not order_num:
            return HttpResponse("SUCCESS", content_type="text/plain")

        trx = Transaction.objects.filter(trx_id=order_num).first()
        withdrawal = Withdrawal.objects.filter(transaction=trx).first() if trx else None
        if not withdrawal and order_num.startswith("WD-PH-"):
            try:
                parts = order_num.split("-", 3)
                wid = int(parts[2]) if len(parts) > 2 else None
            except Exception:
                wid = None
            if wid:
                withdrawal = Withdrawal.objects.filter(pk=wid).first()
        if not withdrawal:
            return HttpResponse("SUCCESS", content_type="text/plain")

        trace = JayapayPhPayoutWithdrawal.objects.filter(withdrawal=withdrawal).first()

        signature_valid = False
        try:
            public_key = (gs.jayapay_ph_payout_public_key or "").strip() if gs else ""
            if public_key:
                signature_valid = verify_jayapay_signature(payload, public_key, signature_field="sign")
                logger.info("Jayapay PH payout callback signature_valid=%s orderNum=%s", signature_valid, order_num)
            else:
                logger.warning("Jayapay PH payout callback: public key missing orderNum=%s", order_num)
        except Exception as e:
            logger.error("Jayapay PH payout callback: signature verification error=%s orderNum=%s", e, order_num)
            signature_valid = False

        if trace:
            trace.response_payload = {"callback": payload, "_signature_valid": signature_valid}
            trace.save(update_fields=["response_payload"])

        if not signature_valid:
            logger.warning("Jayapay PH payout callback: invalid signature orderNum=%s", order_num)
            return HttpResponse("SUCCESS", content_type="text/plain")

        try:
            status_int = int(payload.get("status")) if payload.get("status") is not None else None
        except Exception:
            status_int = None

        if status_int == 2:
            withdrawal.status = "COMPLETED"
            withdrawal.save(update_fields=["status"])
        elif status_int in (4, 6, 8):
            withdrawal.status = "REJECTED"
            withdrawal.save(update_fields=["status"])
        else:
            withdrawal.status = "PROCESSING"
            withdrawal.save(update_fields=["status"])

        logger.info("Jayapay PH payout callback: orderNum=%s status_int=%s mapped=%s", order_num, status_int, withdrawal.status)
        return HttpResponse("SUCCESS", content_type="text/plain")


class JayapayPhPayoutBanksView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(summary="Daftar bank/wallet code Jayapay Philippines (Pay-Out)")
    def get(self, request):
        q = (request.query_params.get("q") or "").strip().lower()
        items = list(JAYAPAY_PH_PAYOUT_BANKS or [])
        if q:
            items = [
                it for it in items
                if q in str(it.get("bankCode") or "").lower() or q in str(it.get("bankName") or "").lower()
            ]
        return Response({"count": len(items), "results": items})


def _atpay_store_trace(trace: AtpayWithdrawal | None, payload: dict):
    if not trace:
        return
    current = trace.response_payload if isinstance(trace.response_payload, dict) else {}
    current.update(payload or {})
    trace.response_payload = current
    trace.save(update_fields=["response_payload"])


class AtpayPayoutInitiateView(APIView):
    permission_classes = [permissions.IsAdminUser]
    throttle_scope = "withdraw_admin_initiate"

    @extend_schema(summary="Inisiasi withdraw otomatis via ATPAY (admin)")
    def post(self, request, pk: int):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.atpay_payout_enabled)
        api_url = (gs.atpay_payout_api_url or "").strip() if gs else ""
        merchant_no = (gs.atpay_payout_merchant_no or "").strip() if gs else ""
        sign_type = atpay_normalize_sign_type((gs.atpay_payout_sign_type or "MD5").strip() if gs else "MD5")
        secret_key = (gs.atpay_payout_secret_key or "").strip() if gs else ""
        private_key = (gs.atpay_payout_private_key or "").strip() if gs else ""
        public_key = (gs.atpay_payout_public_key or "").strip() if gs else ""
        app_domain = _resolve_app_domain(gs)

        if not enabled:
            return Response({"detail": "ATPAY payout tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not api_url or not merchant_no:
            return Response({"detail": "Konfigurasi ATPAY payout belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)
        if sign_type == "MD5" and not secret_key:
            return Response({"detail": "Secret key ATPAY payout belum diisi"}, status=status.HTTP_400_BAD_REQUEST)
        if sign_type == "MD5withRsa" and (not private_key or not public_key):
            return Response({"detail": "Private/Public key ATPAY payout belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({"detail": "Konfigurasi domain untuk callback belum diisi"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            wd = Withdrawal.objects.select_related("user", "bank_account__bank", "transaction").get(pk=pk)
        except Withdrawal.DoesNotExist:
            return Response({"detail": "Withdrawal tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)

        if wd.status not in ("PENDING", "PROCESSING"):
            return Response({"detail": "Status withdrawal tidak valid untuk inisiasi"}, status=status.HTTP_400_BAD_REQUEST)

        trade_account = (request.data.get("tradeAccount") or getattr(wd.bank_account, "account_name", "") or "").strip()
        trade_number = (request.data.get("tradeNumber") or getattr(wd.bank_account, "account_number", "") or "").strip()
        bank_code = (request.data.get("bankCode") or getattr(getattr(wd, "bank_account", None), "bank", None) and wd.bank_account.bank.code or "").strip()
        mobile = (request.data.get("mobile") or getattr(wd.bank_account, "phone", "") or getattr(wd.user, "phone", "") or "").strip()
        email = (request.data.get("email") or getattr(wd.user, "email", "") or f"user{wd.user_id}@example.com").strip()
        identity = (request.data.get("identity") or "").strip()
        attach = (request.data.get("attach") or f"withdrawal:{wd.pk}").strip()
        ifsc = (request.data.get("ifsc") or "").strip()
        pix = (request.data.get("pix") or "").strip()
        pix_type = (request.data.get("pixType") or "").strip()

        if not trade_account or not trade_number:
            return Response({"detail": "tradeAccount dan tradeNumber wajib diisi"}, status=status.HTTP_400_BAD_REQUEST)

        amount_raw = request.data.get("amount")
        try:
            amount = atpay_normalize_amount(amount_raw) if amount_raw is not None else atpay_normalize_amount(wd.net_amount or wd.amount)
            if amount <= 0:
                raise InvalidOperation()
        except Exception:
            return Response({"detail": "amount tidak valid"}, status=status.HTTP_400_BAD_REQUEST)

        out_trade_sn = getattr(getattr(wd, "transaction", None), "trx_id", None) or f"WAT{wd.pk}{int(pytime.time())}"
        payload = atpay_build_payout_payload(
            merchant_no=merchant_no,
            out_trade_sn=out_trade_sn[:50],
            amount=amount,
            trade_account=trade_account,
            trade_number=trade_number,
            bank_code=bank_code,
            mobile=mobile,
            email=email,
            identity=identity,
            attach=attach,
            pix=pix,
            pix_type=pix_type,
            ifsc=ifsc,
            notify_url=f"https://{app_domain}/api/withdrawals/atpay/callback/",
            sign_type=sign_type,
        )
        payload["sign"] = atpay_sign_payload(payload, sign_type, secret_key=secret_key, private_key=private_key)

        trace, _ = AtpayWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
        if trace and not trace.request_params:
            trace.request_params = payload
            trace.save(update_fields=["request_params"])

        response_payload = atpay_post_json(f"{api_url.rstrip('/')}/gw-api/payout/create", payload)
        if response_payload.get("sign"):
            response_payload["_sign_valid"] = atpay_verify_payload(
                response_payload,
                response_payload.get("sign_type") or sign_type,
                secret_key=secret_key,
                public_key=public_key,
            )
        _atpay_store_trace(trace, {"initiate": response_payload})

        if str(response_payload.get("code") or "").strip() == "100":
            wd.status = "PROCESSING"
            wd.save(update_fields=["status"])
            return Response({"gateway": response_payload, "provider_data": response_payload.get("data") or {}}, status=status.HTTP_200_OK)

        wd.status = "REJECTED"
        wd.save(update_fields=["status"])
        return Response({"detail": response_payload.get("message") or "Payout gagal", "gateway": response_payload}, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name="dispatch")
class AtpayPayoutCallbackView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "gateway_callback"

    @extend_schema(summary="Callback ATPAY untuk update status withdraw")
    def post(self, request, *args, **kwargs):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        secret_key = (gs.atpay_payout_secret_key or "").strip() if gs else ""
        public_key = (gs.atpay_payout_public_key or "").strip() if gs else ""
        payload = request.data if isinstance(request.data, dict) else {}
        order_num = str(payload.get("out_trade_sn") or "").strip()
        if not order_num:
            return HttpResponse("success", content_type="text/plain")

        trx = Transaction.objects.filter(trx_id=order_num).first()
        withdrawal = Withdrawal.objects.filter(transaction=trx).first() if trx else None
        if not withdrawal:
            return HttpResponse("success", content_type="text/plain")

        trace = AtpayWithdrawal.objects.filter(withdrawal=withdrawal).first()
        sign_type = payload.get("sign_type") or (gs.atpay_payout_sign_type if gs else "MD5")
        signature_valid = atpay_verify_payload(payload, sign_type, secret_key=secret_key, public_key=public_key)
        _atpay_store_trace(trace, {"callback": {**payload, "_sign_valid": signature_valid}})
        if not signature_valid:
            return HttpResponse("success", content_type="text/plain")

        mapped_status = atpay_map_payout_trade_status(payload.get("trade_status"))
        if mapped_status:
            withdrawal.status = mapped_status
            withdrawal.save(update_fields=["status"])
        return HttpResponse("success", content_type="text/plain")


class AtpayPayoutQueryView(APIView):
    permission_classes = [permissions.IsAdminUser]
    throttle_scope = "withdraw_admin_initiate"

    @extend_schema(summary="Query status withdraw ATPAY")
    def post(self, request, pk: int):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.atpay_payout_enabled)
        api_url = (gs.atpay_payout_api_url or "").strip() if gs else ""
        merchant_no = (gs.atpay_payout_merchant_no or "").strip() if gs else ""
        sign_type = atpay_normalize_sign_type((gs.atpay_payout_sign_type or "MD5").strip() if gs else "MD5")
        secret_key = (gs.atpay_payout_secret_key or "").strip() if gs else ""
        private_key = (gs.atpay_payout_private_key or "").strip() if gs else ""
        public_key = (gs.atpay_payout_public_key or "").strip() if gs else ""
        if not enabled:
            return Response({"detail": "ATPAY payout tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not api_url or not merchant_no:
            return Response({"detail": "Konfigurasi ATPAY payout belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            wd = Withdrawal.objects.select_related("transaction").get(pk=pk)
        except Withdrawal.DoesNotExist:
            return Response({"detail": "Withdrawal tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)

        trace = AtpayWithdrawal.objects.filter(withdrawal=wd).first()
        order_sn = (request.data.get("orderSn") or "").strip()
        out_trade_sn = (request.data.get("outTradeSn") or getattr(getattr(wd, "transaction", None), "trx_id", None) or "").strip()
        if not order_sn and trace and isinstance(trace.response_payload, dict):
            initiate_payload = trace.response_payload.get("initiate")
            initiate_data = initiate_payload.get("data") if isinstance(initiate_payload, dict) and isinstance(initiate_payload.get("data"), dict) else {}
            order_sn = str(initiate_data.get("order_sn") or "").strip()
        if not out_trade_sn or not order_sn:
            return Response({"detail": "outTradeSn dan orderSn wajib tersedia"}, status=status.HTTP_400_BAD_REQUEST)

        payload = atpay_build_payout_query_payload(
            merchant_no=merchant_no,
            out_trade_sn=out_trade_sn,
            order_sn=order_sn,
            sign_type=sign_type,
        )
        payload["sign"] = atpay_sign_payload(payload, sign_type, secret_key=secret_key, private_key=private_key)

        response_payload = atpay_post_json(f"{api_url.rstrip('/')}/gw-api/payout/query", payload)
        if response_payload.get("sign"):
            response_payload["_sign_valid"] = atpay_verify_payload(
                response_payload,
                response_payload.get("sign_type") or sign_type,
                secret_key=secret_key,
                public_key=public_key,
            )
        _atpay_store_trace(trace, {"query": response_payload})

        data = response_payload.get("data") if isinstance(response_payload.get("data"), dict) else {}
        if str(response_payload.get("code") or "").strip() == "100":
            mapped_status = atpay_map_payout_trade_status(data.get("trade_status"))
            if mapped_status:
                wd.status = mapped_status
                wd.save(update_fields=["status"])

        return Response({"local_status": wd.status, "gateway": response_payload, "provider_data": data}, status=status.HTTP_200_OK)


class AtpayPayoutBanksView(APIView):
    permission_classes = [permissions.IsAdminUser]
    throttle_scope = "withdraw_admin_initiate"

    @extend_schema(summary="Ambil daftar bank code ATPAY untuk admin")
    def get(self, request):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.atpay_payout_enabled)
        api_url = (gs.atpay_payout_api_url or "").strip() if gs else ""
        merchant_no = (gs.atpay_payout_merchant_no or "").strip() if gs else ""
        sign_type = atpay_normalize_sign_type((gs.atpay_payout_sign_type or "MD5").strip() if gs else "MD5")
        secret_key = (gs.atpay_payout_secret_key or "").strip() if gs else ""
        private_key = (gs.atpay_payout_private_key or "").strip() if gs else ""

        if not enabled:
            return Response({"detail": "ATPAY payout tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not api_url or not merchant_no:
            return Response({"detail": "Konfigurasi ATPAY payout belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)

        payload = atpay_build_bank_code_payload(merchant_no=merchant_no, sign_type=sign_type)
        payload["sign"] = atpay_sign_payload(payload, sign_type, secret_key=secret_key, private_key=private_key)
        response_payload = atpay_post_json(f"{api_url.rstrip('/')}/gw-api/bank-code", payload)
        items = response_payload.get("data") if isinstance(response_payload.get("data"), list) else []
        results = [
            {"bank_code": str(item.get("bank_code") or "").strip(), "bank_name": str(item.get("bank_name") or "").strip()}
            for item in items
            if str(item.get("bank_code") or "").strip()
        ]
        return Response({"count": len(results), "results": results, "provider": response_payload}, status=status.HTTP_200_OK)


class PPayProsPayoutInitiateView(APIView):
    permission_classes = [permissions.IsAdminUser]
    throttle_scope = "withdraw_admin_initiate"

    @extend_schema(summary="Inisiasi withdraw otomatis via PPay Pros (admin)")
    def post(self, request, pk: int):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.ppaypros_payout_enabled)
        api_url = (gs.ppaypros_payout_api_url or "").strip() if gs else ""
        mch_no = (gs.ppaypros_payout_mch_no or "").strip() if gs else ""
        app_id = (gs.ppaypros_payout_app_id or "").strip() if gs else ""
        private_key = (gs.ppaypros_payout_private_key or "").strip() if gs else ""
        entry_type_default = (gs.ppaypros_payout_entry_type or "BANK_CARD").strip() if gs else "BANK_CARD"
        app_domain = _resolve_app_domain(gs)

        if not enabled:
            return Response({"detail": "PPay Pros payout tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not api_url or not mch_no or not app_id or not private_key:
            return Response({"detail": "Konfigurasi PPay Pros payout belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({"detail": "Konfigurasi domain untuk callback belum diisi"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            wd = Withdrawal.objects.select_related("user", "bank_account__bank", "transaction").get(pk=pk)
        except Withdrawal.DoesNotExist:
            return Response({"detail": "Withdrawal tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)

        if wd.status not in ("PENDING", "PROCESSING"):
            return Response({"detail": "Status withdrawal tidak valid untuk inisiasi"}, status=status.HTTP_400_BAD_REQUEST)

        entry_type = (request.data.get("entryType") or entry_type_default or "BANK_CARD").strip().upper()
        account_code = (request.data.get("accountCode") or getattr(getattr(wd, "bank_account", None), "bank", None) and wd.bank_account.bank.code or "").strip()
        account_no = (request.data.get("accountNo") or getattr(wd.bank_account, "account_number", "") or "").strip()
        account_name = (request.data.get("accountName") or getattr(wd.bank_account, "account_name", "") or "").strip()
        account_email = (request.data.get("accountEmail") or getattr(wd.user, "email", "") or f"user{wd.user_id}@example.com").strip()
        account_phone = (request.data.get("accountPhone") or getattr(wd.bank_account, "phone", "") or getattr(wd.user, "phone", "") or "").strip()
        if not account_code or not account_no or not account_name:
            return Response({"detail": "accountCode, accountNo, accountName wajib diisi"}, status=status.HTTP_400_BAD_REQUEST)

        amount_raw = request.data.get("amount")
        try:
            amount = ppaypros_normalize_amount(amount_raw) if amount_raw is not None else ppaypros_normalize_amount(wd.net_amount or wd.amount)
            if amount <= 0:
                raise InvalidOperation()
        except Exception:
            return Response({"detail": "amount tidak valid"}, status=status.HTTP_400_BAD_REQUEST)

        mch_order_no = getattr(getattr(wd, "transaction", None), "trx_id", None) or f"WPP{wd.pk}{int(pytime.time())}"
        notify_url = f"https://{app_domain}/api/withdrawals/ppaypros/callback/"
        bank_name = getattr(getattr(wd, "bank_account", None), "bank", None)
        payload = ppaypros_build_payout_payload(
            mch_no=mch_no,
            app_id=app_id,
            mch_order_no=mch_order_no,
            amount_points=ppaypros_amount_to_points(amount),
            entry_type=entry_type,
            account_no=account_no,
            account_code=account_code,
            account_name=account_name,
            account_email=account_email[:64],
            account_phone=account_phone[:16],
            notify_url=notify_url,
            bank_name=getattr(bank_name, "name", "")[:64],
            ext_param=f"withdrawal:{wd.pk}",
        )
        payload["sign"] = ppaypros_generate_sign(payload, private_key)

        trace, _ = PPayProsWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
        if trace and not trace.request_params:
            trace.request_params = payload
            trace.save(update_fields=["request_params"])

        response_payload = ppaypros_post_json(f"{api_url.rstrip('/')}/api/payout/pay", payload)
        if response_payload.get("sign"):
            response_payload["_sign_valid"] = ppaypros_verify_sign(response_payload, private_key)
        _ppaypros_store_trace(trace, {"initiate": response_payload})

        if str(response_payload.get("code")) == "0":
            data = ppaypros_parse_data_field(response_payload)
            mapped_status = ppaypros_map_payout_state(data.get("state"))
            if mapped_status:
                wd.status = mapped_status
                wd.save(update_fields=["status"])
            else:
                wd.status = "PROCESSING"
                wd.save(update_fields=["status"])
            return Response({"gateway": response_payload, "provider_data": data}, status=status.HTTP_200_OK)

        wd.status = "REJECTED"
        wd.save(update_fields=["status"])
        return Response({"detail": response_payload.get("msg") or "Payout gagal", "gateway": response_payload}, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name="dispatch")
class PPayProsPayoutCallbackView(generics.GenericAPIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "gateway_callback"

    @extend_schema(summary="Callback PPay Pros untuk update status withdraw")
    def post(self, request, *args, **kwargs):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        private_key = (gs.ppaypros_payout_private_key or "").strip() if gs else ""
        payload = _ppaypros_collect_payload(request)
        order_num = str(payload.get("mchOrderNo") or "").strip()
        if not order_num:
            return HttpResponse("success", content_type="text/plain")

        trx = Transaction.objects.filter(trx_id=order_num).first()
        withdrawal = Withdrawal.objects.filter(transaction=trx).first() if trx else None
        if not withdrawal:
            ext_param = str(payload.get("extParam") or "").strip().lower()
            if ext_param.startswith("withdrawal:"):
                try:
                    withdrawal_id = int(ext_param.split(":", 1)[1])
                except Exception:
                    withdrawal_id = None
                if withdrawal_id:
                    withdrawal = Withdrawal.objects.filter(pk=withdrawal_id).first()
        if not withdrawal:
            return HttpResponse("success", content_type="text/plain")

        trace = PPayProsWithdrawal.objects.filter(withdrawal=withdrawal).first()
        signature_valid = ppaypros_verify_sign(payload, private_key) if private_key else False
        _ppaypros_store_trace(trace, {"callback": {**payload, "_sign_valid": signature_valid}})
        if not signature_valid:
            return HttpResponse("success", content_type="text/plain")

        mapped_status = ppaypros_map_payout_state(payload.get("state"))
        if mapped_status:
            withdrawal.status = mapped_status
            withdrawal.save(update_fields=["status"])
        return HttpResponse("success", content_type="text/plain")


class PPayProsPayoutQueryView(APIView):
    permission_classes = [permissions.IsAdminUser]
    throttle_scope = "withdraw_admin_initiate"

    @extend_schema(summary="Query status withdraw PPay Pros")
    def post(self, request, pk: int):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.ppaypros_payout_enabled)
        api_url = (gs.ppaypros_payout_api_url or "").strip() if gs else ""
        mch_no = (gs.ppaypros_payout_mch_no or "").strip() if gs else ""
        app_id = (gs.ppaypros_payout_app_id or "").strip() if gs else ""
        private_key = (gs.ppaypros_payout_private_key or "").strip() if gs else ""
        if not enabled:
            return Response({"detail": "PPay Pros payout tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not api_url or not mch_no or not app_id or not private_key:
            return Response({"detail": "Konfigurasi PPay Pros payout belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            wd = Withdrawal.objects.select_related("transaction").get(pk=pk)
        except Withdrawal.DoesNotExist:
            return Response({"detail": "Withdrawal tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)

        trace = PPayProsWithdrawal.objects.filter(withdrawal=wd).first()
        transfer_id = (request.data.get("transferId") or "").strip()
        mch_order_no = (request.data.get("mchOrderNo") or getattr(getattr(wd, "transaction", None), "trx_id", None) or "").strip()
        if not transfer_id and trace and isinstance(trace.response_payload, dict):
            initiate_payload = trace.response_payload.get("initiate")
            initiate_data = ppaypros_parse_data_field(initiate_payload) if isinstance(initiate_payload, dict) else {}
            transfer_id = str(initiate_data.get("transferId") or "").strip()

        payload = {"mchNo": mch_no, "appId": app_id}
        if transfer_id:
            payload["transferId"] = transfer_id
        if mch_order_no:
            payload["mchOrderNo"] = mch_order_no
        if "transferId" not in payload and "mchOrderNo" not in payload:
            return Response({"detail": "transferId atau mchOrderNo wajib tersedia"}, status=status.HTTP_400_BAD_REQUEST)
        payload["sign"] = ppaypros_generate_sign(payload, private_key)

        response_payload = ppaypros_post_json(f"{api_url.rstrip('/')}/api/payout/query", payload)
        if response_payload.get("sign"):
            response_payload["_sign_valid"] = ppaypros_verify_sign(response_payload, private_key)
        _ppaypros_store_trace(trace, {"query": response_payload})

        data = ppaypros_parse_data_field(response_payload)
        if str(response_payload.get("code")) == "0":
            mapped_status = ppaypros_map_payout_state(data.get("state"))
            if mapped_status:
                wd.status = mapped_status
                wd.save(update_fields=["status"])

        return Response({"local_status": wd.status, "gateway": response_payload, "provider_data": data}, status=status.HTTP_200_OK)


class WithdrawalTransactionsListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    throttle_scope = 'transactions'

    @extend_schema(
        summary="Daftar transaksi Withdraw",
        parameters=[
            OpenApiParameter(name='status', type=str, description='Filter status transaksi'),
            OpenApiParameter(name='wallet_type', type=str, description='Filter wallet (BALANCE/BALANCE_DEPOSIT)'),
            OpenApiParameter(name='start_date', type=str, description='Tanggal mulai (YYYY-MM-DD)'),
            OpenApiParameter(name='end_date', type=str, description='Tanggal akhir (YYYY-MM-DD)'),
            OpenApiParameter(name='order_num', type=str, description='Filter berdasarkan nomor order (trx_id)'),
            OpenApiParameter(name='bank_account_id', type=int, description='Filter berdasarkan ID rekening pengguna'),
            OpenApiParameter(name='page', type=int, description='A page number within the paginated result set.'),
        ],
        responses=TransactionSerializer(many=True),
        description='Mengambil daftar transaksi bertipe WITHDRAW untuk user saat ini atau semua jika admin.'
    )
    def get(self, request):
        # Base queryset: admin melihat semua; user melihat miliknya atau referral
        if request.user.is_staff:
            queryset = Transaction.objects.all()
        else:
            queryset = Transaction.objects.filter(Q(user=request.user) | Q(upline_user=request.user))

        queryset = queryset.select_related('user', 'product', 'upline_user').prefetch_related(
            'related_withdrawal',
            'related_withdrawal__bank_account',
            'related_withdrawal__bank_account__bank',
            'related_withdrawal__withdrawal_service',
        )

        # Hanya transaksi bertipe WITHDRAW
        queryset = queryset.filter(type='WITHDRAW')

        # Query params
        status_param = request.query_params.get('status')
        wallet_type = request.query_params.get('wallet_type')
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        order_num = request.query_params.get('order_num')
        bank_account_id = request.query_params.get('bank_account_id')

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
        if order_num:
            queryset = queryset.filter(trx_id=order_num)

        # Filter melalui relasi Withdrawal (bank_account_id, atau jika order_num dipakai via relasi)
        if bank_account_id:
            wd_qs = Withdrawal.objects.all() if request.user.is_staff else Withdrawal.objects.filter(user=request.user)
            wd_qs = wd_qs.filter(bank_account_id=bank_account_id)
            queryset = queryset.filter(id__in=wd_qs.values_list('transaction_id', flat=True))

        queryset = queryset.order_by('-created_at')
        paginator = PageNumberPagination()
        paginator.page_size = 20
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = TransactionSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class BankPayPayoutInitiateView(APIView):
    permission_classes = [permissions.IsAdminUser]
    throttle_scope = "withdraw_admin_initiate"

    @extend_schema(summary="Inisiasi withdraw via BankPay (admin)")
    def post(self, request, pk: int):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.bankpay_payout_enabled)
        api_url = (gs.bankpay_payout_api_url or "https://pay.bankpay.cfd").strip() if gs else ""
        member_id = (gs.bankpay_payout_member_id or "").strip() if gs else ""
        key = (gs.bankpay_payout_key or "").strip() if gs else ""
        app_domain = _resolve_app_domain(gs)

        if not enabled:
            return Response({"detail": "BankPay payout tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not api_url or not member_id or not key:
            return Response({"detail": "Konfigurasi BankPay payout belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)
        if not app_domain:
            return Response({"detail": "Konfigurasi domain untuk callback belum diisi"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            wd = Withdrawal.objects.select_related("user", "bank_account__bank", "transaction").get(pk=pk)
        except Withdrawal.DoesNotExist:
            return Response({"detail": "Withdrawal tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)

        if wd.status not in ("PENDING", "PROCESSING"):
            return Response({"detail": "Status withdrawal tidak valid untuk inisiasi"}, status=status.HTTP_400_BAD_REQUEST)

        account_no = getattr(wd.bank_account, "account_number", "") or ""
        account_name = getattr(wd.bank_account, "account_name", "") or ""
        bank_name = getattr(getattr(wd, "bank_account", None), "bank", None)
        bank_name_str = getattr(bank_name, "name", "") or ""
        bank_code = getattr(bank_name, "code", "") or ""

        amount_raw = request.data.get("amount")
        try:
            amount = ppaypros_normalize_amount(amount_raw) if amount_raw is not None else ppaypros_normalize_amount(wd.net_amount or wd.amount)
            if amount <= 0:
                raise InvalidOperation()
        except Exception:
            return Response({"detail": "amount tidak valid"}, status=status.HTTP_400_BAD_REQUEST)

        order_id = getattr(getattr(wd, "transaction", None), "trx_id", None) or f"WBP{wd.pk}{int(pytime.time())}"
        notify_url = f"https://{app_domain}/api/withdrawals/bankpay/callback/"
        pay_amount = f"{amount:.2f}"

        payload = bankpay_build_payout_payload(
            member_id=member_id,
            order_id=order_id,
            amount=pay_amount,
            bankcode="bank",
            notify_url=notify_url,
            mobile=getattr(wd.user, "phone", "") or "",
            email=getattr(wd.user, "email", "") or f"user{wd.user_id}@example.com",
            bank_name=bank_name_str,
            card_number=account_no,
            account_name=account_name,
            bank_no=bank_code,
        )
        payload["sign"] = bankpay_generate_sign(payload, key)

        trace, _ = BankPayWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
        if trace and not trace.request_params:
            trace.request_params = payload
            trace.save(update_fields=["request_params"])

        response_payload = bankpay_post_form(f"{api_url.rstrip('/')}/Pay-payment-draw.aspx", payload)
        if trace:
            stored = trace.response_payload or {}
            stored["initiate"] = response_payload
            trace.response_payload = stored
            trace.save(update_fields=["response_payload"])

        if isinstance(response_payload, dict) and response_payload.get("status") == 1:
            msg = response_payload.get("msg") if isinstance(response_payload.get("msg"), dict) else {}
            trade_state = str(msg.get("trade_state") or "").strip().upper()
            if trade_state == "SUCCESS":
                wd.status = "COMPLETED"
                wd.save(update_fields=["status"])
            elif trade_state in ("REFUSE",):
                wd.status = "REJECTED"
                wd.save(update_fields=["status"])
            else:
                wd.status = "PROCESSING"
                wd.save(update_fields=["status"])
            return Response({"gateway": response_payload}, status=status.HTTP_200_OK)

        wd.status = "REJECTED"
        wd.save(update_fields=["status"])
        return Response({"detail": response_payload.get("msg") if isinstance(response_payload, dict) else "Payout gagal", "gateway": response_payload}, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name="dispatch")
class BankPayPayoutCallbackView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "gateway_callback"

    @extend_schema(summary="Callback BankPay untuk update status withdraw")
    def post(self, request, *args, **kwargs):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        key = (gs.bankpay_payout_key or "").strip() if gs else ""
        payload = _bankpay_withdraw_collect_payload(request)
        order_id = str(payload.get("orderid") or "").strip()
        if not order_id:
            return HttpResponse("OK", content_type="text/plain")

        trx = Transaction.objects.filter(trx_id=order_id).first()
        withdrawal = Withdrawal.objects.filter(transaction=trx).first() if trx else None
        if not withdrawal:
            return HttpResponse("OK", content_type="text/plain")

        sign_valid = bankpay_verify_sign(dict(payload), key)
        trace = BankPayWithdrawal.objects.filter(withdrawal=withdrawal).first()
        if trace:
            stored = trace.response_payload or {}
            stored["callback"] = {**payload, "_sign_valid": sign_valid}
            trace.response_payload = stored
            trace.save(update_fields=["response_payload"])

        if not sign_valid:
            return HttpResponse("OK", content_type="text/plain")

        returncode = str(payload.get("returncode") or "").strip()
        mapped = bankpay_map_payout_returncode(returncode)
        if mapped:
            withdrawal.status = mapped
            withdrawal.save(update_fields=["status"])
        return HttpResponse("OK", content_type="text/plain")


def _bankpay_withdraw_collect_payload(request) -> dict:
    if isinstance(request.data, dict) and request.data:
        return dict(request.data)
    post_data = dict(request.POST) if hasattr(request, "POST") else {}
    result = {}
    for k, v in post_data.items():
        if isinstance(v, list) and len(v) == 1:
            result[k] = v[0]
        elif isinstance(v, list):
            result[k] = v[-1]
        else:
            result[k] = v
    if not result:
        raw = request.body or b""
        try:
            body_str = raw.decode("utf-8")
        except Exception:
            body_str = ""
        for pair in body_str.split("&"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                result[k] = v
            elif pair:
                result[pair] = ""
    return result


# ============================================================
# Reepay Payout Views (HMAC-SHA256)
# ============================================================

def _reepay_withdraw_raw_body(request) -> str:
    raw = request.body or b""
    try:
        return raw.decode("utf-8")
    except Exception:
        return ""


def _reepay_withdraw_callback_payload(request) -> dict:
    raw = _reepay_withdraw_raw_body(request)
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    if isinstance(getattr(request, "data", None), dict):
        return request.data
    return {}


def _reepay_withdraw_verify_callback(request, secret: str) -> bool:
    timestamp = (request.META.get("HTTP_X_TIMESTAMP") or "").strip()
    signature = (request.META.get("HTTP_X_SIGNATURE") or "").strip()
    webhook_path = request.path
    raw_body = _reepay_withdraw_raw_body(request)
    return reepay_verify_callback_signature(secret, timestamp, webhook_path, raw_body, signature)


def _reepay_handle_withdraw_callback(request, payload: dict):
    """Proses callback withdraw.* dari Reepay (payout)."""
    gs = WithdrawalSettings.objects.order_by("-updated_at").first()
    secret_key = (gs.reepay_payout_secret_key or "").strip() if gs else ""

    event = str(reepay_extract_callback_field(payload, "event") or "").strip()
    merchant_ref = str(reepay_extract_callback_field(payload, "merchant_ref") or "").strip()

    if not merchant_ref:
        return

    sign_valid = _reepay_withdraw_verify_callback(request, secret_key)

    trx = Transaction.objects.filter(trx_id=merchant_ref).first()
    withdrawal = Withdrawal.objects.filter(transaction=trx).first() if trx else None

    trace = ReepayWithdrawal.objects.filter(withdrawal=withdrawal).first() if withdrawal else None
    if trace:
        stored = trace.response_payload if isinstance(trace.response_payload, dict) else {}
        stored["callback"] = {**payload, "_sign_valid": sign_valid}
        trace.response_payload = stored
        trace.save(update_fields=["response_payload"])

    if not withdrawal or not sign_valid:
        return

    if event == "disbursement.success":
        withdrawal.status = "COMPLETED"
        withdrawal.save(update_fields=["status"])
    elif event in ("disbursement.failed", "disbursement.rejected"):
        withdrawal.status = "REJECTED"
        withdrawal.save(update_fields=["status"])
    elif event == "disbursement.processing":
        withdrawal.status = "PROCESSING"
        withdrawal.save(update_fields=["status"])


class ReepayPayoutInitiateView(APIView):
    permission_classes = [permissions.IsAdminUser]
    throttle_scope = "withdraw_admin_initiate"

    @extend_schema(summary="Inisiasi withdraw via Reepay (admin)")
    def post(self, request, pk: int):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.reepay_payout_enabled)
        api_url = (gs.reepay_payout_api_url or "https://api.roguecdn.online").strip() if gs else ""
        api_key = (gs.reepay_payout_api_key or "").strip() if gs else ""
        secret_key = (gs.reepay_payout_secret_key or "").strip() if gs else ""

        if not enabled:
            return Response({"detail": "Reepay payout tidak aktif"}, status=status.HTTP_400_BAD_REQUEST)
        if not api_url or not api_key or not secret_key:
            return Response({"detail": "Konfigurasi Reepay payout belum lengkap"}, status=status.HTTP_400_BAD_REQUEST)

        try:
            wd = Withdrawal.objects.select_related("user", "bank_account__bank", "transaction").get(pk=pk)
        except Withdrawal.DoesNotExist:
            return Response({"detail": "Withdrawal tidak ditemukan"}, status=status.HTTP_404_NOT_FOUND)

        if wd.status not in ("PENDING", "PROCESSING"):
            return Response({"detail": "Status withdrawal tidak valid untuk inisiasi"}, status=status.HTTP_400_BAD_REQUEST)

        account_no = getattr(wd.bank_account, "account_number", "") or ""
        account_name = getattr(wd.bank_account, "account_name", "") or ""
        bank = getattr(getattr(wd, "bank_account", None), "bank", None)
        bank_code = getattr(bank, "code", "") or ""

        amount_raw = request.data.get("amount")
        try:
            amount = ppaypros_normalize_amount(amount_raw) if amount_raw is not None else ppaypros_normalize_amount(wd.net_amount or wd.amount)
            if amount <= 0:
                raise InvalidOperation()
        except Exception:
            return Response({"detail": "amount tidak valid"}, status=status.HTTP_400_BAD_REQUEST)

        amount_int = int(round(float(amount)))
        merchant_ref = getattr(getattr(wd, "transaction", None), "trx_id", None) or f"WRP{wd.pk}{int(pytime.time())}"

        payload = {
            "amount": amount_int,
            "destination_account": account_no,
            "bank_code": bank_code,
            "account_holder_name": (account_name or "")[:100],
            "merchant_ref": merchant_ref,
        }

        trace, _ = ReepayWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
        if trace and not trace.request_params:
            trace.request_params = payload
            trace.save(update_fields=["request_params"])

        resp_data, http_status = reepay_post_json(
            api_key, secret_key, "/merchant/withdraw/create", payload, base_url=api_url
        )

        if trace:
            stored = trace.response_payload if isinstance(trace.response_payload, dict) else {}
            stored["initiate"] = resp_data
            trace.response_payload = stored
            trace.save(update_fields=["response_payload"])

        if resp_data.get("success"):
            data = resp_data.get("data") if isinstance(resp_data.get("data"), dict) else {}
            ref_id = (data.get("ref_id") or "").strip()
            if ref_id:
                note = f"Reepay ref_id: {ref_id}"
                wd.note = f"{note}\n{wd.note}" if wd.note else note
                wd.save(update_fields=["note"])
            wd.status = "PROCESSING"
            wd.save(update_fields=["status"])
            return Response({"ref_id": ref_id, "provider": resp_data}, status=status.HTTP_200_OK)

        detail_msg = (
            resp_data.get("message")
            or resp_data.get("detail")
            or resp_data.get("msg")
            or "Reepay payout gagal"
        )
        return Response({"detail": detail_msg, "provider": resp_data}, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name="dispatch")
class ReepayPayoutCallbackView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_scope = "gateway_callback"

    @extend_schema(summary="Callback Reepay untuk update status withdraw")
    def post(self, request, *args, **kwargs):
        payload = _reepay_withdraw_callback_payload(request)
        _reepay_handle_withdraw_callback(request, payload)
        return HttpResponse("OK", content_type="text/plain")
