from django.contrib import admin
from .models import GatewaySettings, Deposit, QRISGateway
from django.contrib import messages
from django.db import transaction as db_transaction
from django.utils import timezone


@admin.register(GatewaySettings)
class GatewaySettingsAdmin(admin.ModelAdmin):
    list_display = (
        'default_wallet_type', 'app_domain', 'min_deposit_amount', 'max_deposit_amount', 'usd_gateway_min_deposit_amount', 'usd_gateway_max_deposit_amount', 'jayapay_enabled', 'jayapay_ph_enabled', 'klikpay_enabled', 'usd_gateway_enabled', 'ppaypros_enabled', 'clienthub_enabled', 'sitransferhub_enabled', 'atpay_enabled', 'bankpay_enabled', 'qris_enabled', 'reepay_enabled', 'batpay_enabled', 'nextpay_enabled', 'updated_at'
    )
    readonly_fields = ('updated_at',)

    def has_add_permission(self, request):
        # Singleton: jangan izinkan tambah record baru kalau sudah ada
        return not GatewaySettings.objects.exists()
    fieldsets = (
        ('Global', {
            'fields': ('default_wallet_type', 'app_domain', 'min_deposit_amount', 'max_deposit_amount', 'jayapay_enabled', 'jayapay_ph_enabled', 'klikpay_enabled', 'usd_gateway_enabled', 'ppaypros_enabled', 'clienthub_enabled', 'sitransferhub_enabled', 'atpay_enabled', 'bankpay_enabled', 'qris_enabled', 'reepay_enabled', 'batpay_enabled', 'nextpay_enabled')
        }),
        ('Jayapay', {
            'fields': (
                'jayapay_merchant_code',
                'jayapay_private_key',
                'jayapay_public_key',
                'jayapay_api_url',
                'jayapay_callback_path',
                'jayapay_redirect_url',
            ),
            'description': 'Konfigurasi Jayapay (merchant code, keys, API URL, callback path, redirect URL).'
        }),
        ('Jayapay PH', {
            'fields': (
                'jayapay_ph_mch_no',
                'jayapay_ph_private_key',
                'jayapay_ph_public_key',
                'jayapay_ph_api_url',
                'jayapay_ph_default_method',
                'jayapay_ph_redirect_url',
            ),
            'description': 'Konfigurasi Jayapay Philippines Pay-In (prePay). downNotifyUrl mengikuti app_domain dan endpoint callback.',
        }),
        ('Klikpay', {
            'fields': (
                'klikpay_api_url',
                'klikpay_merchant_code',
                'klikpay_secret_key',
                'klikpay_private_key',
                'klikpay_public_key',
                'klikpay_callback_path',
                'klikpay_redirect_url',
            ),
            'description': 'Konfigurasi Klikpay (API URL, merchant code, keys, callback path, redirect URL).'
        }),
        ('USD Gateway', {
            'fields': (
                'usd_gateway_api_url',
                'usd_gateway_mer_no',
                'usd_gateway_sign_key',
                'usd_gateway_busi_code',
                'usd_gateway_bank_code',
                'usd_gateway_redirect_url',
                'usd_gateway_min_deposit_amount',
                'usd_gateway_max_deposit_amount',
            ),
            'description': 'Konfigurasi gateway USD (createOrder). Redirect URL digunakan sebagai pageUrl.',
        }),
        ('PPay Pros', {
            'fields': (
                'ppaypros_api_url',
                'ppaypros_mch_no',
                'ppaypros_app_id',
                'ppaypros_private_key',
                'ppaypros_way_code',
                'ppaypros_ext_param',
                'ppaypros_return_url',
            ),
            'description': 'Konfigurasi PPay Pros untuk payin/deposit. Callback memakai app_domain dan endpoint statis.',
        }),
        ('ClientHub', {
            'fields': (
                'clienthub_base_url',
                'clienthub_client_id',
                'clienthub_secret_key',
                'clienthub_method',
                'clienthub_return_url',
                'clienthub_expired_minutes',
            ),
            'description': 'Konfigurasi ClientHub/Tripay Hub. Signature request dan callback memakai HMAC SHA256 sesuai `clienthub.md`.',
        }),
        ('SiTransfer Hub', {
            'fields': (
                'sitransferhub_base_url',
                'sitransferhub_client_id',
                'sitransferhub_secret_key',
                'sitransferhub_channel',
            ),
            'description': 'Konfigurasi SiTransfer Hub. Signature request dan callback memakai HMAC SHA256 sesuai `clienthubqris.md`.',
        }),
        ('ATPAY', {
            'fields': (
                'atpay_api_url',
                'atpay_merchant_no',
                'atpay_sign_type',
                'atpay_secret_key',
                'atpay_private_key',
                'atpay_public_key',
                'atpay_return_url',
            ),
            'description': 'Konfigurasi ATPAY untuk deposit. Pilih `MD5` atau `MD5withRsa` sesuai kredensial merchant.',
        }),
        ('BankPay', {
            'fields': (
                'bankpay_api_url',
                'bankpay_member_id',
                'bankpay_key',
                'bankpay_return_url',
            ),
            'description': 'Konfigurasi BankPay untuk deposit IDR. Sign MD5, callback return OK plain text.',
        }),
        ('QRIS Manual', {
            'fields': (
                'qris_min_deposit_amount',
                'qris_max_deposit_amount',
                'qris_expired_minutes',
            ),
            'description': 'QRIS Manual: upload QR static di menu QRIS Gateway, sistem akan konversi ke dynamic saat deposit.',
        }),
        ('Reepay', {
            'fields': (
                'reepay_api_url',
                'reepay_api_key',
                'reepay_secret_key',
                'reepay_return_url',
            ),
            'description': 'Konfigurasi Reepay (RogueCDN). Auth HMAC-SHA256 via header X-API-Key, X-Timestamp, X-Signature.',
        }),
        ('BatPay', {
            'fields': (
                'batpay_api_url',
                'batpay_api_key',
                'batpay_secret_key',
                'batpay_return_url',
            ),
            'description': 'Konfigurasi BatPay (api.wayrooou.online). Auth HMAC-SHA256 via header X-API-Key, X-Timestamp, X-Signature (sama seperti Reepay). Secret key panjang (347 karakter).',
        }),
        ('NextPay', {
            'fields': (
                'nextpay_api_url',
                'nextpay_api_key',
                'nextpay_secret_key',
                'nextpay_return_url',
            ),
            'description': 'Konfigurasi NextPay (api.nextcdn.online). Auth HMAC-SHA256 via header X-API-Key, X-Timestamp, X-Signature (sama seperti Reepay). Secret key panjang (347 karakter).',
        }),
    )


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


