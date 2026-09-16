from django.conf import settings
from django.db import models
from django.utils import timezone

from django.db import transaction as db_transaction
from products.models import Transaction
import uuid


class WithdrawalSettings(models.Model):
    BALANCE_CHOICES = [
        ('balance', 'Balance'),
        ('balance_deposit', 'Balance Deposit'),
    ]

    is_active = models.BooleanField(default=True)
    require_bank_account = models.BooleanField(default=True)
    require_pin = models.BooleanField(default=False)
    require_active_investment = models.BooleanField(default=False, help_text="User must have at least one active investment to withdraw")
    max_withdrawal_count = models.PositiveIntegerField(
        default=0,
        help_text="Batas maksimal jumlah penarikan per user. 0 = tanpa batas. Hanya menghitung request PENDING, PROCESSING, dan COMPLETED."
    )
    minimum_product_quantity = models.PositiveIntegerField(default=0)
    required_product = models.ForeignKey('products.Product', on_delete=models.SET_NULL, null=True, blank=True)
    balance_source = models.CharField(max_length=20, choices=BALANCE_CHOICES, default='balance')
    require_withdraw_service = models.BooleanField(default=True, help_text="Jika ON, user wajib memilih WithdrawalService aktif; jika OFF, boleh tanpa service")

    app_domain = models.CharField(max_length=255, blank=True, default='', help_text='Contoh: myapp.example.com (tanpa http/https)')

    jayapay_enabled = models.BooleanField(default=False)
    jayapay_merchant_code = models.CharField(max_length=100, blank=True, default='')
    jayapay_private_key = models.TextField(blank=True, default='', help_text='Paste RSA PRIVATE KEY body ONLY (without BEGIN/END headers)')
    jayapay_public_key = models.TextField(blank=True, default='', help_text='Optional: PUBLIC KEY untuk verifikasi/dekripsi callback bila diperlukan')

    jayapay_ph_payout_enabled = models.BooleanField(default=False)
    jayapay_ph_payout_mch_no = models.CharField(max_length=100, blank=True, default='')
    jayapay_ph_payout_private_key = models.TextField(blank=True, default='', help_text='Paste RSA PRIVATE KEY body ONLY (without BEGIN/END headers)')
    jayapay_ph_payout_public_key = models.TextField(blank=True, default='', help_text='Optional: Platform PUBLIC KEY untuk verifikasi callback')
    jayapay_ph_payout_api_url = models.CharField(max_length=255, blank=True, default='')
    jayapay_ph_payout_fee_type = models.PositiveSmallIntegerField(default=1, help_text='0: fee deduct in order; 1: handling fee calculated separately')

    ppaypros_payout_enabled = models.BooleanField(default=False)
    ppaypros_payout_api_url = models.CharField(max_length=255, blank=True, default='https://pay.ppaypros.com')
    ppaypros_payout_mch_no = models.CharField(max_length=100, blank=True, default='')
    ppaypros_payout_app_id = models.CharField(max_length=100, blank=True, default='')
    ppaypros_payout_private_key = models.CharField(max_length=255, blank=True, default='', help_text='Private key/sign key untuk MD5 signature')
    ppaypros_payout_entry_type = models.CharField(max_length=32, blank=True, default='BANK_CARD', help_text='Default entryType payout, contoh: BANK_CARD')

    atpay_payout_enabled = models.BooleanField(default=False)
    atpay_payout_api_url = models.CharField(max_length=255, blank=True, default='https://test.wowpay.biz')
    atpay_payout_merchant_no = models.CharField(max_length=100, blank=True, default='')
    atpay_payout_sign_type = models.CharField(max_length=20, blank=True, default='MD5', help_text='MD5 atau MD5withRsa')
    atpay_payout_secret_key = models.CharField(max_length=255, blank=True, default='', help_text='Dipakai jika sign_type=MD5')
    atpay_payout_private_key = models.TextField(blank=True, default='', help_text='Dipakai jika sign_type=MD5withRsa')
    atpay_payout_public_key = models.TextField(blank=True, default='', help_text='Public key ATPAY untuk verifikasi callback MD5withRsa')

    bankpay_payout_enabled = models.BooleanField(default=False)
    bankpay_payout_api_url = models.CharField(max_length=255, blank=True, default='https://pay.bankpay.cfd')
    bankpay_payout_member_id = models.CharField(max_length=100, blank=True, default='', help_text='Merchant ID dari BankPay')
    bankpay_payout_key = models.CharField(max_length=255, blank=True, default='', help_text='MERCHANT_KEY untuk signature MD5 payout')

    reepay_payout_enabled = models.BooleanField(default=False)
    reepay_payout_api_url = models.CharField(max_length=255, blank=True, default='https://api.roguecdn.online', help_text='Base URL Reepay')
    reepay_payout_api_key = models.CharField(max_length=255, blank=True, default='', help_text='X-API-Key merchant (ak_...)')
    reepay_payout_secret_key = models.CharField(max_length=255, blank=True, default='', help_text='Secret key untuk HMAC-SHA256 signature payout')

    batpay_payout_enabled = models.BooleanField(default=False)
    batpay_payout_api_url = models.CharField(max_length=255, blank=True, default='https://api.wayrooou.online', help_text='Base URL BatPay')
    batpay_payout_api_key = models.CharField(max_length=255, blank=True, default='', help_text='X-API-Key merchant (ak_...)')
    batpay_payout_secret_key = models.TextField(blank=True, default='', help_text='Secret key HMAC-SHA256 payout (347 karakter - jangan VARCHAR(255))')

    nextpay_payout_enabled = models.BooleanField(default=False)
    nextpay_payout_api_url = models.CharField(max_length=255, blank=True, default='https://api.nextcdn.online', help_text='Base URL NextPay')
    nextpay_payout_api_key = models.CharField(max_length=255, blank=True, default='', help_text='X-API-Key merchant (ak_...)')
    nextpay_payout_secret_key = models.TextField(blank=True, default='', help_text='Secret key HMAC-SHA256 payout (347 karakter - jangan VARCHAR(255))')

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'withdrawal_settings'

    def __str__(self):
        return f"WithdrawalSettings(active={self.is_active})"


