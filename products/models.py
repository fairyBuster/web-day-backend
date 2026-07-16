from django.db import models, transaction as db_transaction
from django.core.validators import MinValueValidator
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import json
import uuid

class Product(models.Model):
    BALANCE_CHOICES = [
        ('balance', 'Balance'),
        ('balance_deposit', 'Balance Deposit'),
    ]
    
    CLAIM_RESET_CHOICES = [
        ('at_00', 'Reset at 00:00'),
        ('at_custom', 'Reset at Custom Hour (Daily)'),
        ('after_purchase', 'Reset after purchase duration'),
    ]
    
    PROFIT_TYPE_CHOICES = [
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed Amount'),
        ('random', 'Random Range'),
    ]
    
    PROFIT_METHOD_CHOICES = [
        ('manual', 'Manual'),
        ('auto', 'Automatic'),
        ('hold', 'Hold Until Maturity'),
    ]
    
    STATUS_CHOICES = [
        (0, 'Inactive'),
        (1, 'Active'),
    ]
    
    name = models.CharField(max_length=255)
    golongan = models.CharField(max_length=20, blank=True, null=True, db_index=True)
    description = models.TextField()
    price = models.DecimalField(max_digits=16, decimal_places=2, validators=[MinValueValidator(0)])
    image = models.CharField(max_length=255, blank=True, null=True)
    status = models.IntegerField(choices=STATUS_CHOICES, default=1)
    
    # Investment Settings
    purchase_limit = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    stock = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    stock_enabled = models.BooleanField(default=True)
    # Added max_purchase_count to enforce per-user purchase cap
    max_purchase_count = models.IntegerField(default=3, validators=[MinValueValidator(1)], help_text='Maximum number of times a user can purchase this product')
    
    # Profit Settings
    profit_type = models.CharField(max_length=20, choices=PROFIT_TYPE_CHOICES)
    profit_rate = models.DecimalField(max_digits=16, decimal_places=2, validators=[MinValueValidator(0)])
    # Random Profit Settings (optional; used when profit_type == 'random')
    profit_random_min = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    profit_random_max = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True, validators=[MinValueValidator(0)])
    profit_method = models.CharField(max_length=20, choices=PROFIT_METHOD_CHOICES)
    duration = models.IntegerField(validators=[MinValueValidator(1)])  # in hours
    
    # Balance Settings
    balance_source = models.CharField(max_length=20, choices=BALANCE_CHOICES)
    
    # Claim Settings
    claim_reset_mode = models.CharField(max_length=20, choices=CLAIM_RESET_CHOICES, default='after_purchase')
    claim_reset_hours = models.IntegerField(null=True, blank=True)

    # Commission Rules
    require_upline_ownership_for_commissions = models.BooleanField(
        default=False,
        help_text='Jika ON, upline harus memiliki produk ini (investment ACTIVE) untuk menerima purchase/profit commission'
    )
    qualify_as_active_investment = models.BooleanField(
        default=True,
        help_text='Jika OFF, pembelian produk ini tidak membuat user dihitung sebagai member aktif (rank, missions, dsb)'
    )
    
    # Rebate Settings
    purchase_rebate_level_1 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    purchase_rebate_level_2 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    purchase_rebate_level_3 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    purchase_rebate_level_4 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    purchase_rebate_level_5 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    profit_rebate_level_1 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    profit_rebate_level_2 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    profit_rebate_level_3 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    profit_rebate_level_4 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    profit_rebate_level_5 = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    
    # Cashback Settings
    cashback_enabled = models.BooleanField(default=False, help_text='Enable cashback for this product')
    cashback_percentage = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=0, 
        validators=[MinValueValidator(0)],
        help_text='Cashback percentage (0-100). Example: 10.50 for 10.5%'
    )
    
    # Additional Settings
    image = models.ImageField(upload_to='products/', null=True, blank=True)
    return_principal_on_completion = models.BooleanField(default=False)
    
    # Custom Fields
    # Ten custom fields (title + content), optional use
    custom_field_1_title = models.CharField(max_length=255, null=True, blank=True, help_text='Custom field 1 title')
    custom_field_1_content = models.TextField(null=True, blank=True, help_text='Custom field 1 content')
    custom_field_2_title = models.CharField(max_length=255, null=True, blank=True, help_text='Custom field 2 title')
    custom_field_2_content = models.TextField(null=True, blank=True, help_text='Custom field 2 content')
    custom_field_3_title = models.CharField(max_length=255, null=True, blank=True, help_text='Custom field 3 title')
    custom_field_3_content = models.TextField(null=True, blank=True, help_text='Custom field 3 content')
    custom_field_4_title = models.CharField(max_length=255, null=True, blank=True, help_text='Custom field 4 title')
    custom_field_4_content = models.TextField(null=True, blank=True, help_text='Custom field 4 content')
    custom_field_5_title = models.CharField(max_length=255, null=True, blank=True, help_text='Custom field 5 title')
    custom_field_5_content = models.TextField(null=True, blank=True, help_text='Custom field 5 content')
    custom_field_6_title = models.CharField(max_length=255, null=True, blank=True, help_text='Custom field 6 title')
    custom_field_6_content = models.TextField(null=True, blank=True, help_text='Custom field 6 content')
    custom_field_7_title = models.CharField(max_length=255, null=True, blank=True, help_text='Custom field 7 title')
    custom_field_7_content = models.TextField(null=True, blank=True, help_text='Custom field 7 content')
    custom_field_8_title = models.CharField(max_length=255, null=True, blank=True, help_text='Custom field 8 title')
    custom_field_8_content = models.TextField(null=True, blank=True, help_text='Custom field 8 content')
    custom_field_9_title = models.CharField(max_length=255, null=True, blank=True, help_text='Custom field 9 title')
    custom_field_9_content = models.TextField(null=True, blank=True, help_text='Custom field 9 content')
    custom_field_10_title = models.CharField(max_length=255, null=True, blank=True, help_text='Custom field 10 title')
    custom_field_10_content = models.TextField(null=True, blank=True, help_text='Custom field 10 content')
    specifications = models.TextField(blank=True)
    
    # Purchase Restrictions
    require_withdraw_pin_on_purchase = models.BooleanField(
        default=False,
        help_text='Jika ON, pembelian produk ini wajib input withdraw PIN'
    )
    require_min_rank_enabled = models.BooleanField(
        default=False,
        help_text='Jika ON, user harus memiliki rank minimum untuk membeli produk ini'
    )
    min_required_rank = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text='Rank minimum yang dibutuhkan untuk membeli (contoh: 2 untuk Rank 2)'
    )
    required_product = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='unlocks_products',
        help_text='Jika diisi, user wajib sudah pernah memiliki produk ini sebelum bisa membeli produk ini',
    )
    required_golongan = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        db_index=True,
        help_text='Jika diisi, user wajib sudah pernah membeli produk dengan golongan ini sebelum bisa membeli produk ini',
    )
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return self.name
    
    def get_rebate_settings(self):
        if isinstance(self.rebate_settings, str):
            return json.loads(self.rebate_settings)
        return self.rebate_settings
    
    def set_rebate_settings(self, settings):
        if isinstance(settings, dict):
            self.rebate_settings = settings
        else:
            self.rebate_settings = json.loads(settings)
    
    def calculate_cashback(self, purchase_amount):
        """Calculate cashback amount based on purchase amount and cashback percentage"""
        if not self.cashback_enabled or self.cashback_percentage <= 0:
            return 0

        from decimal import Decimal

        amount = Decimal(str(purchase_amount or 0))
        percent = Decimal(str(self.cashback_percentage or 0))
        cashback_amount = (amount * percent) / Decimal("100")
        return cashback_amount
    
    def get_cashback_info(self):
        """Get cashback information for display purposes"""
        return {
            'enabled': self.cashback_enabled,
            'percentage': float(self.cashback_percentage),
            'display': f"{self.cashback_percentage}%" if self.cashback_enabled else "No cashback"
        }
    
    class Meta:
        db_table = 'products'
        ordering = ['-created_at']


