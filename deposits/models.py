from django.db import models
from django.conf import settings
from django.utils import timezone
from products.models import Transaction
from .integrations.qris import sanitize_qris_string


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
    clienthub_enabled = models.BooleanField(default=False)
    sitransferhub_enabled = models.BooleanField(default=False)
    atpay_enabled = models.BooleanField(default=False)
    bankpay_enabled = models.BooleanField(default=False)
    qris_enabled = models.BooleanField(default=False)

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

    # ClientHub pay-in
    clienthub_base_url = models.CharField(max_length=255, blank=True, default='', help_text='Contoh: https://api.totc.site')
    clienthub_client_id = models.CharField(max_length=100, blank=True, default='')
    clienthub_secret_key = models.CharField(max_length=255, blank=True, default='', help_text='Secret key untuk HMAC request/callback')
    clienthub_method = models.CharField(max_length=50, blank=True, default='BRIVA')
    clienthub_return_url = models.CharField(max_length=512, blank=True, default='', help_text='URL redirect setelah pembayaran selesai')
    clienthub_expired_minutes = models.PositiveIntegerField(default=60, help_text='Masa berlaku invoice dalam menit')

    # SiTransfer Hub pay-in
    sitransferhub_base_url = models.CharField(max_length=255, blank=True, default='', help_text='Contoh: https://api.totc.site')
    sitransferhub_client_id = models.CharField(max_length=100, blank=True, default='')
    sitransferhub_secret_key = models.CharField(max_length=255, blank=True, default='', help_text='Secret key untuk HMAC request/callback')
    sitransferhub_channel = models.CharField(max_length=20, blank=True, default='QRIS', help_text='Channel default: QRIS atau DANA')

    # ATPAY pay-in
    atpay_api_url = models.CharField(max_length=255, blank=True, default='https://test.wowpay.biz')
    atpay_merchant_no = models.CharField(max_length=100, blank=True, default='')
    atpay_sign_type = models.CharField(max_length=20, blank=True, default='MD5', help_text='MD5 atau MD5withRsa')
    atpay_secret_key = models.CharField(max_length=255, blank=True, default='', help_text='Dipakai jika sign_type=MD5')
    atpay_private_key = models.TextField(blank=True, default='', help_text='Dipakai jika sign_type=MD5withRsa')
    atpay_public_key = models.TextField(blank=True, default='', help_text='Public key ATPAY untuk verifikasi callback MD5withRsa')
    atpay_return_url = models.CharField(max_length=512, blank=True, default='', help_text='URL redirect setelah pembayaran selesai')

    # BankPay pay-in
    bankpay_api_url = models.CharField(max_length=255, blank=True, default='https://pay.bankpay.cfd')
    bankpay_member_id = models.CharField(max_length=100, blank=True, default='', help_text='Merchant ID dari BankPay')
    bankpay_key = models.CharField(max_length=255, blank=True, default='', help_text='MERCHANT_KEY untuk signature MD5')
    bankpay_return_url = models.CharField(max_length=512, blank=True, default='', help_text='URL redirect setelah pembayaran selesai')

    # QRIS Gateway config (manual upload, static-to-dynamic)
    qris_min_deposit_amount = models.DecimalField(max_digits=15, decimal_places=2, default=10000, help_text='Minimal nominal deposit QRIS')
    qris_max_deposit_amount = models.DecimalField(max_digits=15, decimal_places=2, default=5000000, help_text='Maksimal nominal deposit QRIS (0 = tidak dibatasi)')
    qris_expired_minutes = models.PositiveIntegerField(default=30, help_text='QR kadaluarsa setelah berapa menit (0 = tidak kadaluarsa)')

    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Gateway Settings (default={self.default_wallet_type})"

    class Meta:
        verbose_name = 'Gateway Settings'
        verbose_name_plural = 'Gateway Settings'


class QRISGateway(models.Model):
    """Menyimpan QRIS static yang di-upload manual oleh admin.
    QRIS static akan dikonversi ke dynamic saat user melakukan deposit."""

    label = models.CharField(max_length=100, help_text='Label/nama QRIS (contoh: QRIS BCA, ShopeePay)')
    qris_image = models.ImageField(upload_to='qris/images/', blank=True, null=True, help_text='Upload gambar QRIS static')
    qris_raw_data = models.TextField(blank=True, default='', help_text='Raw QRIS string hasil scan (0002010102...)')
    is_active = models.BooleanField(default=True, help_text='Aktifkan QR ini untuk digunakan')
    max_use_count = models.PositiveIntegerField(default=0, help_text='Maksimal berapa kali QR ini bisa dipakai (0 = unlimited)')
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
            # Try filesystem path first
            file_path = self.qris_image.path
            if not os.path.exists(file_path):
                logger.info("QRISGateway: image file not found, skip decode (path=%s)", file_path)
                return

            # Read file bytes and decode via numpy (more reliable than cv2.imread path)
            with open(file_path, 'rb') as f:
                file_bytes = np.frombuffer(f.read(), np.uint8)
            img = cv2.imdecode(file_bytes, cv2.IMREAD_COLOR)
            if img is None:
                logger.warning("QRISGateway: cannot decode image for label=%s, path=%s", self.label, file_path)
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
        """Cek apakah QR ini masih bisa digunakan."""
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
        ('CLIENTHUB', 'ClientHub'),
        ('SITRANSFERHUB', 'SiTransfer Hub'),
        ('ATPAY', 'ATPAY'),
        ('BANKPAY', 'BankPay'),
        ('QRIS', 'QRIS Manual'),
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
    payment_url = models.CharField(max_length=2000, blank=True, default='')

    request_params = models.JSONField(default=dict, blank=True)
    response_payload = models.JSONField(null=True, blank=True)
    callback_payload = models.JSONField(null=True, blank=True)
    callback_at = models.DateTimeField(null=True, blank=True)
    expired_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.order_num} - {self.gateway} - {self.user_id}"

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

    class Meta:
        db_table = 'deposits'
        ordering = ['-created_at']