class WithdrawalService(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    duration_hours = models.PositiveIntegerField()
    fee_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    fee_fixed = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'withdrawal_services'
        ordering = ['sort_order', 'duration_hours', 'name']

    def __str__(self):
        return f"{self.name} ({self.duration_hours} jam, {self.fee_percent}% + {self.fee_fixed})"


class Withdrawal(models.Model):
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('REJECTED', 'Rejected'),
        ('CANCELLED', 'Cancelled'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='withdrawals')
    bank_account = models.ForeignKey('banks.UserBank', on_delete=models.SET_NULL, null=True, blank=True, related_name='withdrawals')
    withdrawal_service = models.ForeignKey('WithdrawalService', on_delete=models.SET_NULL, null=True, blank=True, related_name='withdrawals')

    amount = models.DecimalField(max_digits=15, decimal_places=2)
    fee = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    net_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')

    note = models.TextField(blank=True)
    transaction = models.ForeignKey('products.Transaction', on_delete=models.SET_NULL, null=True, blank=True, related_name='related_withdrawal')

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'withdrawals'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user.phone} - {self.amount} ({self.status})"

    def save(self, *args, **kwargs):
        # Capture previous status before saving to detect transitions
        prev_status = None
        if self.pk:
            try:
                prev_status = Withdrawal.objects.only('status').get(pk=self.pk).status
            except Withdrawal.DoesNotExist:
                prev_status = None

        super().save(*args, **kwargs)

        # Keep linked transaction status in sync
        if self.transaction and self.transaction.status != self.status:
            self.transaction.status = self.status
            self.transaction.save(update_fields=['status'])

        # Auto refund when rejected/cancelled from a pending/processing state
        if prev_status in ('PENDING', 'PROCESSING') and self.status in ('REJECTED', 'CANCELLED'):
            # Determine wallet field from original transaction
            wallet_field = None
            wallet_type = None
            if self.transaction:
                wallet_type = self.transaction.wallet_type
                if wallet_type == 'BALANCE':
                    wallet_field = 'balance'
                elif wallet_type == 'BALANCE_DEPOSIT':
                    wallet_field = 'balance_deposit'

            if wallet_field:
                # Ensure idempotency: do not double-refund
                refund_exists = Transaction.objects.filter(
                    related_transaction=self.transaction,
                    type__in=['REJECT', 'CREDIT'],
                    description__icontains='Withdrawal',
                ).exists()
                if not refund_exists:
                    with db_transaction.atomic():
                        # Refund full amount deducted at request time
                        current_value = getattr(self.user, wallet_field)
                        setattr(self.user, wallet_field, current_value + self.amount)
                        self.user.save(update_fields=[wallet_field])

                        # Record refund transaction
                        Transaction.objects.create(
                            user=self.user,
                            product=None,
                            upline_user=None,
                            trx_id=f"WDREF-{uuid.uuid4().hex[:10].upper()}",
                            type='REJECT',
                            amount=self.amount,
                            description='Withdrawal rejected - refund',
                            status='COMPLETED',
                            wallet_type=wallet_type or 'BALANCE',
                            related_transaction=self.transaction,
                        )


