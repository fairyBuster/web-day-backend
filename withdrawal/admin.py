from django.contrib import admin, messages
from django.conf import settings
from django.urls import path, reverse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from .models import Withdrawal, WithdrawalSettings, WithdrawalJayapay, WithdrawalService, UsdPayoutWithdrawal, JayapayPhPayoutWithdrawal, PPayProsWithdrawal, AtpayWithdrawal, BankPayWithdrawal, ReepayWithdrawal, BatPayWithdrawal, NextPayWithdrawal
from .integrations.jayapay import build_params, sign_params, sign_params_legacy, send_cash_request
from .integrations.jayapay_banks import JAYAPAY_BANKS
from .integrations.jayapay_ph_banks import JAYAPAY_PH_PAYOUT_BANKS
from .integrations.ppaypros_bank_codes import PPAYPROS_PAYOUT_CODES
from .integrations.usd_payout import build_payload as usd_build_payload, sign_hmac_sha256_then_rsa_base64, send_single_order
from .integrations.ppaypros import build_payout_payload as ppaypros_build_payout_payload, map_payout_state as ppaypros_map_payout_state
from deposits.integrations.ppaypros import amount_to_points as ppaypros_amount_to_points, generate_sign as ppaypros_generate_sign, parse_data_field as ppaypros_parse_data_field, post_json as ppaypros_post_json, verify_sign as ppaypros_verify_sign
from deposits.integrations.atpay import build_bank_code_payload as atpay_build_bank_code_payload, build_payout_payload as atpay_build_payout_payload, build_payout_query_payload as atpay_build_payout_query_payload, map_payout_trade_status as atpay_map_payout_trade_status, normalize_amount as atpay_normalize_amount, normalize_sign_type as atpay_normalize_sign_type, post_json as atpay_post_json, sign_payload as atpay_sign_payload, verify_payload as atpay_verify_payload
from deposits.integrations.bankpay import generate_sign as bankpay_generate_sign, post_form as bankpay_post_form, build_payout_payload as bankpay_build_payout_payload, fetch_bank_list as bankpay_fetch_bank_list
from deposits.integrations.reepay import post_json as reepay_post_json
from deposits.integrations.batpay import post_json as batpay_post_json, get_json as batpay_get_json
from deposits.integrations.nextpay import post_json as nextpay_post_json, get_json as nextpay_get_json
from django.utils.html import format_html
import json
import logging
import time
import requests
from decimal import Decimal, InvalidOperation


logger = logging.getLogger(__name__)

USD_PAYOUT_BANK_CODE_CHOICES = (
    ("ETH", "Ethereum/ERC20"),
    ("TRX", "Tron/TRC20"),
    ("MATIC", "Polygon"),
    ("BSC", "BNB Smart Chain/BEP20"),
    ("SOL", "Solana"),
    ("ARBEVM", "Arbitrum One"),
    ("CASH", "cashapp wallet"),
    ("VENMO", "venmo"),
    ("PAYPAL", "paypal"),
)

# Daftar bank Reepay (bankCode -> bankName). Dipakai sebagai fallback saat API
# /merchant/withdraw/banks tidak bisa diakses (mis. kena block Cloudflare).
REEPAY_FALLBACK_BANK_CODES = (
    ("014", "Bank Central Asia (BCA)"),
    ("009", "Bank Negara Indonesia (BNI)"),
    ("002", "Bank Rakyat Indonesia (BRI)"),
    ("008", "Bank Mandiri"),
    ("013", "Bank Permata"),
    ("022", "Bank CIMB Niaga"),
    ("4510", "Bank Syariah Indonesia (BSI)"),
    ("200", "Bank Tabungan Negara (BTN)"),
    ("019", "Bank Panin"),
    ("028", "Bank OCBC NISP"),
    ("426", "Bank Mega"),
    ("016", "Bank Maybank"),
    ("147", "Bank Muamalat Indonesia"),
    ("041", "HSBC"),
    ("011", "Bank Danamon"),
    ("046", "Bank DBS Indonesia"),
    ("031", "Citibank"),
    ("050", "Standard Chartered Bank"),
    ("023", "TMRW / Bank UOB Indonesia"),
    ("067", "Deutsche Bank"),
    ("069", "Bank of China"),
    ("1450", "Bank BNP Paribas"),
    ("535", "Seabank (Bank Kesejahteraan Ekonomi)"),
    ("542", "Bank Jago (ARTOS)"),
    ("5010", "Blu / BCA Digital"),
    ("567", "Allo Bank"),
    ("490", "Neo Commerce (BNC)"),
    ("484", "LINE Bank / KEB Hana"),
    ("213", "Bank BTPN"),
    ("441", "Wokee / Bukopin"),
    ("087", "Bank Ekonomi Raharja"),
    ("097", "Bank Mayapada"),
    ("153", "Bank Sinarmas"),
    ("152", "Bank Shinhan Indonesia"),
    ("212", "Bank Woori Saudara"),
    ("494", "Bank Agroniaga"),
    ("466", "Bank Andara"),
    ("10001", "OVO"),
    ("10002", "DANA"),
    ("10003", "GOPAY"),
    ("10008", "SHOPEEPAY"),
    ("10009", "LINKAJA"),
    ("10007", "NATIONALNOBU"),
)


def _redact_for_log(value):
    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if str(k).lower() in {"sign", "signature"}:
                out[k] = "<redacted>"
            else:
                out[k] = _redact_for_log(v)
        return out
    if isinstance(value, list):
        return [_redact_for_log(v) for v in value]
    return value


PPAYPROS_PAYOUT_CODE_SET = {item["code"] for item in PPAYPROS_PAYOUT_CODES if item.get("code")}


def _fetch_atpay_bank_codes(gs):
    enabled = bool(gs and getattr(gs, "atpay_payout_enabled", False))
    api_url = (getattr(gs, "atpay_payout_api_url", "") or "").strip() if gs else ""
    merchant_no = (getattr(gs, "atpay_payout_merchant_no", "") or "").strip() if gs else ""
    sign_type = atpay_normalize_sign_type((getattr(gs, "atpay_payout_sign_type", "") or "MD5").strip() if gs else "MD5")
    secret_key = (getattr(gs, "atpay_payout_secret_key", "") or "").strip() if gs else ""
    private_key = (getattr(gs, "atpay_payout_private_key", "") or "").strip() if gs else ""
    if not enabled or not api_url or not merchant_no:
        return [], ""
    if sign_type == "MD5" and not secret_key:
        return [], "Secret key ATPAY payout belum diisi"
    if sign_type == "MD5withRsa" and not private_key:
        return [], "Private key ATPAY payout belum diisi"
    try:
        payload = atpay_build_bank_code_payload(merchant_no=merchant_no, sign_type=sign_type)
        payload["sign"] = atpay_sign_payload(payload, sign_type, secret_key=secret_key, private_key=private_key)
        response_payload = atpay_post_json(f"{api_url.rstrip('/')}/gw-api/bank-code", payload)
        if str(response_payload.get("code") or "").strip() != "100":
            return [], str(response_payload.get("message") or "Gagal mengambil bank code ATPAY")
        items = response_payload.get("data") if isinstance(response_payload.get("data"), list) else []
        results = []
        for item in items:
            bank_code = str(item.get("bank_code") or "").strip()
            bank_name = str(item.get("bank_name") or "").strip()
            if bank_code:
                results.append({"bank_code": bank_code, "bank_name": bank_name})
        return results, ""
    except Exception as exc:
        logger.warning("Failed to fetch ATPAY bank codes: %s", exc, exc_info=True)
        return [], str(exc)