class Transaction(models.Model):
    TYPE_CHOICES = [
        ('CREDIT', 'Credit'),
        ('BONUS', 'Bonus'),
        ('DEBIT', 'Debit'),
        ('TRANSFER', 'Transfer'),
        ('DEPOSIT', 'Deposit'),
        ('WITHDRAW', 'Withdraw'),
        ('PURCHASE_COMMISSION', 'Purchase Commission'),
        ('PROFIT_COMMISSION', 'Profit Commission'),
        ('INTEREST', 'Interest'),
        ('INVESTMENTS', 'Investments'),
        ('MISSIONS', 'Missions'),
        ('VOUCHER', 'Voucher'),
        ('ATTENDANCE', 'Attendance'),
        ('CASHBACK', 'Cashback'),
        ('CASHBACK_DEPOSIT', 'Cashback Deposit'),
        ('REJECT', 'Reject'),
        ('RETURN', 'Return'),
        ('HOLD_RELEASE', 'Hold Release'),
    ]
    
    STATUS_CHOICES = [
        ('PENDING', 'Pending'),
        ('PROCESSING', 'Processing'),
        ('COMPLETED', 'Completed'),
        ('REJECTED', 'Rejected'),
        ('FAILED', 'Failed'),
        ('CANCELLED', 'Cancelled'),
    ]
    
    WALLET_CHOICES = [
        ('BALANCE', 'Balance'),
        ('BALANCE_DEPOSIT', 'Balance Deposit'),
        ('BALANCE_HOLD', 'Balance Hold'),
        ('BALANCE_CASHBACK', 'Balance Cashback'),
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True)
    upline_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='referral_transactions')
    
    trx_id = models.CharField(max_length=50, unique=True)
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    currency_code = models.CharField(max_length=10, blank=True, default="")
    original_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    original_currency_code = models.CharField(max_length=10, blank=True, default="")
    conversion_rate = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        null=True,
        blank=True,
        verbose_name="Conversion rate",
    )
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='PENDING')
    wallet_type = models.CharField(max_length=20, choices=WALLET_CHOICES)
    
    # Investment specific
    investment_quantity = models.IntegerField(null=True, blank=True)
    commission_level = models.IntegerField(null=True, blank=True)
    
    # Related transactions
    related_transaction = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    
    # Voucher related
    voucher = models.ForeignKey('vouchers.Voucher', on_delete=models.SET_NULL, null=True, blank=True)
    voucher_code = models.CharField(max_length=50, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    @staticmethod
    def _build_auto_trx_id(prefix: str) -> str:
        ts = timezone.now().strftime("%Y%m%d%H%M%S")
        rand = uuid.uuid4().hex[:10].upper()
        prefix_clean = (prefix or "TRX").strip().upper() or "TRX"
        return f"{prefix_clean}-{ts}-{rand}"[:50]

    def _suggest_trx_prefix(self) -> str:
        t = (self.type or "").strip().upper()
        if t == "WITHDRAW":
            return "WD"
        if t == "DEPOSIT":
            return "DEP"
        if t == "CREDIT":
            return "CR"
        if t == "DEBIT":
            return "DB"
        if t == "TRANSFER":
            return "TF"
        return "TRX"

    def save(self, *args, **kwargs):
        if not (self.trx_id or "").strip():
            prefix = self._suggest_trx_prefix()
            candidate = self._build_auto_trx_id(prefix)
            for _ in range(10):
                if not Transaction.objects.filter(trx_id=candidate).exists():
                    break
                candidate = self._build_auto_trx_id(prefix)
            self.trx_id = candidate
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.trx_id} - {self.user.phone}"
    
    class Meta:
        db_table = 'transactions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'type', 'status', 'created_at'], name='trx_user_type_stat_cr_idx'),
            models.Index(fields=['upline_user', 'type'], name='trx_upline_type_idx'),
            models.Index(fields=['type'], name='trx_type_idx'),
            models.Index(fields=['wallet_type'], name='trx_wallet_type_idx'),
        ]