class JayapayWithdrawal(models.Model):
    withdrawal = models.OneToOneField(Withdrawal, on_delete=models.CASCADE, related_name='jayapay_withdrawal')
    request_params = models.JSONField(default=dict)
    response_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'withdrawal_jayapay'
        ordering = ['-created_at']

    def __str__(self):
        return f"Jayapay for Withdrawal #{self.withdrawal.pk}"


class JayapayPhPayoutWithdrawal(models.Model):
    withdrawal = models.OneToOneField(Withdrawal, on_delete=models.CASCADE, related_name='jayapay_ph_payout_withdrawal')
    request_params = models.JSONField(default=dict)
    response_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'withdrawal_jayapay_ph_payout'
        ordering = ['-created_at']

    def __str__(self):
        return f"Jayapay PH payout for Withdrawal #{self.withdrawal.pk}"


class UsdPayoutWithdrawal(models.Model):
    withdrawal = models.OneToOneField(Withdrawal, on_delete=models.CASCADE, related_name='usd_payout_withdrawal')
    request_params = models.JSONField(default=dict)
    response_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'withdrawal_usd_payout'
        ordering = ['-created_at']

    def __str__(self):
        return f"USD payout for Withdrawal #{self.withdrawal.pk}"


class PPayProsWithdrawal(models.Model):
    withdrawal = models.OneToOneField(Withdrawal, on_delete=models.CASCADE, related_name='ppaypros_withdrawal')
    request_params = models.JSONField(default=dict)
    response_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'withdrawal_ppaypros'
        ordering = ['-created_at']

    def __str__(self):
        return f"PPay Pros payout for Withdrawal #{self.withdrawal.pk}"


class AtpayWithdrawal(models.Model):
    withdrawal = models.OneToOneField(Withdrawal, on_delete=models.CASCADE, related_name='atpay_withdrawal')
    request_params = models.JSONField(default=dict)
    response_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'withdrawal_atpay'
        ordering = ['-created_at']

    def __str__(self):
        return f"ATPAY payout for Withdrawal #{self.withdrawal.pk}"


class WithdrawalJayapay(Withdrawal):
    class Meta:
        proxy = True
        verbose_name = 'Withdrawal Jayapay'
        verbose_name_plural = 'Withdrawals Jayapay'


class BankPayWithdrawal(models.Model):
    withdrawal = models.OneToOneField(Withdrawal, on_delete=models.CASCADE, related_name='bankpay_withdrawal')
    request_params = models.JSONField(default=dict)
    response_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'withdrawal_bankpay'
        ordering = ['-created_at']

    def __str__(self):
        return f"BankPay payout for Withdrawal #{self.withdrawal.pk}"


class ReepayWithdrawal(models.Model):
    withdrawal = models.OneToOneField(Withdrawal, on_delete=models.CASCADE, related_name='reepay_withdrawal')
    request_params = models.JSONField(default=dict)
    response_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'withdrawal_reepay'
        ordering = ['-created_at']

    def __str__(self):
        return f"Reepay payout for Withdrawal #{self.withdrawal.pk}"


class BatPayWithdrawal(models.Model):
    withdrawal = models.OneToOneField(Withdrawal, on_delete=models.CASCADE, related_name='batpay_withdrawal')
    request_params = models.JSONField(default=dict)
    response_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'withdrawal_batpay'
        ordering = ['-created_at']

    def __str__(self):
        return f"BatPay payout for Withdrawal #{self.withdrawal.pk}"

class NextPayWithdrawal(models.Model):
    withdrawal = models.OneToOneField(Withdrawal, on_delete=models.CASCADE, related_name='nextpay_withdrawal')
    request_params = models.JSONField(default=dict)
    response_payload = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'withdrawal_nextpay'
        ordering = ['-created_at']

    def __str__(self):
        return f"NextPay payout for Withdrawal #{self.withdrawal.pk}"