@admin.register(Deposit)
class DepositAdmin(admin.ModelAdmin):
    list_display = ('order_num', 'user', 'gateway', 'amount_display', 'unique_code', 'amount_currency_code', 'credited_amount', 'credited_currency_code', 'wallet_type', 'status', 'expired_status', 'created_at')
    list_filter = ('gateway', 'status', 'wallet_type')
    search_fields = ('order_num', 'user__phone', 'user__username')
    readonly_fields = ('created_at', 'updated_at', 'payment_url', 'request_params', 'response_payload', 'callback_payload', 'callback_at', 'expired_at')
    autocomplete_fields = ('user', 'transaction')
    list_select_related = ('user', 'transaction')
    actions = ['accept_qris_deposit', 'reject_qris_deposit']

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'transaction')

    @admin.display(description='Jumlah', ordering='amount')
    def amount_display(self, obj):
        val = obj.display_amount
        if obj.gateway == 'QRIS' and obj.unique_code:
            return f'Rp {val:,.0f} (kode: {obj.unique_code})'
        return f'Rp {val:,.0f}'

    @admin.display(description='Kode Unik', ordering='request_params')
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
        from deposits.views import _ppaypros_complete_deposit
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
                _ppaypros_complete_deposit(trx, dep)
                dep.callback_payload = {
                    "accepted_by": request.user.username,
                    "accepted_at": timezone.now().isoformat(),
                    "method": "admin_bulk_accept",
                }
                dep.callback_at = timezone.now()
                dep.save(update_fields=['callback_payload', 'callback_at'])
                accepted += 1
        if accepted:
            msg = f'{accepted} deposit QRIS berhasil diterima, saldo user sudah di-credit.'
            if skipped_expired:
                msg += f' {skipped_expired} deposit expired dilewati.'
            self.message_user(request, msg, messages.SUCCESS)
        else:
            msg = 'Tidak ada deposit QRIS pending yang bisa diterima.'
            if skipped_expired:
                msg += f' ({skipped_expired} expired).'
            self.message_user(request, msg, messages.WARNING)

    @admin.action(description='Tolak deposit QRIS')
    def reject_qris_deposit(self, request, queryset):
        from deposits.views import _ppaypros_mark_deposit_failed
        rejected = 0
        for dep in queryset.filter(gateway='QRIS', status='PENDING'):
            trx = dep.transaction
            if not trx:
                continue
            _ppaypros_mark_deposit_failed(trx, dep, reason='Ditolak admin')
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
            self.message_user(request, 'Tidak ada deposit QRIS pending yang bisa ditolak.', messages.WARNING)