class ProfitHolidaySettings(models.Model):
    is_active = models.BooleanField(default=False)
    disable_monday = models.BooleanField(default=False)
    disable_tuesday = models.BooleanField(default=False)
    disable_wednesday = models.BooleanField(default=False)
    disable_thursday = models.BooleanField(default=False)
    disable_friday = models.BooleanField(default=False)
    disable_saturday = models.BooleanField(default=False)
    disable_sunday = models.BooleanField(default=False)
    extend_duration_on_holidays = models.BooleanField(
        default=False,
        help_text="Jika ON, hari libur tidak mengurangi durasi investasi (siklus bergeser, tidak hangus)"
    )
    disabled_dates = models.JSONField(
        default=list,
        blank=True,
        help_text="Daftar tanggal libur format YYYY-MM-DD. Contoh: [\"2026-04-10\", \"2026-05-01\"]",
    )

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "profit_holiday_settings"
        verbose_name = "Profit Holiday Settings"
        verbose_name_plural = "Profit Holiday Settings"

    def __str__(self):
        return f"ProfitHolidaySettings(active={self.is_active})"

    @classmethod
    def get_settings(cls):
        return cls.objects.first()

    @classmethod
    def is_profit_blocked_today(cls, today=None):
        settings_obj = cls.get_settings()
        if not settings_obj or not settings_obj.is_active:
            return False
        if today is None:
            now_dt = timezone.now()
            today = timezone.localdate(now_dt) if timezone.is_aware(now_dt) else now_dt.date()

        weekday = today.weekday()
        if weekday == 0 and settings_obj.disable_monday:
            return True
        if weekday == 1 and settings_obj.disable_tuesday:
            return True
        if weekday == 2 and settings_obj.disable_wednesday:
            return True
        if weekday == 3 and settings_obj.disable_thursday:
            return True
        if weekday == 4 and settings_obj.disable_friday:
            return True
        if weekday == 5 and settings_obj.disable_saturday:
            return True
        if weekday == 6 and settings_obj.disable_sunday:
            return True

        try:
            disabled = settings_obj.disabled_dates or []
            return today.isoformat() in disabled
        except Exception:
            return False
    
    @classmethod
    def count_blocked_days(cls, start_date, end_date):
        settings_obj = cls.get_settings()
        if not settings_obj or not settings_obj.is_active:
            return 0
        if start_date > end_date:
            return 0
        blocked = 0
        disabled_set = set((settings_obj.disabled_dates or []))
        cur = start_date
        while cur <= end_date:
            if cls.is_profit_blocked_today(cur):
                blocked += 1
            elif cur.isoformat() in disabled_set:
                blocked += 1
            cur = cur + timedelta(days=1)
        return blocked