@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'bank_account', 'withdrawal_service', 'amount', 'fee', 'net_amount', 'status_display', 'created_at'
    )
    list_filter = ('status', 'created_at')
    search_fields = ('user__phone', 'bank_account__account_number')
    readonly_fields = ('created_at', 'updated_at')
    actions = ['process_withdrawal_jayapay', 'process_withdrawal_bankpay', 'process_withdrawal_reepay', 'process_withdrawal_batpay', 'process_withdrawal_nextpay']
    change_form_template = 'admin/withdrawal/change_form.html'
    autocomplete_fields = ('user', 'bank_account', 'transaction')
    list_select_related = ('user', 'bank_account', 'transaction', 'withdrawal_service')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.select_related('user', 'bank_account__bank', 'transaction')

    def status_display(self, obj):
        color_map = {
            'PENDING': '#f59e0b',      # amber
            'PROCESSING': '#3b82f6',   # blue
            'COMPLETED': '#10b981',    # green
            'REJECTED': '#ef4444',     # red
            'FAILED': '#ef4444',       # red
            'CANCELLED': '#9ca3af',    # gray
        }
        label = obj.status.title()
        color = color_map.get(obj.status, '#6b7280')  # default gray
        return format_html(
            '<span style="padding:2px 10px;border-radius:999px;background-color:{};color:#fff;font-weight:600;font-size:12px;">{}</span>',
            color,
            label,
        )
    status_display.short_description = 'Status'

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                '<int:pk>/process-jayapay/',
                self.admin_site.admin_view(self.process_jayapay_view),
                name='withdrawal_withdrawal_process_jayapay',
            ),
            path(
                '<int:pk>/process-jayapay-ph/',
                self.admin_site.admin_view(self.process_jayapay_ph_view),
                name='withdrawal_withdrawal_process_jayapay_ph',
            ),
            path(
                '<int:pk>/process-usd-payout/',
                self.admin_site.admin_view(self.process_usd_payout_view),
                name='withdrawal_withdrawal_process_usd_payout',
            ),
            path(
                '<int:pk>/process-ppaypros/',
                self.admin_site.admin_view(self.process_ppaypros_view),
                name='withdrawal_withdrawal_process_ppaypros',
            ),
            path(
                '<int:pk>/process-atpay/',
                self.admin_site.admin_view(self.process_atpay_view),
                name='withdrawal_withdrawal_process_atpay',
            ),
            path(
                '<int:pk>/process-bankpay/',
                self.admin_site.admin_view(self.process_bankpay_view),
                name='withdrawal_withdrawal_process_bankpay',
            ),
            path(
                '<int:pk>/process-reepay/',
                self.admin_site.admin_view(self.process_reepay_view),
                name='withdrawal_withdrawal_process_reepay',
            ),
            path(
                '<int:pk>/process-batpay/',
                self.admin_site.admin_view(self.process_batpay_view),
                name='withdrawal_withdrawal_process_batpay',
            ),
            path(
                '<int:pk>/process-nextpay/',
                self.admin_site.admin_view(self.process_nextpay_view),
                name='withdrawal_withdrawal_process_nextpay',
            ),
        ]
        return custom + urls

    def process_jayapay_view(self, request, pk: int):
        try:
            wd = Withdrawal.objects.select_related('bank_account__bank', 'user').get(pk=pk)
        except Withdrawal.DoesNotExist:
            self.message_user(request, 'Withdrawal tidak ditemukan', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_changelist'))

        if not getattr(settings, 'JAYAPAY_ENABLED', False):
            self.message_user(request, 'Jayapay tidak aktif (JAYAPAY_ENABLED=false)', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
        if not settings.JAYAPAY_MERCHANT_CODE or not settings.JAYAPAY_PRIVATE_KEY:
            self.message_user(request, 'Konfigurasi Jayapay belum lengkap', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        initial = {
            'bankCode': wd.bank_account.bank.code if wd.bank_account else '',
            'accountNumber': wd.bank_account.account_number if wd.bank_account else '',
            'accountName': wd.bank_account.account_name if wd.bank_account else '',
            'amount': str(wd.net_amount or wd.amount),
        }

        if request.method == 'POST':
            bank_code = request.POST.get('bankCode')
            account_number = request.POST.get('accountNumber')
            account_name = request.POST.get('accountName')
            amount = request.POST.get('amount')

            if not bank_code or not account_number or not account_name or not amount:
                self.message_user(request, 'Semua field harus diisi', level=messages.ERROR)
                context = dict(self.admin_site.each_context(request), withdrawal=wd, initial=initial)
                return TemplateResponse(request, 'admin/withdrawal_jayapay.html', context)

            # Override net_amount jika admin isi amount
            try:
                wd.net_amount = float(amount)
            except Exception:
                self.message_user(request, 'Amount tidak valid', level=messages.ERROR)
                context = dict(self.admin_site.each_context(request), withdrawal=wd, initial=initial)
                return TemplateResponse(request, 'admin/withdrawal_jayapay.html', context)

            try:
                params = build_params(
                    wd,
                    merchant_code=settings.JAYAPAY_MERCHANT_CODE,
                    bank_code=bank_code,
                    account_number=account_number,
                    account_name=account_name,
                    notify_url=settings.JAYAPAY_NOTIFY_URL,
                )
                params['sign'] = sign_params(params, settings.JAYAPAY_PRIVATE_KEY)
                resp = send_cash_request(params)
                # Persist traceability for admin action as well
                try:
                    jp_withdrawal, _ = WithdrawalJayapay.objects.get_or_create(
                        withdrawal=wd,
                        defaults={"request_params": params}
                    )
                    if jp_withdrawal and not jp_withdrawal.request_params:
                        jp_withdrawal.request_params = params
                        jp_withdrawal.response_payload = resp
                        jp_withdrawal.save(update_fields=['request_params', 'response_payload'])
                    else:
                        jp_withdrawal.response_payload = resp
                        jp_withdrawal.save(update_fields=['response_payload'])
                except Exception:
                    pass
                wd.status = 'PROCESSING'
                wd.save()
                self.message_user(request, f"Withdrawal #{wd.id} dikirim ke Jayapay", level=messages.SUCCESS)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
            except Exception as e:
                self.message_user(request, f"Gagal kirim ke Jayapay: {e}", level=messages.ERROR)
                context = dict(self.admin_site.each_context(request), withdrawal=wd, initial=initial)
                return TemplateResponse(request, 'admin/withdrawal_jayapay.html', context)

        context = dict(self.admin_site.each_context(request), withdrawal=wd, initial=initial)
        return TemplateResponse(request, 'admin/withdrawal_jayapay.html', context)

    def process_usd_payout_view(self, request, pk: int):
        try:
            wd = Withdrawal.objects.select_related('bank_account__bank', 'user', 'transaction').get(pk=pk)
        except Withdrawal.DoesNotExist:
            self.message_user(request, 'Withdrawal tidak ditemukan', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_changelist'))

        if not getattr(settings, 'USD_PAYOUT_ENABLED', False):
            self.message_user(request, 'USD payout tidak aktif (USD_PAYOUT_ENABLED=false)', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
        if not settings.USD_PAYOUT_API_URL or not settings.USD_PAYOUT_MER_NO or not settings.USD_PAYOUT_SIGN_KEY or not settings.USD_PAYOUT_RSA_PRIVATE_KEY:
            self.message_user(request, 'Konfigurasi USD payout belum lengkap', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        initial = {
            'bankCode': wd.bank_account.bank.code if wd.bank_account and wd.bank_account.bank else '',
            'accNo': wd.bank_account.account_number if wd.bank_account else '',
            'accName': wd.bank_account.account_name if wd.bank_account else '',
            'email': getattr(wd.user, 'email', '') or f"user{wd.user_id}@example.com",
            'phone': (getattr(wd.bank_account, 'phone', '') or getattr(wd.user, 'phone', '') or '').strip(),
            'orderAmount': str(wd.net_amount or wd.amount),
        }

        if request.method == 'POST':
            bank_code = (request.POST.get('bankCode') or '').strip()
            acc_no = (request.POST.get('accNo') or '').strip()
            acc_name = (request.POST.get('accName') or '').strip()
            email = (request.POST.get('email') or '').strip() or initial['email']
            phone = (request.POST.get('phone') or '').strip() or initial['phone']
            order_amount = (request.POST.get('orderAmount') or '').strip() or initial['orderAmount']

            if not bank_code or not acc_no or not acc_name or not order_amount:
                self.message_user(request, 'bankCode, accNo, accName, orderAmount wajib diisi', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            allowed_bank_codes = {c[0] for c in USD_PAYOUT_BANK_CODE_CHOICES}
            if bank_code not in allowed_bank_codes:
                self.message_user(request, f"bankCode tidak valid (pilih: {', '.join(sorted(allowed_bank_codes))})", level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            mer_order_no = wd.transaction.trx_id if wd.transaction else f"WD-{wd.id}-{int(time.time() * 1000)}"
            payload = usd_build_payload(
                acc_name=acc_name,
                acc_no=acc_no,
                bank_code=bank_code,
                busi_code="265001",
                currency='USD',
                email=email,
                mer_no=settings.USD_PAYOUT_MER_NO,
                mer_order_no=mer_order_no,
                notify_url=getattr(settings, 'USD_PAYOUT_NOTIFY_URL', ''),
                order_amount=order_amount,
                phone=''.join([c for c in (phone or '') if c.isdigit()]) or '0000000000',
            )

            try:
                sign, sign_a, raw = sign_hmac_sha256_then_rsa_base64(
                    payload,
                    sign_key=settings.USD_PAYOUT_SIGN_KEY,
                    rsa_private_key_pem=settings.USD_PAYOUT_RSA_PRIVATE_KEY,
                    hex_key=False,
                )
                payload['sign'] = sign
            except Exception as e:
                self.message_user(request, f"Gagal generate signature: {e}", level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            trace, _ = UsdPayoutWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
            if trace and not trace.request_params:
                trace.request_params = payload
                trace.save(update_fields=['request_params'])

            try:
                try:
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
                except Exception:
                    pass
                resp = send_single_order(settings.USD_PAYOUT_API_URL, payload)
            except Exception as e:
                trace.response_payload = {"error": str(e)}
                trace.save(update_fields=['response_payload'])
                wd.status = 'PROCESSING'
                wd.save(update_fields=['status'])
                self.message_user(request, f"Gagal kirim ke USD payout: {e}", level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            code_first = str(resp.get("code") or "").strip()
            sign_key = (settings.USD_PAYOUT_SIGN_KEY or "").strip()
            key_is_hex = len(sign_key) % 2 == 0 and all(c in "0123456789abcdefABCDEF" for c in sign_key) and bool(sign_key)
            if code_first == "901007" and key_is_hex:
                payload2 = dict(payload)
                sign2, sign_a2, raw2 = sign_hmac_sha256_then_rsa_base64(
                    {k: v for k, v in payload2.items() if k != "sign"},
                    sign_key=sign_key,
                    rsa_private_key_pem=settings.USD_PAYOUT_RSA_PRIVATE_KEY,
                    hex_key=True,
                )
                payload2["sign"] = sign2
                try:
                    logger.warning(
                        "USD_PAYOUT singleOrder retry (hex_key): withdrawal=%s order=%s raw=%s signA=%s sign=%s",
                        wd.id,
                        mer_order_no,
                        raw2,
                        sign_a2[:10],
                        sign2[:10],
                    )
                except Exception:
                    pass
                try:
                    resp2 = send_single_order(settings.USD_PAYOUT_API_URL, payload2)
                    if resp2:
                        resp = resp2
                        payload = payload2
                except Exception:
                    pass

            trace.response_payload = resp
            trace.save(update_fields=['response_payload'])
            try:
                logger.warning(
                    "USD_PAYOUT singleOrder response: withdrawal=%s order=%s resp=%s",
                    wd.id,
                    mer_order_no,
                    json.dumps(_redact_for_log(resp), ensure_ascii=False),
                )
            except Exception:
                pass

            code = str(resp.get('code') or '').strip()
            data = resp.get('data') if isinstance(resp.get('data'), dict) else {}
            try:
                st = int(data.get('status')) if data.get('status') is not None else None
            except Exception:
                st = None

            if code in ('200', '500'):
                if st == 7:
                    wd.status = 'COMPLETED'
                elif st in (2, 6, 8):
                    wd.status = 'REJECTED'
                else:
                    wd.status = 'PROCESSING'
                wd.save(update_fields=['status'])
                self.message_user(request, f"Withdrawal #{wd.id} dikirim ke USD payout (code={code}, status={st})", level=messages.SUCCESS)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            wd.status = 'REJECTED'
            wd.save(update_fields=['status'])
            self.message_user(request, f"USD payout gagal: {resp.get('msg') or resp}", level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

    def process_jayapay_ph_view(self, request, pk: int):
        try:
            wd = Withdrawal.objects.select_related('bank_account__bank', 'user', 'transaction').get(pk=pk)
        except Withdrawal.DoesNotExist:
            self.message_user(request, 'Withdrawal tidak ditemukan', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_changelist'))

        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and getattr(gs, "jayapay_ph_payout_enabled", False))
        mch_no = (getattr(gs, "jayapay_ph_payout_mch_no", "") or "").strip() if gs else ""
        private_key = (getattr(gs, "jayapay_ph_payout_private_key", "") or "").strip() if gs else ""
        api_url = (getattr(gs, "jayapay_ph_payout_api_url", "") or "").strip() if gs else ""
        app_domain = (getattr(gs, "app_domain", "") or "").strip() if gs else ""
        if not app_domain:
            try:
                from deposits.models import GatewaySettings
                ggs = GatewaySettings.objects.order_by("-updated_at").first()
                app_domain = (getattr(ggs, "app_domain", "") or "").strip() if ggs else ""
            except Exception:
                app_domain = ""
        fee_type_default = int(getattr(gs, "jayapay_ph_payout_fee_type", 1) or 1) if gs else 1

        if not enabled:
            self.message_user(request, 'Jayapay PH payout tidak aktif', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
        if not mch_no or not private_key or not app_domain:
            self.message_user(request, 'Konfigurasi Jayapay PH payout belum lengkap (mchNo/privateKey/app_domain)', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        api_url = api_url or "https://global-ph-openapi.jayapayment.com/ph/disbursement/cash"

        initial = {
            "bankCode": "GCASH",
            "bankCard": wd.bank_account.account_number if wd.bank_account else "",
            "accountName": wd.bank_account.account_name if wd.bank_account else "",
            "amount": str(wd.net_amount or wd.amount),
            "feeType": str(fee_type_default),
            "description": (wd.note or f"Withdrawal #{wd.id}")[:255],
        }

        if request.method == "POST":
            bank_code = (request.POST.get("bankCode") or "").strip().upper().replace("-", "_").replace(" ", "_")
            bank_card = (request.POST.get("bankCard") or "").strip()
            account_name = (request.POST.get("accountName") or "").strip()
            amount_raw = (request.POST.get("amount") or "").strip()
            fee_type_raw = (request.POST.get("feeType") or "").strip()
            description = (request.POST.get("description") or "").strip()[:255] or initial["description"]

            if not bank_code or not bank_card or not account_name or not amount_raw:
                self.message_user(request, "bankCode, bankCard, accountName, amount wajib diisi", level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            allowed_codes = {b.get("bankCode") for b in (JAYAPAY_PH_PAYOUT_BANKS or []) if b.get("bankCode")}
            if allowed_codes and bank_code not in allowed_codes:
                self.message_user(request, "bankCode tidak valid", level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            try:
                amount = Decimal(str(amount_raw)).quantize(Decimal("0.01"))
                if amount <= 0:
                    raise InvalidOperation()
            except (InvalidOperation, ValueError, TypeError):
                self.message_user(request, "Amount tidak valid", level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            try:
                fee_type = int(fee_type_raw) if fee_type_raw != "" else fee_type_default
            except Exception:
                fee_type = fee_type_default
            if fee_type not in (0, 1):
                fee_type = fee_type_default

            order_num = wd.transaction.trx_id if wd.transaction else f"WD-PH-{wd.id}-{int(time.time() * 1000)}"
            if len(order_num) > 50:
                order_num = f"WD-PH-{wd.id}-{int(time.time() * 1000)}"

            payload = {
                "mchNo": mch_no,
                "orderNum": order_num,
                "amount": int(amount) if amount == amount.to_integral() else float(amount),
                "bankCode": bank_code,
                "bankCard": bank_card,
                "accountName": account_name,
                "description": description,
                "feeType": fee_type,
                "downNotifyUrl": f"https://{app_domain}/api/withdrawals/jayapay-ph/callback/",
                "timestamp": str(int(time.time() * 1000)),
            }

            try:
                payload["sign"] = sign_params_legacy(payload, private_key)
            except Exception as e:
                self.message_user(request, f"Gagal membuat signature: {e}", level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            trace, _ = JayapayPhPayoutWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
            if trace and not trace.request_params:
                trace.request_params = payload
                trace.save(update_fields=["request_params"])

            try:
                resp = requests.post(api_url, json=payload, timeout=30)
                resp_data = resp.json() if resp.content else {}
            except Exception as e:
                wd.status = "PROCESSING"
                wd.save(update_fields=["status"])
                trace.response_payload = {"error": str(e)}
                trace.save(update_fields=["response_payload"])
                self.message_user(request, f"Gagal menghubungi Jayapay PH: {e}", level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            trace.response_payload = _redact_for_log(resp_data)
            trace.save(update_fields=["response_payload"])

            success = bool(resp_data.get("success")) and str(resp_data.get("code") or "").strip() == "9999"
            if success:
                wd.status = "PROCESSING"
                wd.save(update_fields=["status"])
                self.message_user(request, f"Withdrawal #{wd.id} dikirim ke Jayapay PH", level=messages.SUCCESS)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            wd.status = "REJECTED"
            wd.save(update_fields=["status"])
            self.message_user(request, f"Jayapay PH gagal: {resp_data.get('msg') or resp_data}", level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

    def process_ppaypros_view(self, request, pk: int):
        try:
            wd = Withdrawal.objects.select_related('bank_account__bank', 'user', 'transaction').get(pk=pk)
        except Withdrawal.DoesNotExist:
            self.message_user(request, 'Withdrawal tidak ditemukan', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_changelist'))

        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and getattr(gs, "ppaypros_payout_enabled", False))
        api_url = (getattr(gs, "ppaypros_payout_api_url", "") or "").strip() if gs else ""
        mch_no = (getattr(gs, "ppaypros_payout_mch_no", "") or "").strip() if gs else ""
        app_id = (getattr(gs, "ppaypros_payout_app_id", "") or "").strip() if gs else ""
        private_key = (getattr(gs, "ppaypros_payout_private_key", "") or "").strip() if gs else ""
        entry_type_default = (getattr(gs, "ppaypros_payout_entry_type", "") or "BANK_CARD").strip() if gs else "BANK_CARD"
        app_domain = (getattr(gs, "app_domain", "") or "").strip() if gs else ""
        if not app_domain:
            try:
                from deposits.models import GatewaySettings
                ggs = GatewaySettings.objects.order_by("-updated_at").first()
                app_domain = (getattr(ggs, "app_domain", "") or "").strip() if ggs else ""
            except Exception:
                app_domain = ""

        if not enabled:
            self.message_user(request, 'PPay Pros payout tidak aktif', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
        if not api_url or not mch_no or not app_id or not private_key or not app_domain:
            self.message_user(request, 'Konfigurasi PPay Pros payout belum lengkap', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        if request.method == "POST":
            entry_type = (request.POST.get("entryType") or entry_type_default or "BANK_CARD").strip().upper()
            account_code = (request.POST.get("accountCode") or (wd.bank_account.bank.code if wd.bank_account and wd.bank_account.bank else "")).strip()
            account_no = (request.POST.get("accountNo") or (wd.bank_account.account_number if wd.bank_account else "")).strip()
            account_name = (request.POST.get("accountName") or (wd.bank_account.account_name if wd.bank_account else "")).strip()
            account_email = (request.POST.get("accountEmail") or getattr(wd.user, 'email', '') or f"user{wd.user_id}@example.com").strip()
            account_phone = (request.POST.get("accountPhone") or getattr(wd.bank_account, 'phone', '') or getattr(wd.user, 'phone', '') or '').strip()
            amount_raw = (request.POST.get("amount") or '').strip() or str(wd.net_amount or wd.amount)

            if not account_code or not account_no or not account_name or not amount_raw:
                self.message_user(request, 'entry/accountCode/accountNo/accountName/amount wajib diisi', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
            if PPAYPROS_PAYOUT_CODE_SET and account_code not in PPAYPROS_PAYOUT_CODE_SET:
                self.message_user(request, 'Account Code tidak valid untuk PPay Pros', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            try:
                amount = Decimal(str(amount_raw)).quantize(Decimal("0.01"))
                if amount <= 0:
                    raise InvalidOperation()
            except Exception:
                self.message_user(request, 'Amount tidak valid', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            mch_order_no = wd.transaction.trx_id if wd.transaction else f"WPP{wd.id}{int(time.time())}"
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
                notify_url=f"https://{app_domain}/api/withdrawals/ppaypros/callback/",
                bank_name=(wd.bank_account.bank.name if wd.bank_account and wd.bank_account.bank else "")[:64],
                ext_param=f"withdrawal:{wd.id}",
            )
            payload["sign"] = ppaypros_generate_sign(payload, private_key)

            trace, _ = PPayProsWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
            if trace and not trace.request_params:
                trace.request_params = payload
                trace.save(update_fields=["request_params"])

            response_payload = ppaypros_post_json(f"{api_url.rstrip('/')}/api/payout/pay", payload)
            if response_payload.get("sign"):
                response_payload["_sign_valid"] = ppaypros_verify_sign(response_payload, private_key)
            trace.response_payload = {"initiate": _redact_for_log(response_payload)}
            trace.save(update_fields=["response_payload"])

            if str(response_payload.get("code")) == "0":
                data = ppaypros_parse_data_field(response_payload)
                mapped = ppaypros_map_payout_state(data.get("state"))
                wd.status = mapped or 'PROCESSING'
                wd.save(update_fields=['status'])
                self.message_user(request, f"Withdrawal #{wd.id} dikirim ke PPay Pros", level=messages.SUCCESS)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            wd.status = 'REJECTED'
            wd.save(update_fields=['status'])
            self.message_user(request, f"PPay Pros gagal: {response_payload.get('msg') or response_payload}", level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

    def process_atpay_view(self, request, pk: int):
        try:
            wd = Withdrawal.objects.select_related('bank_account__bank', 'user', 'transaction').get(pk=pk)
        except Withdrawal.DoesNotExist:
            self.message_user(request, 'Withdrawal tidak ditemukan', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_changelist'))

        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and getattr(gs, "atpay_payout_enabled", False))
        api_url = (getattr(gs, "atpay_payout_api_url", "") or "").strip() if gs else ""
        merchant_no = (getattr(gs, "atpay_payout_merchant_no", "") or "").strip() if gs else ""
        sign_type = atpay_normalize_sign_type((getattr(gs, "atpay_payout_sign_type", "") or "MD5").strip() if gs else "MD5")
        secret_key = (getattr(gs, "atpay_payout_secret_key", "") or "").strip() if gs else ""
        private_key = (getattr(gs, "atpay_payout_private_key", "") or "").strip() if gs else ""
        public_key = (getattr(gs, "atpay_payout_public_key", "") or "").strip() if gs else ""
        app_domain = (getattr(gs, "app_domain", "") or "").strip() if gs else ""
        if not app_domain:
            try:
                from deposits.models import GatewaySettings
                ggs = GatewaySettings.objects.order_by("-updated_at").first()
                app_domain = (getattr(ggs, "app_domain", "") or "").strip() if ggs else ""
            except Exception:
                app_domain = ""

        if not enabled:
            self.message_user(request, 'ATPAY payout tidak aktif', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
        if not api_url or not merchant_no or not app_domain:
            self.message_user(request, 'Konfigurasi ATPAY payout belum lengkap', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
        if sign_type == "MD5" and not secret_key:
            self.message_user(request, 'Secret key ATPAY payout belum diisi', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
        if sign_type == "MD5withRsa" and (not private_key or not public_key):
            self.message_user(request, 'Private/Public key ATPAY payout belum lengkap', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        if request.method == "POST":
            atpay_bank_codes, atpay_bank_codes_error = _fetch_atpay_bank_codes(gs)
            atpay_bank_code_set = {
                item["bank_code"]
                for item in atpay_bank_codes
                if item.get("bank_code")
            }
            trade_account = (request.POST.get("tradeAccount") or (wd.bank_account.account_name if wd.bank_account else "")).strip()
            trade_number = (request.POST.get("tradeNumber") or (wd.bank_account.account_number if wd.bank_account else "")).strip()
            bank_code = (request.POST.get("bankCode") or (wd.bank_account.bank.code if wd.bank_account and wd.bank_account.bank else "")).strip()
            mobile = (request.POST.get("mobile") or getattr(wd.bank_account, 'phone', '') or getattr(wd.user, 'phone', '') or '').strip()
            email = (request.POST.get("email") or getattr(wd.user, 'email', '') or f"user{wd.user_id}@example.com").strip()
            identity = (request.POST.get("identity") or '').strip()
            amount_raw = (request.POST.get("amount") or '').strip() or str(wd.net_amount or wd.amount)
            attach = (request.POST.get("attach") or f"withdrawal:{wd.id}").strip()

            if not trade_account or not trade_number or not amount_raw:
                self.message_user(request, 'tradeAccount, tradeNumber, amount wajib diisi', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
            if atpay_bank_code_set and not bank_code:
                self.message_user(request, 'Bank Code ATPAY wajib dipilih', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
            if atpay_bank_code_set and bank_code not in atpay_bank_code_set:
                self.message_user(request, 'Bank Code ATPAY tidak valid', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
            if atpay_bank_codes_error and not atpay_bank_codes and bank_code:
                self.message_user(request, f'Gagal validasi daftar bank ATPAY: {atpay_bank_codes_error}', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            try:
                amount = atpay_normalize_amount(amount_raw)
                if amount <= 0:
                    raise InvalidOperation()
            except Exception:
                self.message_user(request, 'Amount tidak valid', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            out_trade_sn = wd.transaction.trx_id if wd.transaction else f"WAT{wd.id}{int(time.time())}"
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
            trace.response_payload = {"initiate": _redact_for_log(response_payload)}
            trace.save(update_fields=["response_payload"])

            if str(response_payload.get("code") or "").strip() == "100":
                wd.status = 'PROCESSING'
                wd.save(update_fields=['status'])
                self.message_user(request, f"Withdrawal #{wd.id} dikirim ke ATPAY", level=messages.SUCCESS)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            wd.status = 'REJECTED'
            wd.save(update_fields=['status'])
            self.message_user(request, f"ATPAY gagal: {response_payload.get('message') or response_payload}", level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

    def process_bankpay_view(self, request, pk: int):
        try:
            wd = Withdrawal.objects.select_related('bank_account__bank', 'user', 'transaction').get(pk=pk)
        except Withdrawal.DoesNotExist:
            self.message_user(request, 'Withdrawal tidak ditemukan', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_changelist'))

        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.bankpay_payout_enabled)
        api_url = (gs.bankpay_payout_api_url or "https://pay.bankpay.cfd").strip() if gs else ""
        member_id = (gs.bankpay_payout_member_id or "").strip() if gs else ""
        key = (gs.bankpay_payout_key or "").strip() if gs else ""
        app_domain = getattr(gs, "app_domain", "").strip() if gs else ""
        if not app_domain:
            try:
                from deposits.models import GatewaySettings
                ggs = GatewaySettings.objects.order_by("-updated_at").first()
                app_domain = (getattr(ggs, "app_domain", "") or "").strip() if ggs else ""
            except Exception:
                app_domain = ""

        if not enabled:
            self.message_user(request, 'BankPay payout tidak aktif', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
        if not api_url or not member_id or not key:
            self.message_user(request, 'Konfigurasi BankPay payout belum lengkap', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        if request.method == "POST":
            bankno = (request.POST.get("bankno") or (getattr(wd.bank_account.bank, "code", "") if wd.bank_account else "")).strip()
            bankname = (request.POST.get("bankname") or (getattr(wd.bank_account.bank, "name", "") if wd.bank_account else "")).strip()
            cardnumber = (request.POST.get("cardnumber") or (wd.bank_account.account_number if wd.bank_account else "")).strip()
            accountname = (request.POST.get("accountname") or (wd.bank_account.account_name if wd.bank_account else "")).strip()
            mobile = (request.POST.get("mobile") or getattr(wd.user, "phone", "") or "").strip()
            email = (request.POST.get("email") or getattr(wd.user, "email", "") or f"user{wd.user_id}@example.com").strip()
            amount_raw = (request.POST.get("amount") or "").strip() or str(wd.net_amount or wd.amount)

            if not cardnumber or not accountname or not amount_raw:
                self.message_user(request, 'Account Number, Account Name, Amount wajib diisi', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            try:
                amount = Decimal(str(amount_raw))
                if amount <= 0:
                    raise InvalidOperation()
            except Exception:
                self.message_user(request, 'Amount tidak valid', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            order_id = wd.transaction.trx_id if wd.transaction else f"WBP{wd.id}{int(time.time())}"
            notify_url = f"https://{app_domain}/api/withdrawals/bankpay/callback/"
            pay_amount = f"{amount:.2f}"

            payload = bankpay_build_payout_payload(
                member_id=member_id,
                order_id=order_id,
                amount=pay_amount,
                bankcode="bank",
                notify_url=notify_url,
                mobile=mobile,
                email=email,
                bank_name=bankname,
                card_number=cardnumber,
                account_name=accountname,
                bank_no=bankno,
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
                wd.status = 'PROCESSING'
                wd.save(update_fields=['status'])
                self.message_user(request, f"Withdrawal #{wd.id} dikirim ke BankPay", level=messages.SUCCESS)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            wd.status = 'REJECTED'
            wd.save(update_fields=['status'])
            self.message_user(request, f"BankPay gagal: {response_payload.get('msg') if isinstance(response_payload, dict) else response_payload}", level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

    def process_reepay_view(self, request, pk: int):
        try:
            wd = Withdrawal.objects.select_related('bank_account__bank', 'user', 'transaction').get(pk=pk)
        except Withdrawal.DoesNotExist:
            self.message_user(request, 'Withdrawal tidak ditemukan', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_changelist'))

        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.reepay_payout_enabled)
        api_url = (gs.reepay_payout_api_url or "https://api.roguecdn.online").strip() if gs else ""
        api_key = (gs.reepay_payout_api_key or "").strip() if gs else ""
        secret_key = (gs.reepay_payout_secret_key or "").strip() if gs else ""

        if not enabled:
            self.message_user(request, 'Reepay payout tidak aktif', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
        if not api_url or not api_key or not secret_key:
            self.message_user(request, 'Konfigurasi Reepay payout belum lengkap', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        if request.method == "POST":
            bank_code = (request.POST.get("bank_code") or (getattr(wd.bank_account.bank, "code", "") if wd.bank_account else "")).strip()
            destination_account = (request.POST.get("destination_account") or (wd.bank_account.account_number if wd.bank_account else "")).strip()
            account_holder_name = (request.POST.get("account_holder_name") or (wd.bank_account.account_name if wd.bank_account else "")).strip()
            amount_raw = (request.POST.get("amount") or "").strip() or str(wd.net_amount or wd.amount)

            if not destination_account or not amount_raw:
                self.message_user(request, 'Account Number dan Amount wajib diisi', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            try:
                amount = Decimal(str(amount_raw))
                if amount <= 0:
                    raise InvalidOperation()
            except Exception:
                self.message_user(request, 'Amount tidak valid', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            amount_int = int(round(float(amount)))
            merchant_ref = wd.transaction.trx_id if wd.transaction else f"WRP{wd.id}{int(time.time())}"

            payload = {
                "amount": amount_int,
                "destination_account": destination_account,
                "bank_code": bank_code,
                "account_holder_name": account_holder_name[:100],
                "merchant_ref": merchant_ref,
            }

            trace, _ = ReepayWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
            if trace and not trace.request_params:
                trace.request_params = payload
                trace.save(update_fields=["request_params"])

            resp_data, _ = reepay_post_json(api_key, secret_key, "/merchant/withdraw/create", payload, base_url=api_url)

            if trace:
                stored = trace.response_payload if isinstance(trace.response_payload, dict) else {}
                stored["initiate"] = _redact_for_log(resp_data)
                trace.response_payload = stored
                trace.save(update_fields=["response_payload"])

            if resp_data.get("success"):
                data = resp_data.get("data") if isinstance(resp_data.get("data"), dict) else {}
                ref_id = (data.get("ref_id") or "").strip()
                if ref_id:
                    note = f"Reepay ref_id: {ref_id}"
                    wd.note = f"{note}\n{wd.note}" if wd.note else note
                    wd.save(update_fields=["note"])
                wd.status = 'PROCESSING'
                wd.save(update_fields=['status'])
                self.message_user(request, f"Withdrawal #{wd.id} dikirim ke Reepay", level=messages.SUCCESS)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            detail_msg = resp_data.get("message") or resp_data.get("detail") or resp_data.get("msg") or "Reepay payout gagal"
            self.message_user(request, f"Reepay gagal: {detail_msg}", level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

    def process_batpay_view(self, request, pk: int):
        try:
            wd = Withdrawal.objects.select_related('bank_account__bank', 'user', 'transaction').get(pk=pk)
        except Withdrawal.DoesNotExist:
            self.message_user(request, 'Withdrawal tidak ditemukan', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_changelist'))

        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.batpay_payout_enabled)
        api_url = (gs.batpay_payout_api_url or "https://api.wayrooou.online").strip() if gs else ""
        api_key = (gs.batpay_payout_api_key or "").strip() if gs else ""
        secret_key = (gs.batpay_payout_secret_key or "").strip() if gs else ""

        if not enabled:
            self.message_user(request, 'BatPay payout tidak aktif', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
        if not api_url or not api_key or not secret_key:
            self.message_user(request, 'Konfigurasi BatPay payout belum lengkap', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        if request.method == "POST":
            bank_code = (request.POST.get("bank_code") or (getattr(wd.bank_account.bank, "code", "") if wd.bank_account else "")).strip()
            destination_account = (request.POST.get("destination_account") or (wd.bank_account.account_number if wd.bank_account else "")).strip()
            account_holder_name = (request.POST.get("account_holder_name") or (wd.bank_account.account_name if wd.bank_account else "")).strip()
            amount_raw = (request.POST.get("amount") or "").strip() or str(wd.net_amount or wd.amount)

            if not destination_account or not amount_raw:
                self.message_user(request, 'Account Number dan Amount wajib diisi', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            try:
                amount = Decimal(str(amount_raw))
                if amount <= 0:
                    raise InvalidOperation()
            except Exception:
                self.message_user(request, 'Amount tidak valid', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            amount_int = int(round(float(amount)))
            merchant_ref = wd.transaction.trx_id if wd.transaction else f"WBP{wd.id}{int(time.time())}"

            payload = {
                "amount": amount_int,
                "destination_account": destination_account,
                "bank_code": bank_code,
                "account_holder_name": account_holder_name[:100],
                "merchant_ref": merchant_ref,
            }

            trace, _ = BatPayWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
            if trace and not trace.request_params:
                trace.request_params = payload
                trace.save(update_fields=["request_params"])

            resp_data, _ = batpay_post_json(api_key, secret_key, "/gateway/payout/create", payload, base_url=api_url)

            if trace:
                stored = trace.response_payload if isinstance(trace.response_payload, dict) else {}
                stored["initiate"] = _redact_for_log(resp_data)
                trace.response_payload = stored
                trace.save(update_fields=["response_payload"])

            if resp_data.get("success"):
                data = resp_data.get("data") if isinstance(resp_data.get("data"), dict) else {}
                ref_id = (data.get("ref_id") or "").strip()
                if ref_id:
                    note = f"BatPay ref_id: {ref_id}"
                    wd.note = (note + chr(10) + wd.note) if wd.note else note
                    wd.save(update_fields=["note"])
                wd.status = 'PROCESSING'
                wd.save(update_fields=['status'])
                self.message_user(request, f"Withdrawal #{wd.id} dikirim ke BatPay", level=messages.SUCCESS)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            detail_msg = resp_data.get("message") or resp_data.get("detail") or resp_data.get("msg") or "BatPay payout gagal"
            self.message_user(request, f"BatPay gagal: {detail_msg}", level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
    def process_nextpay_view(self, request, pk: int):
        try:
            wd = Withdrawal.objects.select_related('bank_account__bank', 'user', 'transaction').get(pk=pk)
        except Withdrawal.DoesNotExist:
            self.message_user(request, 'Withdrawal tidak ditemukan', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_changelist'))

        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.nextpay_payout_enabled)
        api_url = (gs.nextpay_payout_api_url or "https://api.nextcdn.online").strip() if gs else ""
        api_key = (gs.nextpay_payout_api_key or "").strip() if gs else ""
        secret_key = (gs.nextpay_payout_secret_key or "").strip() if gs else ""

        if not enabled:
            self.message_user(request, 'NextPay payout tidak aktif', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))
        if not api_url or not api_key or not secret_key:
            self.message_user(request, 'Konfigurasi NextPay payout belum lengkap', level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        if request.method == "POST":
            bank_code = (request.POST.get("bank_code") or (getattr(wd.bank_account.bank, "code", "") if wd.bank_account else "")).strip()
            destination_account = (request.POST.get("destination_account") or (wd.bank_account.account_number if wd.bank_account else "")).strip()
            account_holder_name = (request.POST.get("account_holder_name") or (wd.bank_account.account_name if wd.bank_account else "")).strip()
            amount_raw = (request.POST.get("amount") or "").strip() or str(wd.net_amount or wd.amount)

            if not destination_account or not amount_raw:
                self.message_user(request, 'Account Number dan Amount wajib diisi', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            try:
                amount = Decimal(str(amount_raw))
                if amount <= 0:
                    raise InvalidOperation()
            except Exception:
                self.message_user(request, 'Amount tidak valid', level=messages.ERROR)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            amount_int = int(round(float(amount)))
            merchant_ref = wd.transaction.trx_id if wd.transaction else f"WNP{wd.id}{int(time.time())}"

            payload = {
                "amount": amount_int,
                "destination_account": destination_account,
                "bank_code": bank_code,
                "account_holder_name": account_holder_name[:100],
                "merchant_ref": merchant_ref,
            }

            trace, _ = NextPayWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
            if trace and not trace.request_params:
                trace.request_params = payload
                trace.save(update_fields=["request_params"])

            resp_data, _ = nextpay_post_json(api_key, secret_key, "/gateway/payout/create", payload, base_url=api_url)

            if trace:
                stored = trace.response_payload if isinstance(trace.response_payload, dict) else {}
                stored["initiate"] = _redact_for_log(resp_data)
                trace.response_payload = stored
                trace.save(update_fields=["response_payload"])

            if resp_data.get("success"):
                data = resp_data.get("data") if isinstance(resp_data.get("data"), dict) else {}
                ref_id = (data.get("ref_id") or "").strip()
                if ref_id:
                    note = f"NextPay ref_id: {ref_id}"
                    wd.note = (note + chr(10) + wd.note) if wd.note else note
                    wd.save(update_fields=["note"])
                wd.status = 'PROCESSING'
                wd.save(update_fields=['status'])
                self.message_user(request, f"Withdrawal #{wd.id} dikirim ke NextPay", level=messages.SUCCESS)
                return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

            detail_msg = resp_data.get("message") or resp_data.get("detail") or resp_data.get("msg") or "NextPay payout gagal"
            self.message_user(request, f"NextPay gagal: {detail_msg}", level=messages.ERROR)
            return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

        return redirect(reverse('admin:withdrawal_withdrawal_change', args=(wd.id,)))

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        if obj:
            gs = WithdrawalSettings.objects.order_by("-updated_at").first()
            atpay_bank_codes, atpay_bank_codes_error = _fetch_atpay_bank_codes(gs)
            bankpay_bank_codes, bankpay_bank_codes_error = [], ""
            if gs and gs.bankpay_payout_enabled and gs.bankpay_payout_member_id and gs.bankpay_payout_key:
                try:
                    bankpay_bank_codes, bankpay_bank_codes_error = bankpay_fetch_bank_list(
                        gs.bankpay_payout_api_url or "https://pay.bankpay.cfd",
                        gs.bankpay_payout_member_id.strip(),
                        gs.bankpay_payout_key.strip(),
                    )
                except Exception as e:
                    bankpay_bank_codes_error = str(e)
            # Daftar bank Reepay pakai daftar statis (tanpa fetch API)
            reepay_bank_codes = [
                {"bank_code": c, "bank_name": n}
                for c, n in REEPAY_FALLBACK_BANK_CODES
            ]
            # Daftar bank BatPay: fetch dari API, fallback ke daftar statis (kode sama dengan Reepay)
            batpay_bank_codes, batpay_bank_codes_error = [], ""
            if gs and gs.batpay_payout_enabled and gs.batpay_payout_api_key and gs.batpay_payout_secret_key:
                try:
                    _resp, _ = batpay_get_json(
                        (gs.batpay_payout_api_key or "").strip(),
                        (gs.batpay_payout_secret_key or "").strip(),
                        "/gateway/payout/banks",
                        base_url=(gs.batpay_payout_api_url or "https://api.wayrooou.online").strip(),
                    )
                    _items = _resp.get("data", {}).get("items") if isinstance(_resp, dict) and isinstance(_resp.get("data"), dict) else None
                    if _items:
                        batpay_bank_codes = [
                            {"bank_code": b.get("bank_code"), "bank_name": b.get("bank_name")}
                            for b in _items if b.get("bank_code")
                        ]
                except Exception as e:
                    batpay_bank_codes_error = str(e)
            if not batpay_bank_codes:
                batpay_bank_codes = [
                    {"bank_code": c, "bank_name": n}
                    for c, n in REEPAY_FALLBACK_BANK_CODES
                ]
            # Daftar bank NextPay: fetch dari API, fallback ke daftar statis (kode sama dengan Reepay)
            nextpay_bank_codes, nextpay_bank_codes_error = [], ""
            if gs and gs.nextpay_payout_enabled and gs.nextpay_payout_api_key and gs.nextpay_payout_secret_key:
                try:
                    _resp, _ = nextpay_get_json(
                        (gs.nextpay_payout_api_key or "").strip(),
                        (gs.nextpay_payout_secret_key or "").strip(),
                        "/gateway/payout/banks",
                        base_url=(gs.nextpay_payout_api_url or "https://api.nextcdn.online").strip(),
                    )
                    _items = _resp.get("data", {}).get("items") if isinstance(_resp, dict) and isinstance(_resp.get("data"), dict) else None
                    if _items:
                        nextpay_bank_codes = [
                            {"bank_code": b.get("bank_code"), "bank_name": b.get("bank_name")}
                            for b in _items if b.get("bank_code")
                        ]
                except Exception as e:
                    nextpay_bank_codes_error = str(e)
            if not nextpay_bank_codes:
                nextpay_bank_codes = [
                    {"bank_code": c, "bank_name": n}
                    for c, n in REEPAY_FALLBACK_BANK_CODES
                ]
            wd_bank_code = getattr(getattr(obj.bank_account, 'bank', None), 'code', '') or ''
            wd_bank_name = getattr(getattr(obj.bank_account, 'bank', None), 'name', '') or ''
            if wd_bank_code and not any(b["bank_code"] == wd_bank_code for b in reepay_bank_codes):
                reepay_bank_codes.insert(0, {"bank_code": wd_bank_code, "bank_name": wd_bank_name})
            reepay_bank_codes_error = ""
            atpay_bank_code_set = {
                item["bank_code"]
                for item in atpay_bank_codes
                if item.get("bank_code")
            }
            ph_allowed_codes = {b.get("bankCode") for b in (JAYAPAY_PH_PAYOUT_BANKS or []) if b.get("bankCode")}
            ph_bank_code_default = obj.bank_account.bank.code if obj.bank_account else ""
            if ph_allowed_codes and ph_bank_code_default not in ph_allowed_codes:
                ph_bank_code_default = "GCASH"
            ppaypros_code_default = obj.bank_account.bank.code if obj.bank_account and obj.bank_account.bank else ""
            if PPAYPROS_PAYOUT_CODE_SET and ppaypros_code_default not in PPAYPROS_PAYOUT_CODE_SET:
                ppaypros_code_default = ""
            atpay_code_default = obj.bank_account.bank.code if obj.bank_account and obj.bank_account.bank else ""
            if atpay_bank_code_set and atpay_code_default not in atpay_bank_code_set:
                atpay_code_default = ""
            initial = {
                'bankCode': obj.bank_account.bank.code if obj.bank_account else '',
                'accountNumber': obj.bank_account.account_number if obj.bank_account else '',
                'accountName': obj.bank_account.account_name if obj.bank_account else '',
                'amount': str(obj.net_amount or obj.amount),
            }
            context.update({
                'jayapay_initial': initial,
                'jayapay_banks': JAYAPAY_BANKS,
                'process_jayapay_url': reverse('admin:withdrawal_withdrawal_process_jayapay', args=(obj.id,)),
                'jayapay_enabled': getattr(settings, 'JAYAPAY_ENABLED', False),
                'jayapay_ph_enabled': bool(gs and getattr(gs, "jayapay_ph_payout_enabled", False)),
                'jayapay_ph_initial': {
                    'bankCode': ph_bank_code_default or 'GCASH',
                    'bankCard': obj.bank_account.account_number if obj.bank_account else '',
                    'accountName': obj.bank_account.account_name if obj.bank_account else '',
                    'amount': str(obj.net_amount or obj.amount),
                    'feeType': str(int(getattr(gs, "jayapay_ph_payout_fee_type", 1) or 1) if gs else 1),
                    'description': (obj.note or f"Withdrawal #{obj.id}")[:255],
                },
                'jayapay_ph_banks': JAYAPAY_PH_PAYOUT_BANKS,
                'process_jayapay_ph_url': reverse('admin:withdrawal_withdrawal_process_jayapay_ph', args=(obj.id,)),
                'ppaypros_enabled': bool(gs and getattr(gs, "ppaypros_payout_enabled", False)),
                'ppaypros_initial': {
                    'entryType': (getattr(gs, "ppaypros_payout_entry_type", "") or 'BANK_CARD') if gs else 'BANK_CARD',
                    'accountCode': ppaypros_code_default,
                    'accountNo': obj.bank_account.account_number if obj.bank_account else '',
                    'accountName': obj.bank_account.account_name if obj.bank_account else '',
                    'accountEmail': getattr(obj.user, 'email', '') or f"user{obj.user_id}@example.com",
                    'accountPhone': (getattr(obj.bank_account, 'phone', '') or getattr(obj.user, 'phone', '') or '').strip(),
                    'amount': str(obj.net_amount or obj.amount),
                },
                'ppaypros_wallet_codes': [item for item in PPAYPROS_PAYOUT_CODES if item.get('category') == 'wallet'],
                'ppaypros_bank_codes': [item for item in PPAYPROS_PAYOUT_CODES if item.get('category') == 'bank'],
                'process_ppaypros_url': reverse('admin:withdrawal_withdrawal_process_ppaypros', args=(obj.id,)),
                'atpay_enabled': bool(gs and getattr(gs, "atpay_payout_enabled", False)),
                'atpay_initial': {
                    'bankCode': atpay_code_default,
                    'tradeNumber': obj.bank_account.account_number if obj.bank_account else '',
                    'tradeAccount': obj.bank_account.account_name if obj.bank_account else '',
                    'mobile': (getattr(obj.bank_account, 'phone', '') or getattr(obj.user, 'phone', '') or '').strip(),
                    'email': getattr(obj.user, 'email', '') or f"user{obj.user_id}@example.com",
                    'identity': '',
                    'amount': str(obj.net_amount or obj.amount),
                    'attach': f"withdrawal:{obj.id}",
                },
                'atpay_bank_codes': atpay_bank_codes,
                'atpay_bank_codes_error': atpay_bank_codes_error,
                'process_atpay_url': reverse('admin:withdrawal_withdrawal_process_atpay', args=(obj.id,)),
                'usd_payout_initial': {
                    'bankCode': '',
                    'accNo': obj.bank_account.account_number if obj.bank_account else '',
                    'accName': obj.bank_account.account_name if obj.bank_account else '',
                    'email': getattr(obj.user, 'email', '') or f"user{obj.user_id}@example.com",
                    'phone': (getattr(obj.bank_account, 'phone', '') or getattr(obj.user, 'phone', '') or '').strip(),
                    'orderAmount': str(obj.net_amount or obj.amount),
                },
                'usd_payout_bank_codes': [{"code": c[0], "name": c[1]} for c in USD_PAYOUT_BANK_CODE_CHOICES],
                'process_usd_payout_url': reverse('admin:withdrawal_withdrawal_process_usd_payout', args=(obj.id,)),
                'usd_payout_enabled': getattr(settings, 'USD_PAYOUT_ENABLED', False),
                'bankpay_payout_enabled': bool(gs and gs.bankpay_payout_enabled),
                'bankpay_payout_member_id': (gs.bankpay_payout_member_id or "").strip() if gs else "",
                'bankpay_bank_codes': bankpay_bank_codes,
                'bankpay_bank_codes_error': bankpay_bank_codes_error,
                'bankpay_payout_initial': {
                    'bankcode': getattr(getattr(obj.bank_account, 'bank', None), 'code', '') or '',
                    'cardnumber': obj.bank_account.account_number if obj.bank_account else '',
                    'accountname': obj.bank_account.account_name if obj.bank_account else '',
                    'bankname': getattr(getattr(obj.bank_account, 'bank', None), 'name', '') or '',
                    'bankno': getattr(getattr(obj.bank_account, 'bank', None), 'code', '') or '',
                    'mobile': (getattr(obj.bank_account, 'phone', '') or getattr(obj.user, 'phone', '') or '').strip(),
                    'email': getattr(obj.user, 'email', '') or f"user{obj.user_id}@example.com",
                    'amount': str(obj.net_amount or obj.amount),
                },
                'process_bankpay_url': reverse('admin:withdrawal_withdrawal_process_bankpay', args=(obj.id,)),
                'reepay_payout_enabled': bool(gs and gs.reepay_payout_enabled),
                'reepay_bank_codes': reepay_bank_codes,
                'reepay_bank_codes_error': reepay_bank_codes_error,
                'reepay_payout_initial': {
                    'bank_code': getattr(getattr(obj.bank_account, 'bank', None), 'code', '') or '',
                    'destination_account': obj.bank_account.account_number if obj.bank_account else '',
                    'account_holder_name': obj.bank_account.account_name if obj.bank_account else '',
                    'amount': str(obj.net_amount or obj.amount),
                },
                'process_reepay_url': reverse('admin:withdrawal_withdrawal_process_reepay', args=(obj.id,)),
                'batpay_payout_enabled': bool(gs and gs.batpay_payout_enabled),
                'batpay_bank_codes': batpay_bank_codes,
                'batpay_bank_codes_error': batpay_bank_codes_error,
                'batpay_payout_initial': {
                    'bank_code': getattr(getattr(obj.bank_account, 'bank', None), 'code', '') or '',
                    'destination_account': obj.bank_account.account_number if obj.bank_account else '',
                    'account_holder_name': obj.bank_account.account_name if obj.bank_account else '',
                    'amount': str(obj.net_amount or obj.amount),
                },
                'process_batpay_url': reverse('admin:withdrawal_withdrawal_process_batpay', args=(obj.id,)),
                'nextpay_payout_enabled': bool(gs and gs.nextpay_payout_enabled),
                'nextpay_bank_codes': nextpay_bank_codes,
                'nextpay_bank_codes_error': nextpay_bank_codes_error,
                'nextpay_payout_initial': {
                    'bank_code': getattr(getattr(obj.bank_account, 'bank', None), 'code', '') or '',
                    'destination_account': obj.bank_account.account_number if obj.bank_account else '',
                    'account_holder_name': obj.bank_account.account_name if obj.bank_account else '',
                    'amount': str(obj.net_amount or obj.amount),
                },
                'process_nextpay_url': reverse('admin:withdrawal_withdrawal_process_nextpay', args=(obj.id,)),
            })
        return super().render_change_form(request, context, add, change, form_url, obj)

    def process_withdrawal_jayapay(self, request, queryset):
        if not getattr(settings, 'JAYAPAY_ENABLED', False):
            self.message_user(request, 'Jayapay tidak aktif (JAYAPAY_ENABLED=false)', level=messages.ERROR)
            return
        if not settings.JAYAPAY_MERCHANT_CODE or not settings.JAYAPAY_PRIVATE_KEY:
            self.message_user(request, 'Konfigurasi Jayapay belum lengkap', level=messages.ERROR)
            return

        processed = 0
        for wd in queryset.select_related('bank_account__bank'):
            if wd.status not in ('PENDING', 'PROCESSING'):
                self.message_user(request, f"Withdrawal #{wd.id} dilewati: status {wd.status}", level=messages.WARNING)
                continue
            if not wd.bank_account:
                self.message_user(request, f"Withdrawal #{wd.id} gagal: tidak ada bank_account", level=messages.ERROR)
                continue

            bank = wd.bank_account.bank
            try:
                params = build_params(
                    wd,
                    merchant_code=settings.JAYAPAY_MERCHANT_CODE,
                    bank_code=bank.code,
                    account_number=wd.bank_account.account_number,
                    account_name=wd.bank_account.account_name,
                    notify_url=settings.JAYAPAY_NOTIFY_URL,
                )
                params['sign'] = sign_params(params, settings.JAYAPAY_PRIVATE_KEY)
                resp = send_cash_request(params)
                # Persist traceability for bulk action
                try:
                    jp_withdrawal, _ = WithdrawalJayapay.objects.get_or_create(
                        withdrawal=wd,
                        defaults={"request_params": params}
                    )
                    if jp_withdrawal and not jp_withdrawal.request_params:
                        jp_withdrawal.request_params = params
                        jp_withdrawal.response_payload = resp
                        jp_withdrawal.save(update_fields=['request_params', 'response_payload'])
                    else:
                        jp_withdrawal.response_payload = resp
                        jp_withdrawal.save(update_fields=['response_payload'])
                except Exception:
                    pass
                wd.status = 'PROCESSING'
                wd.save()
                processed += 1
                self.message_user(request, f"Withdrawal #{wd.id} dikirim ke Jayapay", level=messages.SUCCESS)
            except Exception as e:
                self.message_user(request, f"Withdrawal #{wd.id} gagal dikirim: {e}", level=messages.ERROR)

        if processed:
            self.message_user(request, f"Berhasil memproses {processed} withdrawal via Jayapay.", level=messages.SUCCESS)
    process_withdrawal_jayapay.short_description = 'Process via Jayapay'

    def process_withdrawal_bankpay(self, request, queryset):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.bankpay_payout_enabled)
        api_url = (gs.bankpay_payout_api_url or "https://pay.bankpay.cfd").strip() if gs else ""
        member_id = (gs.bankpay_payout_member_id or "").strip() if gs else ""
        key = (gs.bankpay_payout_key or "").strip() if gs else ""
        app_domain = getattr(gs, "app_domain", "").strip() if gs else ""

        if not enabled:
            self.message_user(request, 'BankPay payout tidak aktif', level=messages.ERROR)
            return
        if not api_url or not member_id or not key:
            self.message_user(request, 'Konfigurasi BankPay payout belum lengkap', level=messages.ERROR)
            return

        processed = 0
        for wd in queryset.select_related('bank_account__bank', 'transaction'):
            if wd.status not in ('PENDING', 'PROCESSING'):
                self.message_user(request, f"Withdrawal #{wd.id} dilewati: status {wd.status}", level=messages.WARNING)
                continue
            if not wd.bank_account:
                self.message_user(request, f"Withdrawal #{wd.id} gagal: tidak ada bank_account", level=messages.ERROR)
                continue

            bank = wd.bank_account.bank
            account_no = wd.bank_account.account_number or ""
            account_name = wd.bank_account.account_name or ""
            bank_name_str = getattr(bank, "name", "") or ""
            bank_code = getattr(bank, "code", "") or ""

            try:
                order_id = getattr(getattr(wd, "transaction", None), "trx_id", None) or f"WBP{wd.pk}{int(time.time())}"
                notify_url = f"https://{app_domain}/api/withdrawals/bankpay/callback/"
                # Use withdrawal net amount
                net = wd.net_amount if wd.net_amount and wd.net_amount > 0 else (wd.amount - wd.fee if wd.fee else wd.amount)
                pay_amount = f"{net:.2f}" if net else f"{wd.amount:.2f}"

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

                resp = bankpay_post_form(f"{api_url.rstrip('/')}/Pay-payment-draw.aspx", payload)

                trace, _ = BankPayWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
                if trace:
                    if not trace.request_params:
                        trace.request_params = payload
                    stored = trace.response_payload or {}
                    stored["initiate"] = resp
                    trace.response_payload = stored
                    trace.save(update_fields=["request_params", "response_payload"])

                wd.status = 'PROCESSING'
                wd.save()
                processed += 1
                self.message_user(request, f"Withdrawal #{wd.id} dikirim ke BankPay", level=messages.SUCCESS)
            except Exception as e:
                self.message_user(request, f"Withdrawal #{wd.id} gagal dikirim: {e}", level=messages.ERROR)

        if processed:
            self.message_user(request, f"Berhasil memproses {processed} withdrawal via BankPay.", level=messages.SUCCESS)
    process_withdrawal_bankpay.short_description = 'Process via BankPay'

    def process_withdrawal_reepay(self, request, queryset):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.reepay_payout_enabled)
        api_url = (gs.reepay_payout_api_url or "https://api.roguecdn.online").strip() if gs else ""
        api_key = (gs.reepay_payout_api_key or "").strip() if gs else ""
        secret_key = (gs.reepay_payout_secret_key or "").strip() if gs else ""

        if not enabled:
            self.message_user(request, 'Reepay payout tidak aktif', level=messages.ERROR)
            return
        if not api_url or not api_key or not secret_key:
            self.message_user(request, 'Konfigurasi Reepay payout belum lengkap', level=messages.ERROR)
            return

        processed = 0
        for wd in queryset.select_related('bank_account__bank', 'transaction'):
            if wd.status not in ('PENDING', 'PROCESSING'):
                self.message_user(request, f"Withdrawal #{wd.id} dilewati: status {wd.status}", level=messages.WARNING)
                continue
            if not wd.bank_account:
                self.message_user(request, f"Withdrawal #{wd.id} gagal: tidak ada bank_account", level=messages.ERROR)
                continue

            try:
                bank = wd.bank_account.bank
                account_no = wd.bank_account.account_number or ""
                account_name = wd.bank_account.account_name or ""
                bank_code = getattr(bank, "code", "") or ""
                net = wd.net_amount if wd.net_amount and wd.net_amount > 0 else (wd.amount - wd.fee if wd.fee else wd.amount)
                amount_int = int(round(float(net if net else wd.amount)))
                merchant_ref = getattr(getattr(wd, "transaction", None), "trx_id", None) or f"WRP{wd.pk}{int(time.time())}"

                payload = {
                    "amount": amount_int,
                    "destination_account": account_no,
                    "bank_code": bank_code,
                    "account_holder_name": account_name[:100],
                    "merchant_ref": merchant_ref,
                }

                resp, _ = reepay_post_json(api_key, secret_key, "/merchant/withdraw/create", payload, base_url=api_url)

                trace, _ = ReepayWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
                if trace:
                    if not trace.request_params:
                        trace.request_params = payload
                    stored = trace.response_payload if isinstance(trace.response_payload, dict) else {}
                    stored["initiate"] = _redact_for_log(resp)
                    trace.response_payload = stored
                    trace.save(update_fields=["request_params", "response_payload"])

                if resp.get("success"):
                    wd.status = 'PROCESSING'
                    wd.save()
                    processed += 1
                    self.message_user(request, f"Withdrawal #{wd.id} dikirim ke Reepay", level=messages.SUCCESS)
                else:
                    self.message_user(request, f"Withdrawal #{wd.id} gagal: {resp.get('message') or resp.get('detail') or resp.get('msg') or resp}", level=messages.ERROR)
            except Exception as e:
                self.message_user(request, f"Withdrawal #{wd.id} gagal dikirim: {e}", level=messages.ERROR)

        if processed:
            self.message_user(request, f"Berhasil memproses {processed} withdrawal via Reepay.", level=messages.SUCCESS)
    process_withdrawal_reepay.short_description = 'Process via Reepay'

    def process_withdrawal_batpay(self, request, queryset):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.batpay_payout_enabled)
        api_url = (gs.batpay_payout_api_url or "https://api.wayrooou.online").strip() if gs else ""
        api_key = (gs.batpay_payout_api_key or "").strip() if gs else ""
        secret_key = (gs.batpay_payout_secret_key or "").strip() if gs else ""

        if not enabled:
            self.message_user(request, 'BatPay payout tidak aktif', level=messages.ERROR)
            return
        if not api_url or not api_key or not secret_key:
            self.message_user(request, 'Konfigurasi BatPay payout belum lengkap', level=messages.ERROR)
            return

        processed = 0
        for wd in queryset.select_related('bank_account__bank', 'transaction'):
            if wd.status not in ('PENDING', 'PROCESSING'):
                self.message_user(request, f"Withdrawal #{wd.id} dilewati: status {wd.status}", level=messages.WARNING)
                continue
            if not wd.bank_account:
                self.message_user(request, f"Withdrawal #{wd.id} gagal: tidak ada bank_account", level=messages.ERROR)
                continue

            try:
                bank = wd.bank_account.bank
                account_no = wd.bank_account.account_number or ""
                account_name = wd.bank_account.account_name or ""
                bank_code = getattr(bank, "code", "") or ""
                net = wd.net_amount if wd.net_amount and wd.net_amount > 0 else (wd.amount - wd.fee if wd.fee else wd.amount)
                amount_int = int(round(float(net if net else wd.amount)))
                merchant_ref = getattr(getattr(wd, "transaction", None), "trx_id", None) or f"WBP{wd.pk}{int(time.time())}"

                payload = {
                    "amount": amount_int,
                    "destination_account": account_no,
                    "bank_code": bank_code,
                    "account_holder_name": account_name[:100],
                    "merchant_ref": merchant_ref,
                }

                resp, _ = batpay_post_json(api_key, secret_key, "/gateway/payout/create", payload, base_url=api_url)

                trace, _ = BatPayWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
                if trace:
                    if not trace.request_params:
                        trace.request_params = payload
                    stored = trace.response_payload if isinstance(trace.response_payload, dict) else {}
                    stored["initiate"] = _redact_for_log(resp)
                    trace.response_payload = stored
                    trace.save(update_fields=["request_params", "response_payload"])

                if resp.get("success"):
                    wd.status = 'PROCESSING'
                    wd.save()
                    processed += 1
                    self.message_user(request, f"Withdrawal #{wd.id} dikirim ke BatPay", level=messages.SUCCESS)
                else:
                    self.message_user(request, f"Withdrawal #{wd.id} gagal: {resp.get('message') or resp.get('detail') or resp.get('msg') or resp}", level=messages.ERROR)
            except Exception as e:
                self.message_user(request, f"Withdrawal #{wd.id} gagal dikirim: {e}", level=messages.ERROR)

        if processed:
            self.message_user(request, f"Berhasil memproses {processed} withdrawal via BatPay.", level=messages.SUCCESS)
    def process_withdrawal_nextpay(self, request, queryset):
        gs = WithdrawalSettings.objects.order_by("-updated_at").first()
        enabled = bool(gs and gs.nextpay_payout_enabled)
        api_url = (gs.nextpay_payout_api_url or "https://api.nextcdn.online").strip() if gs else ""
        api_key = (gs.nextpay_payout_api_key or "").strip() if gs else ""
        secret_key = (gs.nextpay_payout_secret_key or "").strip() if gs else ""

        if not enabled:
            self.message_user(request, 'NextPay payout tidak aktif', level=messages.ERROR)
            return
        if not api_url or not api_key or not secret_key:
            self.message_user(request, 'Konfigurasi NextPay payout belum lengkap', level=messages.ERROR)
            return

        processed = 0
        for wd in queryset.select_related('bank_account__bank', 'transaction'):
            if wd.status not in ('PENDING', 'PROCESSING'):
                self.message_user(request, f"Withdrawal #{wd.id} dilewati: status {wd.status}", level=messages.WARNING)
                continue
            if not wd.bank_account:
                self.message_user(request, f"Withdrawal #{wd.id} gagal: tidak ada bank_account", level=messages.ERROR)
                continue

            try:
                bank = wd.bank_account.bank
                account_no = wd.bank_account.account_number or ""
                account_name = wd.bank_account.account_name or ""
                bank_code = getattr(bank, "code", "") or ""
                net = wd.net_amount if wd.net_amount and wd.net_amount > 0 else (wd.amount - wd.fee if wd.fee else wd.amount)
                amount_int = int(round(float(net if net else wd.amount)))
                merchant_ref = getattr(getattr(wd, "transaction", None), "trx_id", None) or f"WNP{wd.pk}{int(time.time())}"

                payload = {
                    "amount": amount_int,
                    "destination_account": account_no,
                    "bank_code": bank_code,
                    "account_holder_name": account_name[:100],
                    "merchant_ref": merchant_ref,
                }

                resp, _ = nextpay_post_json(api_key, secret_key, "/gateway/payout/create", payload, base_url=api_url)

                trace, _ = NextPayWithdrawal.objects.get_or_create(withdrawal=wd, defaults={"request_params": payload})
                if trace:
                    if not trace.request_params:
                        trace.request_params = payload
                    stored = trace.response_payload if isinstance(trace.response_payload, dict) else {}
                    stored["initiate"] = _redact_for_log(resp)
                    trace.response_payload = stored
                    trace.save(update_fields=["request_params", "response_payload"])

                if resp.get("success"):
                    wd.status = 'PROCESSING'
                    wd.save()
                    processed += 1
                    self.message_user(request, f"Withdrawal #{wd.id} dikirim ke NextPay", level=messages.SUCCESS)
                else:
                    self.message_user(request, f"Withdrawal #{wd.id} gagal: {resp.get('message') or resp.get('detail') or resp.get('msg') or resp}", level=messages.ERROR)
            except Exception as e:
                self.message_user(request, f"Withdrawal #{wd.id} gagal dikirim: {e}", level=messages.ERROR)

        if processed:
            self.message_user(request, f"Berhasil memproses {processed} withdrawal via NextPay.", level=messages.SUCCESS)
    process_withdrawal_batpay.short_description = 'Process via BatPay'


@admin.register(WithdrawalJayapay)
class WithdrawalJayapayAdmin(WithdrawalAdmin):
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(status__in=['PENDING', 'PROCESSING'])


@admin.register(WithdrawalSettings)
class WithdrawalSettingsAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'is_active',
        'max_withdrawal_count',
        'balance_source',
        'require_bank_account',
        'require_pin',
        'require_active_investment',
        'require_withdraw_service',
        'jayapay_enabled',
        'jayapay_ph_payout_enabled',
        'ppaypros_payout_enabled',
        'atpay_payout_enabled',
        'bankpay_payout_enabled',
        'reepay_payout_enabled',
        'batpay_payout_enabled',
        'nextpay_payout_enabled',
        'updated_at',
    )
    list_filter = ('is_active',)
    search_fields = ('required_product__name',)
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Global', {
            'description': (
                'Gunakan `is_active` untuk ON/OFF withdraw dari admin. Jika OFF, semua user tidak bisa melakukan withdraw. '
                '`Max withdrawal count` membatasi total request withdraw per user. '
                'Nilai 0 berarti tanpa batas. '
                'Jika `Require active investment` diaktifkan, user hanya boleh withdraw bila masih punya '
                'produk/investment dengan status ACTIVE yang benar-benar masih berjalan. '
                'Produk yang siklusnya sudah habis atau sudah completed/expired tidak dihitung.'
            ),
            'fields': (
                'is_active',
                'max_withdrawal_count',
                'balance_source',
                'require_bank_account',
                'require_pin',
                'require_active_investment',
                'require_withdraw_service',
                'minimum_product_quantity',
                'required_product',
            )
        }),
        ('Callback Domain', {
            'fields': ('app_domain',),
        }),
        ('Jayapay', {
            'fields': (
                'jayapay_enabled',
                'jayapay_merchant_code',
                'jayapay_private_key',
                'jayapay_public_key',
            )
        }),
        ('Jayapay PH Payout', {
            'fields': (
                'jayapay_ph_payout_enabled',
                'jayapay_ph_payout_mch_no',
                'jayapay_ph_payout_private_key',
                'jayapay_ph_payout_public_key',
                'jayapay_ph_payout_api_url',
                'jayapay_ph_payout_fee_type',
            )
        }),
        ('PPay Pros Payout', {
            'fields': (
                'ppaypros_payout_enabled',
                'ppaypros_payout_api_url',
                'ppaypros_payout_mch_no',
                'ppaypros_payout_app_id',
                'ppaypros_payout_private_key',
                'ppaypros_payout_entry_type',
            )
        }),
        ('ATPAY Payout', {
            'fields': (
                'atpay_payout_enabled',
                'atpay_payout_api_url',
                'atpay_payout_merchant_no',
                'atpay_payout_sign_type',
                'atpay_payout_secret_key',
                'atpay_payout_private_key',
                'atpay_payout_public_key',
            )
        }),
        ('BankPay Payout', {
            'fields': (
                'bankpay_payout_enabled',
                'bankpay_payout_api_url',
                'bankpay_payout_member_id',
                'bankpay_payout_key',
            )
        }),
        ('Reepay Payout', {
            'fields': (
                'reepay_payout_enabled',
                'reepay_payout_api_url',
                'reepay_payout_api_key',
                'reepay_payout_secret_key',
            )
        }),
        ('BatPay Payout', {
            'fields': (
                'batpay_payout_enabled',
                'batpay_payout_api_url',
                'batpay_payout_api_key',
                'batpay_payout_secret_key',
            )
        }),
        ('NextPay Payout', {
            'fields': (
                'nextpay_payout_enabled',
                'nextpay_payout_api_url',
                'nextpay_payout_api_key',
                'nextpay_payout_secret_key',
            )
        }),
    )


@admin.register(WithdrawalService)
class WithdrawalServiceAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'name',
        'duration_hours',
        'fee_percent',
        'fee_fixed',
        'is_active',
        'sort_order',
        'updated_at',
    )
    list_filter = ('is_active',)
    search_fields = ('name',)
    readonly_fields = ('created_at', 'updated_at')
