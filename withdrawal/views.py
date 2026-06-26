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
from .models import JayapayWithdrawal, JayapayPhPayoutWithdrawal, UsdPayoutWithdrawal
from products.models import Transaction
from products.serializers import TransactionSerializer
from django.db.models import Q
from zoneinfo import ZoneInfo
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
import json
import requests

from .integrations.usd_payout import build_payload as usd_build_payload, sign_hmac_sha256, sign_hmac_sha256_then_rsa_base64, send_single_order
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