class Investment(models.Model):
    STATUS_CHOICES = [
        ('ACTIVE', 'Active'),
        ('COMPLETED', 'Completed'),
        ('EXPIRED', 'Expired'),
        ('CANCELLED', 'Cancelled'),
    ]
    
    CLAIM_RESET_CHOICES = [
        ('at_00', 'Reset at 00:00'),
        ('at_custom', 'Reset at Custom Hour (Daily)'),
        ('after_purchase', 'Reset after purchase duration'),
    ]
    
    PROFIT_TYPE_CHOICES = [
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed Amount'),
        ('random', 'Random Range'),
    ]
    
    PROFIT_METHOD_CHOICES = [
        ('manual', 'Manual'),
        ('auto', 'Automatic'),
        ('hold', 'Hold Until Maturity'),
    ]
    
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, help_text='Purchase transaction')
    
    quantity = models.IntegerField(default=1, validators=[MinValueValidator(1)])
    total_amount = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Profit settings (copied from product at time of purchase)
    profit_type = models.CharField(max_length=20, choices=PROFIT_TYPE_CHOICES)
    profit_rate = models.DecimalField(max_digits=16, decimal_places=2)
    # Random Profit Settings copied from product at purchase time
    profit_random_min = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    profit_random_max = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    profit_method = models.CharField(max_length=20, choices=PROFIT_METHOD_CHOICES)
    claim_reset_mode = models.CharField(max_length=20, choices=CLAIM_RESET_CHOICES)
    claim_reset_hours = models.IntegerField(null=True, blank=True)

    # Duration and timing
    duration_days = models.IntegerField(help_text='Investment duration in days')
    remaining_days = models.IntegerField(help_text='Days remaining until expiration')
    expires_at = models.DateTimeField(help_text='Investment expiration date')
    
    # Claim tracking
    last_claim_time = models.DateTimeField(null=True, blank=True)
    next_claim_time = models.DateTimeField(null=True, blank=True)
    total_claimed_profit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    
    # Detailed claim statistics
    claims_count = models.IntegerField(default=0, help_text='Total number of claims made')
    total_claimed_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text='Total amount claimed (same as total_claimed_profit)')
    last_claim_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text='Amount of the last claim')
    first_claim_time = models.DateTimeField(null=True, blank=True, help_text='Time of the first claim')
    claims_remaining = models.IntegerField(default=0, help_text='Number of claims remaining (calculated field)')
    
    # Status
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='ACTIVE')
    principal_returned = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.user.phone} - {self.product.name} ({self.quantity}x)"
    
    @property
    def daily_profit(self):
        """Calculate daily profit based on profit type and rate"""
        if self.profit_type == 'percentage':
            return (self.total_amount * self.profit_rate) / 100
        elif self.profit_type == 'fixed':
            return self.profit_rate
        else:  # random
            try:
                from decimal import Decimal
                import random
                # Ensure min and max exist and valid
                min_val = self.profit_random_min if self.profit_random_min is not None else Decimal('0')
                max_val = self.profit_random_max if self.profit_random_max is not None else Decimal('0')
                if min_val <= 0 or max_val <= 0 or max_val < min_val:
                    return Decimal('0')
                # Generate random amount in cents to avoid float issues
                min_cents = int((min_val * 100).to_integral_value(rounding=None))
                max_cents = int((max_val * 100).to_integral_value(rounding=None))
                rand_cents = random.randint(min_cents, max_cents)
                return Decimal(rand_cents) / Decimal('100')
            except Exception:
                # Fallback to zero on any error
                from decimal import Decimal
                return Decimal('0')
    
    @property
    def total_potential_profit(self):
        """Calculate total profit for the entire investment period"""
        return self.daily_profit * self.duration_days
    
    @property
    def remaining_profit(self):
        """Calculate remaining profit that can be claimed"""
        return self.total_potential_profit - self.total_claimed_profit
    
    @property
    def days_passed(self):
        """Calculate how many days have passed since investment started"""
        from django.utils import timezone
        days_elapsed = (timezone.now().date() - self.created_at.date()).days
        return min(days_elapsed, self.duration_days)  # Cap at duration_days
    
    @property
    def progress_display(self):
        """Display progress as 'days_passed/total_duration'"""
        return f"{self.days_passed}/{self.duration_days}"
    
    def can_claim_today(self):
        """Check if user can claim profit today"""
        if self.status != 'ACTIVE':
            return False
        
        # Count-first policy: stop claims when count reaches duration
        if self.claims_count >= self.duration_days:
            return False
        
        if self.remaining_days <= 0:
            return False

        if ProfitHolidaySettings.is_profit_blocked_today():
            return False
        
        # For automatic profit method, check if it's time for automatic processing
        if self.profit_method == 'auto':
            from django.utils import timezone
            # If next_claim_time is set, allow only after it passes
            if self.next_claim_time:
                return timezone.now() >= self.next_claim_time
            # If not set, compute expected next claim time based on reset mode
            expected_next = self.calculate_next_claim_time()
            return timezone.now() >= expected_next
        
        from django.utils import timezone
        
        if self.claim_reset_mode == 'at_00':
            if self.last_claim_time:
                now_dt = timezone.now()
                today = timezone.localdate(now_dt) if timezone.is_aware(now_dt) else now_dt.date()
                last_claim_dt = self.last_claim_time
                last_claim_date = timezone.localtime(last_claim_dt).date() if timezone.is_aware(last_claim_dt) else last_claim_dt.date()
                return today > last_claim_date
            return True
        
        if self.next_claim_time:
            return timezone.now() >= self.next_claim_time
        
        expected_next = self.calculate_next_claim_time()
        return timezone.now() >= expected_next
    
    def can_claim_manually(self):
        """Check if user can manually claim profit (excludes auto method)"""
        if self.profit_method == 'auto':
            return False
        return self.can_claim_today()
    
    def calculate_next_claim_time(self):
        """Calculate next available claim time"""
        from django.utils import timezone
        from datetime import time, timedelta
        
        if self.claim_reset_mode == 'at_00':
            # Next claim available at next midnight
            # Gunakan local time agar tanggal sesuai dengan timezone server (Asia/Jakarta)
            # Base calculation on last_claim_time or created_at to be deterministic
            base_time = self.last_claim_time if self.last_claim_time else self.created_at
            local_base = timezone.localtime(base_time) if timezone.is_aware(base_time) else base_time
            
            # Target is the next midnight after the base event
            target_date = local_base.date() + timedelta(days=1)
            
            # Create datetime at 00:00 local time
            naive_target = timezone.datetime.combine(target_date, time.min)
            next_dt = timezone.make_aware(naive_target, timezone.get_current_timezone()) if timezone.is_aware(local_base) else naive_target
        elif self.claim_reset_mode == 'at_custom':
            # Next claim available at specific hour (Daily)
            base_time = self.last_claim_time if self.last_claim_time else self.created_at
            local_base = timezone.localtime(base_time) if timezone.is_aware(base_time) else base_time
            
            # Get target hour from investment setting (default 0 if not set)
            target_hour = 0
            if self.claim_reset_hours is not None:
                target_hour = int(self.claim_reset_hours) % 24
            
            # Create target time for TODAY at specific hour
            # Note: We use the date of local_base initially
            target_dt = local_base.replace(hour=target_hour, minute=0, second=0, microsecond=0)
            
            # If the target time is in the past relative to base_time, move to TOMORROW
            if target_dt <= local_base:
                target_dt = target_dt + timedelta(days=1)
                
            next_dt = target_dt
        else:
            # Next claim available after N hours (from settings) or 24 hours default
            # Use product setting if available, otherwise default to 24
            reset_hours = 24
            # Check if product has claim_reset_hours set
            if self.product.claim_reset_hours is not None and self.product.claim_reset_hours > 0:
                reset_hours = self.product.claim_reset_hours
            
            if self.last_claim_time:
                next_dt = self.last_claim_time + timedelta(hours=reset_hours)
            else:
                # For new investments, first claim available N hours after creation
                next_dt = self.created_at + timedelta(hours=reset_hours)

        next_day = timezone.localdate(next_dt) if timezone.is_aware(next_dt) else next_dt.date()
        if ProfitHolidaySettings.is_profit_blocked_today(next_day):
            for _ in range(14):
                next_dt = next_dt + timedelta(days=1)
                next_day = timezone.localdate(next_dt) if timezone.is_aware(next_dt) else next_dt.date()
                if not ProfitHolidaySettings.is_profit_blocked_today(next_day):
                    break
        return next_dt
    
    def get_next_claim_time(self):
        """Get next claim time, calculating if not set"""
        if self.next_claim_time:
            return self.next_claim_time
        else:
            # Calculate and return (but don't save to DB)
            return self.calculate_next_claim_time()
    
    def update_remaining_days(self):
        # Store old values to check for changes
        old_remaining = self.remaining_days
        old_claims_remaining = self.claims_remaining
        old_status = self.status
        
        created_date = self.created_at.date()
        now_dt = timezone.now()
        today = timezone.localdate(now_dt) if timezone.is_aware(now_dt) else now_dt.date()
        as_of = today - timedelta(days=1)
        if as_of < created_date:
            as_of = created_date
        days_passed = (as_of - created_date).days
        days_remaining_by_time = max(0, self.duration_days - days_passed)
        
        try:
            # Jika di-setting untuk memperpanjang durasi pada hari libur, keluarkan hari libur dari hitungan waktu
            if ProfitHolidaySettings.get_settings() and ProfitHolidaySettings.get_settings().extend_duration_on_holidays:
                blocked_days = ProfitHolidaySettings.count_blocked_days(created_date, as_of)
                working_days_passed = max(0, days_passed - blocked_days)
                days_remaining_by_time = max(0, self.duration_days - working_days_passed)
        except Exception:
            pass
        claims_remaining = max(0, self.duration_days - self.claims_count)
        
        self.claims_remaining = claims_remaining
        # Keep the investment claimable until all profit cycles are actually received.
        # If time has elapsed but there are still unclaimed cycles, expose the remaining
        # cycles here so profit does not get burned and principal cannot unlock early.
        self.remaining_days = max(days_remaining_by_time, claims_remaining)

        if claims_remaining <= 0 and self.status == 'ACTIVE':
            self.status = 'COMPLETED'
        elif claims_remaining > 0 and self.status in ('COMPLETED', 'EXPIRED'):
            self.status = 'ACTIVE'
            
        # Only save if values changed to reduce database writes on read operations
        if (self.remaining_days != old_remaining or 
            self.claims_remaining != old_claims_remaining or 
            self.status != old_status):
            self.save(update_fields=['remaining_days', 'claims_remaining', 'status'])

    def has_completed_all_profit_cycles(self):
        return int(self.claims_count or 0) >= int(self.duration_days or 0)

    def get_existing_principal_return_transaction(self):
        if not self.transaction_id:
            return None
        return Transaction.objects.filter(
            user=self.user,
            type='RETURN',
            related_transaction=self.transaction,
        ).order_by('-created_at').first()

    def get_principal_return_block_reason(self):
        if not getattr(self.product, 'return_principal_on_completion', False):
            return 'Produk ini tidak mengaktifkan pengembalian modal'
        if self.principal_returned or self.get_existing_principal_return_transaction():
            return 'Modal sudah pernah dikembalikan'
        if not self.has_completed_all_profit_cycles():
            return 'Semua siklus profit belum selesai diklaim'
        if self.status not in ('COMPLETED', 'EXPIRED'):
            return 'Investasi belum selesai'
        if not self.transaction:
            return 'Transaksi investasi tidak ditemukan'
        return None

    def can_return_principal(self):
        return self.get_principal_return_block_reason() is None

    def return_principal_if_eligible(self):
        with db_transaction.atomic():
            locked_investment = Investment.objects.select_for_update().select_related(
                'product', 'transaction', 'user'
            ).get(pk=self.pk)

            if not getattr(locked_investment.product, 'return_principal_on_completion', False):
                return None
            if locked_investment.principal_returned:
                return None
            if not locked_investment.has_completed_all_profit_cycles():
                return None
            if locked_investment.status not in ('COMPLETED', 'EXPIRED'):
                return None
            if not locked_investment.transaction:
                return None

            existing_return = locked_investment.get_existing_principal_return_transaction()
            if existing_return:
                if not locked_investment.principal_returned:
                    locked_investment.principal_returned = True
                    locked_investment.save(update_fields=['principal_returned'])
                self.principal_returned = True
                return None

            wallet_type = 'BALANCE'
            wallet_field = 'balance'
            amount = abs(locked_investment.total_amount or Decimal('0'))
            if amount <= 0:
                return None

            user_model = locked_investment.user.__class__
            user = user_model.objects.select_for_update().get(pk=locked_investment.user_id)
            current_value = getattr(user, wallet_field)
            setattr(user, wallet_field, current_value + amount)
            user.save(update_fields=[wallet_field])
            trx = Transaction.objects.create(
                user=user,
                product=locked_investment.product,
                upline_user=None,
                trx_id=f'INVRET-{timezone.now().strftime("%Y%m%d%H%M%S")}-{uuid.uuid4().hex[:6].upper()}',
                type='RETURN',
                amount=amount,
                description=f'Principal return for {locked_investment.product.name} investment',
                status='COMPLETED',
                wallet_type=wallet_type,
                related_transaction=locked_investment.transaction,
            )
            locked_investment.principal_returned = True
            locked_investment.save(update_fields=['principal_returned'])
            self.principal_returned = True
            return {
                'amount': amount,
                'wallet_type': wallet_type,
                'transaction_id': trx.trx_id,
                'balance': getattr(user, wallet_field),
            }
    
    class Meta:
        db_table = 'investments'
        ordering = ['-created_at']


