from django.db import models
from django.conf import settings


class Voucher(models.Model):
    BALANCE_CHOICES = [
        ('BALANCE', 'Balance'),
        ('BALANCE_DEPOSIT', 'Balance Deposit'),
    ]

    REWARD_TYPE_CHOICES = [
        ('fixed', 'Fixed Amount'),
        ('random', 'Random Range'),
        ('rank', 'Rank Based'),
    ]

    CLAIM_MODE_CHOICES = [
        ('manual', 'Manual (Input Code)'),
        ('automatic', 'Automatic (Click to Claim)'),
    ]

    code = models.CharField(max_length=50, unique=True)
    type = models.CharField(max_length=20, choices=REWARD_TYPE_CHOICES, default='fixed')
    claim_mode = models.CharField(max_length=20, choices=CLAIM_MODE_CHOICES, default='manual', help_text="Manual: User harus input kode (tidak muncul di list). Automatic: User tinggal klik (muncul di list).")
    # Base amount for 'fixed' or fallback
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    # Random range
    min_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    max_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    # Rank-based rewards mapping: keys '1'..'6'
    rank_rewards = models.JSONField(default=dict, blank=True)

    balance_type = models.CharField(max_length=20, choices=BALANCE_CHOICES, default='BALANCE_DEPOSIT')
    usage_limit = models.IntegerField(default=1)
    used_count = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    is_daily_claim = models.BooleanField(default=False, help_text="Jika aktif, user bisa klaim lagi besoknya (reset harian)")
    start_at = models.DateTimeField(null=True, blank=True, help_text="Waktu mulai klaim voucher")
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.code} ({self.type})"

    class Meta:
        db_table = 'vouchers'
        ordering = ['-created_at']


class VoucherUsage(models.Model):
    BALANCE_CHOICES = [
        ('BALANCE', 'Balance'),
        ('BALANCE_DEPOSIT', 'Balance Deposit'),
    ]

    voucher = models.ForeignKey(Voucher, on_delete=models.CASCADE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    transaction = models.ForeignKey('products.Transaction', on_delete=models.SET_NULL, null=True, blank=True)
    voucher_code = models.CharField(max_length=50)
    amount_credited = models.DecimalField(max_digits=15, decimal_places=2)
    amount_received = models.DecimalField(max_digits=15, decimal_places=2)
    balance_type = models.CharField(max_length=20, choices=BALANCE_CHOICES)
    used_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.voucher_code} -> {self.user} ({self.amount_received})"

    class Meta:
        db_table = 'voucher_usages'
        ordering = ['-used_at']
