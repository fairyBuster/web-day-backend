from django.db import models
from django.conf import settings
from products.models import Transaction


class GatewaySettings(models.Model):
    WALLET_CHOICES = [
        ('BALANCE', 'Balance'),
        ('BALANCE_DEPOSIT', 'Balance Deposit'),
    ]

    # Global controls
    default_wallet_type = models.CharField(max_length=20, choices=WALLET_CHOICES, default='BALANCE')
    app_domain = models.CharField(max_length=255, blank=True, default='', help_text='Contoh: myapp.example.com (tanpa http/https)')
    min_deposit_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text='Minimal nominal deposit (0 = tidak dibatasi)')
    max_deposit_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text='Maksimal nominal deposit (0 = tidak dibatasi)')
    jayapay_enabled = models.BooleanField(default=True)
    klikpay_enabled = models.BooleanField(default=False)
    usd_gateway_enabled = models.BooleanField(default=False)
    ppaypros_enabled = models.BooleanField(default=False)

    # Jayapay config
    jayapay_merchant_code = models.CharField(max_length=100, blank=True, default='')
    jayapay_private_key = models.TextField(blank=True, default='', help_text='Paste RSA PRIVATE KEY body ONLY (without BEGIN/END headers)')
    jayapay_public_key = models.TextField(blank=True, default='', help_text='Optional: PUBLIC KEY untuk verifikasi/dekripsi callback bila diperlukan')
    jayapay_api_url = models.CharField(max_length=255, blank=True, default='')
    jayapay_callback_path = models.CharField(max_length=255, blank=True, default='', help_text='Contoh: gateway/payment/notify_xxx')
    jayapay_redirect_url = models.CharField(max_length=255, blank=True, default='')

    # Jayapay Philippines (Global Pay-In) config
    jayapay_ph_enabled = models.BooleanField(default=False)
    jayapay_ph_mch_no = models.CharField(max_length=100, blank=True, default='')
    jayapay_ph_private_key = models.TextField(blank=True, default='', help_text='Paste RSA PRIVATE KEY body ONLY (without BEGIN/END headers)')
    jayapay_ph_public_key = models.TextField(blank=True, default='', help_text='Optional: Platform PUBLIC KEY untuk verifikasi callback')
    jayapay_ph_api_url = models.CharField(max_length=255, blank=True, default='')
    jayapay_ph_redirect_url = models.CharField(max_length=512, blank=True, default='')
    jayapay_ph_default_method = models.CharField(max_length=16, blank=True, default='GCASH')

    # Klikpay config
    klikpay_api_url = models.CharField(max_length=255, blank=True, default='')
    klikpay_merchant_code = models.CharField(max_length=100, blank=True, default='')
    klikpay_secret_key = models.CharField(max_length=255, blank=True, default='')
    klikpay_private_key = models.TextField(blank=True, default='', help_text='Optional: PRIVATE KEY jika penyedia memerlukan RSA signing')
    klikpay_public_key = models.TextField(blank=True, default='', help_text='Optional: PUBLIC KEY jika penyedia memerlukan')
    klikpay_callback_path = models.CharField(max_length=255, blank=True, default='', help_text='Contoh: gateway/payment/notify_xxx')
    klikpay_redirect_url = models.CharField(max_length=255, blank=True, default='')

    # USD Gateway (naskl.gctpk.com)
    usd_gateway_api_url = models.CharField(max_length=255, blank=True, default='')
    usd_gateway_mer_no = models.CharField(max_length=100, blank=True, default='')
    usd_gateway_sign_key = models.CharField(max_length=255, blank=True, default='', help_text='Secret key untuk generate/verify signature')
    usd_gateway_busi_code = models.CharField(max_length=20, blank=True, default='122002', help_text='Default busiCode (122002-122006)')
    usd_gateway_redirect_url = models.CharField(max_length=255, blank=True, default='')
    usd_gateway_min_deposit_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text='Minimal nominal deposit USD (0 = tidak dibatasi)')
    usd_gateway_max_deposit_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text='Maksimal nominal deposit USD (0 = tidak dibatasi)')
    usd_gateway_bank_code = models.CharField(max_length=100, blank=True, default='', help_text='Override bankCode/IP yang dikirim ke provider (kosong = pakai IP client dari request)')

    # PPay Pros pay-in
    ppaypros_api_url = models.CharField(max_length=255, blank=True, default='https://pay.ppaypros.com')
    ppaypros_mch_no = models.CharField(max_length=100, blank=True, default='')
    ppaypros_app_id = models.CharField(max_length=100, blank=True, default='')
    ppaypros_private_key = models.CharField(max_length=255, blank=True, default='', help_text='Private key/sign key untuk MD5 signature')
    ppaypros_way_code = models.CharField(max_length=32, blank=True, default='809', help_text='wayCode default, contoh: 808 (bank) atau 809 (e-wallet)')
    ppaypros_ext_param = models.CharField(max_length=64, blank=True, default='', help_text='Kode bank/wallet default, contoh: BRI, BNI, dana, gopay')
    ppaypros_return_url = models.CharField(max_length=512, blank=True, default='', help_text='URL redirect setelah pembayaran selesai')

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Gateway Settings (default={self.default_wallet_type})"

    class Meta:
        verbose_name = 'Gateway Settings'
        verbose_name_plural = 'Gateway Settings'


class Deposit(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]
    GATEWAY_CHOICES = [
        ('JAYAPAY', 'Jayapay'),
        ('JAYAPAY_PH', 'Jayapay Philippines'),
        ('KLIKPAY', 'Klikpay'),
        ('USD_GATEWAY', 'USD Gateway'),
        ('PPAYPROS', 'PPay Pros'),
    ]
    WALLET_CHOICES = [
        ('BALANCE', 'Balance'),
        ('BALANCE_DEPOSIT', 'Balance Deposit'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    gateway = models.CharField(max_length=20, choices=GATEWAY_CHOICES)
    order_num = models.CharField(max_length=60, unique=True)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    amount_currency_code = models.CharField(max_length=10, blank=True, default="")
    credited_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    credited_currency_code = models.CharField(max_length=10, blank=True, default="")
    wallet_type = models.CharField(max_length=20, choices=WALLET_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    transaction = models.ForeignKey(Transaction, on_delete=models.SET_NULL, null=True, blank=True)
    payment_url = models.CharField(max_length=500, blank=True, default='')

    request_params = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(null=True, blank=True)
    callback_payload = models.JSONField(null=True, blank=True)
    callback_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.order_num} - {self.gateway} - {self.user_id}"

    class Meta:
        db_table = 'deposits'
        ordering = ['-created_at']
