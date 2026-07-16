from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
import random
import string
from django.contrib.auth.hashers import make_password, check_password


# General setting untuk referral code
class GeneralSetting(models.Model):
    REFERRAL_CODE_CASE_CHOICES = [
        ('upper', 'Huruf Besar Semua (ABCD123)'),
        ('lower', 'Huruf Kecil Semua (abcd123)'),
        ('mixed', 'Campuran Huruf & Angka (AbCd123)'),
        ('numbers_only', 'Angka Saja (123456)'),
        ('letters_only', 'Huruf Saja (ABCDEF)'),
    ]

    referral_code_length = models.PositiveIntegerField(
        default=6,
        help_text='Panjang kode referral (minimum 4, maksimum 20)'
    )
    referral_code_case = models.CharField(
        max_length=20,
        choices=REFERRAL_CODE_CASE_CHOICES,
        default='upper',
        help_text='Format karakter untuk kode referral'
    )
    exclude_similar_chars = models.BooleanField(
        default=True,
        help_text='Hindari karakter yang mirip (0, O, 1, I, l)'
    )
    referral_code_pattern = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text=(
            "Pola karakter, mis. 'L D D L' atau 'A A D D'. "
            "Token: U=huruf besar, l=huruf kecil, L=huruf (besar/kecil), D=angka, A=alphanumeric."
        )
    )
    referral_daily_invite_limit = models.PositiveIntegerField(
        default=20,
        help_text='Batas undang per hari via referral code (0 = tanpa batas)'
    )
    auto_login_on_register = models.BooleanField(
        default=True,
        help_text='Jika ON, user baru langsung mendapatkan token login setelah register'
    )
    registration_bonus_enabled = models.BooleanField(default=False)
    registration_bonus_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    registration_bonus_wallet = models.CharField(max_length=20, choices=[('balance', 'Balance'), ('balance_deposit', 'Balance Deposit')], default='balance')
    deposit_cashback_enabled = models.BooleanField(
        default=True,
        help_text='Jika ON, user mendapat cashback dari deposit sendiri yang berstatus COMPLETED.',
    )
    deposit_cashback_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=1,
        help_text='Persentase cashback dari deposit sendiri. Contoh: 1 = 1%.',
    )
    # Kebijakan perhitungan rank
    RANK_LOGIC_CHOICES = [
        ('OR', 'Salah satu syarat aktif terpenuhi'),
        ('AND', 'Semua syarat aktif harus terpenuhi'),
    ]
    rank_logic = models.CharField(
        max_length=10,
        choices=RANK_LOGIC_CHOICES,
        default='OR',
        help_text='Tentukan apakah evaluasi rank memakai logika OR atau AND untuk basis yang aktif.'
    )
    # Flag basis rank
    rank_use_missions = models.BooleanField(
        default=True,
        help_text='Jika ON, progres misi selesai (distinct) digunakan untuk rank'
    )
    rank_use_downlines_total = models.BooleanField(
        default=False,
        help_text='Jika ON, jumlah anggota downline (hingga level yang dipilih) digunakan untuk rank'
    )
    rank_use_downlines_active = models.BooleanField(
        default=False,
        help_text='Jika ON, jumlah downline aktif (punya investasi status ACTIVE) digunakan untuk rank'
    )
    rank_use_deposit_self_total = models.BooleanField(
        default=False,
        help_text='Jika ON, total deposit sendiri (COMPLETED) digunakan untuk rank'
    )
    rank_use_team_deposit_level_1_total = models.BooleanField(
        default=False,
        help_text='Jika ON, total deposit tim level 1 saja (downline langsung, status COMPLETED) digunakan untuk rank'
    )
    rank_count_levels_upto = models.PositiveSmallIntegerField(
        default=1,
        help_text='Hitung downline hingga level ini (1=Level 1 saja, 2=Level 1+2, dst.)'
    )

    ACTIVE_MEMBER_LOGIC_CHOICES = [
        ('OR', 'Aktif jika salah satu kondisi terpenuhi'),
        ('AND', 'Aktif jika semua kondisi terpenuhi'),
    ]
    active_member_logic = models.CharField(
        max_length=10,
        choices=ACTIVE_MEMBER_LOGIC_CHOICES,
        default='OR',
        help_text='Logika penentuan member aktif berdasarkan kondisi yang diaktifkan di bawah.',
    )
    active_member_use_deposit_completed = models.BooleanField(
        default=True,
        help_text='Jika ON, member dianggap aktif jika punya deposit status COMPLETED.',
    )
    active_member_use_active_investment = models.BooleanField(
        default=False,
        help_text='Jika ON, member dianggap aktif jika punya investasi status ACTIVE dari product yang qualify_as_active_investment=ON.',
    )
    
    # OTP Settings
    otp_enabled = models.BooleanField(
        default=False,
        help_text='Enable WhatsApp OTP verification for registration'
    )
    verifyway_api_key = models.CharField(
        max_length=255,
        blank=True,
        help_text='API Key for VerifyWay WhatsApp OTP (Deprecated)'
    )
    verifynow_customer_id = models.CharField(
        max_length=255,
        blank=True,
        help_text='Customer ID for VerifyNow (Message Central)'
    )
    verifynow_api_key = models.CharField(
        max_length=255,
        blank=True,
        help_text='Base64 Encrypted Password for VerifyNow (Message Central)'
    )
    OTP_PROVIDER_CHOICES = [
        ('AUTO', 'Auto (prioritas: VerifyNow → Fazpass → VerifyWay)'),
        ('VERIFYNOW', 'VerifyNow (Message Central)'),
        ('FAZPASS', 'Fazpass'),
        ('VERIFYWAY', 'VerifyWay (Legacy)'),
    ]
    otp_provider = models.CharField(
        max_length=20,
        choices=OTP_PROVIDER_CHOICES,
        default='AUTO',
        help_text='Pilih provider OTP yang dipakai. Jika AUTO, sistem akan memilih berdasarkan credential yang tersedia.',
    )
    fazpass_merchant_key = models.CharField(
        max_length=255,
        blank=True,
        help_text='Merchant key untuk Fazpass (Bearer token)'
    )
    fazpass_gateway_key = models.CharField(
        max_length=255,
        blank=True,
        help_text='Gateway key untuk Fazpass OTP'
    )
    # WhatsApp Number Check (Backup)
    whatsapp_check_enabled = models.BooleanField(
        default=False,
        help_text='Jika ON, verifikasi nomor WA aktif saat register (backup/alternatif OTP)'
    )
    checknumber_api_key = models.CharField(
        max_length=255,
        blank=True,
        help_text='API Key untuk checknumber.ai (pemeriksa nomor WhatsApp)'
    )
    require_withdraw_pin_on_register = models.BooleanField(default=False)
    require_withdraw_pin_on_purchase = models.BooleanField(default=False)

    CURRENCY_CHOICES = [
        ("IDR", "IDR (Rupiah)"),
        ("USD", "USD (US Dollar)"),
        ("EUR", "EUR (Euro)"),
        ("SGD", "SGD (Singapore Dollar)"),
        ("MYR", "MYR (Ringgit)"),
        ("PHP", "PHP (Philippine Peso)"),
    ]
    currency_code = models.CharField(
        max_length=10,
        choices=CURRENCY_CHOICES,
        default="IDR",
        help_text="Pilih currency untuk format tampilan nominal (simbol, pemisah ribuan, pemisah desimal).",
    )
    secondary_currency_code = models.CharField(
        max_length=10,
        choices=CURRENCY_CHOICES,
        blank=True,
        default="",
        help_text="Currency kedua (opsional). Jika diisi, sistem menampilkan 2 currency (main + secondary) dan bisa konversi secondary ↔ main via rate.",
    )
    secondary_rate_per_main = models.DecimalField(
        max_digits=20,
        decimal_places=6,
        default=1,
        help_text="Kurs SECONDARY per 1 MAIN. Contoh: MAIN=USD, SECONDARY=PHP, jika 1 USD = 62 PHP, isi 62.",
    )
    
    frontend_url = models.URLField(
        max_length=255,
        blank=True,
        null=True,
        help_text='URL domain frontend (contoh: https://my-frontend.com)'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'General Setting'
        verbose_name_plural = 'General Settings'

    def __str__(self):
        return f"Referral Code: {self.referral_code_case}/{self.referral_code_length}"

    def get_allowed_currency_codes(self):
        main = (self.currency_code or "IDR").strip().upper()
        secondary = (self.secondary_currency_code or "").strip().upper()
        if secondary and secondary != main:
            return [main, secondary]
        return [main]


class User(AbstractUser):
    """Custom User model extending Django's AbstractUser."""
    
    email = models.EmailField(unique=True)
    full_name = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=15, unique=True)
    telegram = models.CharField(max_length=255, blank=True, default='')
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    balance_deposit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    balance_hold = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    balance_cashback = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    banned_status = models.BooleanField(default=False)
    referral_by = models.ForeignKey('self', on_delete=models.SET_NULL, blank=True, null=True, related_name='referrals')
    referral_code = models.CharField(max_length=20, unique=True, blank=True, null=True)
    # Hashed 6-digit PIN for withdrawals (set by user via API)
    withdraw_pin = models.CharField(max_length=128, blank=True, null=True)

    rank = models.PositiveSmallIntegerField(blank=True, null=True)
    is_account_non_expired = models.BooleanField(default=True)
    is_account_non_locked = models.BooleanField(default=True)
    is_credentials_non_expired = models.BooleanField(default=True)
    is_enabled = models.BooleanField(default=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    USERNAME_FIELD = 'phone'
    REQUIRED_FIELDS = ['username', 'email', 'full_name']
    
    def __str__(self):
        return self.email
    
    class Meta:
        verbose_name = 'User'
        verbose_name_plural = 'Users'
        
    def generate_referral_code(self):
        """Generate referral code mengikuti GeneralSetting; dukung pola spesifik jika diisi."""
        settings_obj = GeneralSetting.objects.order_by('-updated_at').first()
        code_len = 6
        case_mode = 'upper'
        exclude_similar = True
        pattern = None
        if settings_obj:
            code_len = max(4, min(20, settings_obj.referral_code_length or 6))
            case_mode = settings_obj.referral_code_case or 'upper'
            exclude_similar = bool(settings_obj.exclude_similar_chars)
            pattern = (settings_obj.referral_code_pattern or '').strip()

        def remove_similar(s: str) -> str:
            if not exclude_similar:
                return s
            for ch in ['0', 'O', '1', 'I', 'l']:
                s = s.replace(ch, '')
            return s

        def charset_for_token(tok: str) -> str:
            if tok == 'U':
                return remove_similar(string.ascii_uppercase)
            if tok == 'l':
                return remove_similar(string.ascii_lowercase)
            if tok == 'L':
                return remove_similar(string.ascii_letters)
            if tok == 'D':
                return remove_similar(string.digits)
            # 'A' atau default: alphanumeric
            return remove_similar(string.ascii_letters + string.digits)

        # Jika pola diisi, generate sesuai urutan token
        tokens = None
        if pattern:
            tokens = pattern.replace(' ', '')
            # Validasi token hanya berisi U, l, L, D, A
            valid_tokens = {'U', 'l', 'L', 'D', 'A'}
            if not set(tokens).issubset(valid_tokens):
                tokens = None  # fallback bila pola tidak valid
        if tokens:
            # Panjang kode mengikuti jumlah token pada pola
            code_chars = []
            for t in tokens:
                cs = charset_for_token(t)
                if len(cs) < 2:
                    cs = remove_similar(string.ascii_uppercase + '23456789')
                code_chars.append(random.choice(cs))
            code = ''.join(code_chars)
        else:
            # Fallback: gunakan case_mode dan code_len
            if case_mode == 'numbers_only':
                chars = string.digits
            elif case_mode == 'letters_only':
                chars = string.ascii_letters
            elif case_mode == 'lower':
                chars = string.ascii_lowercase + string.digits
            elif case_mode == 'mixed':
                chars = string.ascii_letters + string.digits
            else:  # 'upper'
                chars = string.ascii_uppercase + string.digits
            chars = remove_similar(chars)
            if len(chars) < 2:
                chars = remove_similar(string.ascii_uppercase + '23456789')
            code = ''.join(random.choices(chars, k=code_len))

        while User.objects.filter(referral_code=code).exists():
            # Regenerate jika bentrok; gunakan metode yang sama
            if tokens:
                code = ''.join(random.choice(charset_for_token(t)) for t in tokens)
            else:
                code = ''.join(random.choices(chars, k=code_len))
        return code

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = self.generate_referral_code()
        super().save(*args, **kwargs)

    def set_withdraw_pin(self, raw_pin: str):
        """Set user's withdraw PIN using Django's password hasher."""
        self.withdraw_pin = make_password(raw_pin)
        self.save(update_fields=["withdraw_pin"])

    def check_withdraw_pin(self, raw_pin: str) -> bool:
        """Verify provided PIN against stored hashed PIN."""
        if not self.withdraw_pin:
            return False
        return check_password(raw_pin, self.withdraw_pin)


class RankLevel(models.Model):
    """Konfigurasi syarat misi total untuk pencapaian rank tertentu."""
    rank = models.PositiveSmallIntegerField(unique=True)
    title = models.CharField(max_length=100, default='Rank')
    description = models.TextField(blank=True, null=True, help_text='Deskripsi untuk rank ini.')
    missions_required_total = models.PositiveIntegerField(
        help_text=(
            'Ambang jumlah progres untuk rank ini. Jika basis=missions, ini adalah total misi selesai (distinct). '
            'Jika basis=downlines_total, isi dengan jumlah anggota downline. Jika basis=downlines_active, isi dengan jumlah downline aktif.'
        )
    )
    downlines_total_required = models.PositiveIntegerField(default=0)
    downlines_active_required = models.PositiveIntegerField(default=0)
    deposit_self_total_required = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    team_deposit_level_1_total_required = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'rank_levels'
        ordering = ['rank']
        verbose_name = 'Rank Level'
        verbose_name_plural = 'Rank Levels'

    def __str__(self):
        return f"Rank {self.rank} - {self.title} (requires {self.missions_required_total})"


class UserAddress(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='addresses')
    recipient_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    address_details = models.TextField()
    house_number = models.CharField(max_length=50, blank=True, null=True)
    is_primary = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_primary', '-created_at']
        verbose_name = 'User Address'
        verbose_name_plural = 'User Addresses'

    def save(self, *args, **kwargs):
        if self.is_primary:
            # Set other addresses of this user to not primary
            UserAddress.objects.filter(user=self.user, is_primary=True).update(is_primary=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.recipient_name} - {self.address_details}"


class PhoneOTP(models.Model):
    PROVIDER_CHOICES = [
        ('VERIFYNOW', 'VerifyNow'),
        ('VERIFYWAY', 'VerifyWay (Legacy)'),
        ('FAZPASS', 'Fazpass'),
    ]

    phone = models.CharField(max_length=20, unique=True)
    otp_code = models.CharField(max_length=6, blank=True, null=True)
    verification_id = models.CharField(max_length=100, blank=True, null=True)
    provider = models.CharField(max_length=20, blank=True, null=True, choices=PROVIDER_CHOICES)
    created_at = models.DateTimeField(auto_now=True)  # Updated on every save (new OTP)
    verified = models.BooleanField(default=False)
    
    class Meta:
        verbose_name = 'Phone OTP'
        verbose_name_plural = 'Phone OTPs'

    def __str__(self):
        return f"{self.phone} - {self.otp_code}"


class AdminDecodeTool(models.Model):
    class Meta:
        managed = False
        verbose_name = 'Decode API Response'
        verbose_name_plural = 'Decode API Response'

    def __str__(self):
        return 'Decode API Response'
