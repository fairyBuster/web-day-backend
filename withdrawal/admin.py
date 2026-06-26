from django.contrib import admin, messages
from django.conf import settings
from django.urls import path, reverse
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from .models import Withdrawal, WithdrawalSettings, WithdrawalJayapay, WithdrawalService, UsdPayoutWithdrawal, JayapayPhPayoutWithdrawal
from .integrations.jayapay import build_params, sign_params, sign_params_legacy, send_cash_request
from .integrations.jayapay_banks import JAYAPAY_BANKS
from .integrations.jayapay_ph_banks import JAYAPAY_PH_PAYOUT_BANKS
from .integrations.usd_payout import build_payload as usd_build_payload, sign_hmac_sha256_then_rsa_base64, send_single_order
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


@admin.register(Withdrawal)
class WithdrawalAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'user', 'bank_account', 'withdrawal_service', 'amount', 'fee', 'net_amount', 'status_display', 'created_at'
    )
    list_filter = ('status', 'created_at')
    search_fields = ('user__phone', 'bank_account__account_number')
    readonly_fields = ('created_at', 'updated_at')
    actions = ['process_withdrawal_jayapay']
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

    def render_change_form(self, request, context, add=False, change=False, form_url='', obj=None):
        if obj:
            gs = WithdrawalSettings.objects.order_by("-updated_at").first()
            ph_allowed_codes = {b.get("bankCode") for b in (JAYAPAY_PH_PAYOUT_BANKS or []) if b.get("bankCode")}
            ph_bank_code_default = obj.bank_account.bank.code if obj.bank_account else ""
            if ph_allowed_codes and ph_bank_code_default not in ph_allowed_codes:
                ph_bank_code_default = "GCASH"
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
