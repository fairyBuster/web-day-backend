from django.contrib import admin
from .models import GatewaySettings, Deposit


@admin.register(GatewaySettings)
class GatewaySettingsAdmin(admin.ModelAdmin):
    list_display = (
        'default_wallet_type', 'app_domain', 'min_deposit_amount', 'max_deposit_amount', 'usd_gateway_min_deposit_amount', 'usd_gateway_max_deposit_amount', 'jayapay_enabled', 'jayapay_ph_enabled', 'klikpay_enabled', 'usd_gateway_enabled', 'ppaypros_enabled', 'updated_at'
    )
    readonly_fields = ('updated_at',)
    fieldsets = (
        ('Global', {
            'fields': ('default_wallet_type', 'app_domain', 'min_deposit_amount', 'max_deposit_amount', 'jayapay_enabled', 'jayapay_ph_enabled', 'klikpay_enabled', 'usd_gateway_enabled', 'ppaypros_enabled')
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
    )


@admin.register(Deposit)
class DepositAdmin(admin.ModelAdmin):
    list_display = ('order_num', 'user', 'gateway', 'amount', 'amount_currency_code', 'credited_amount', 'credited_currency_code', 'wallet_type', 'status', 'created_at')
    list_filter = ('gateway', 'status', 'wallet_type')
    search_fields = ('order_num', 'user__phone', 'user__username')
    readonly_fields = ('created_at', 'updated_at', 'payment_url', 'request_params', 'response_payload', 'callback_payload', 'callback_at')
    autocomplete_fields = ('user', 'transaction')
    list_select_related = ('user', 'transaction')

    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'transaction')