class ClaimHistory(models.Model):
    """Model to track individual claim records for detailed history"""
    
    CLAIM_TYPE_CHOICES = [
        ('manual', 'Manual Claim'),
        ('auto', 'Automatic Processing'),
    ]
    
    STATUS_CHOICES = [
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('PENDING', 'Pending'),
    ]
    
    investment = models.ForeignKey(Investment, on_delete=models.CASCADE, related_name='claim_history')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    
    # Claim details
    claim_amount = models.DecimalField(max_digits=15, decimal_places=2)
    claim_type = models.CharField(max_length=20, choices=CLAIM_TYPE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SUCCESS')
    
    # Tracking info
    claim_number = models.IntegerField(help_text='Sequential claim number for this investment')
    remaining_days_at_claim = models.IntegerField(help_text='Remaining days when this claim was made')
    total_claimed_before = models.DecimalField(max_digits=15, decimal_places=2, help_text='Total amount claimed before this claim')
    
    # Transaction reference
    transaction = models.ForeignKey(Transaction, on_delete=models.SET_NULL, null=True, blank=True, help_text='Related profit transaction')
    
    # Metadata
    notes = models.TextField(blank=True, help_text='Additional notes or error messages')
    created_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"Claim #{self.claim_number} - {self.investment} - {self.claim_amount}"
    
    class Meta:
        db_table = 'claim_history'
        ordering = ['-created_at']
        unique_together = ['investment', 'claim_number']
