from django.conf import settings
from django.db import models
from django.utils import timezone


class Mission(models.Model):
    TYPE_CHOICES = [
        ('purchase', 'Berdasarkan pembelian/aktivasi'),
        ('purchase_self', 'Berdasarkan pembelian/aktivasi oleh user sendiri'),
        ('service', 'Berdasarkan klaim layanan/profit'),
        ('service_self', 'Berdasarkan klaim layanan/profit oleh user sendiri'),
        ('deposit', 'Berdasarkan deposit oleh downline'),
        ('deposit_self', 'Berdasarkan total deposit oleh user sendiri'),
        ('referral', 'Berdasarkan referral/downline'),
        ('active_downline', 'Berdasarkan total downline aktif'),
        ('withdrawal', 'Berdasarkan penarikan (withdraw) selesai'),
    ]

    BALANCE_CHOICES = [
        ('balance', 'Saldo Utama'),
        ('balance_deposit', 'Saldo Deposit'),
    ]

    title = models.CharField(
        max_length=100,
        default='Judul Misi',
        verbose_name='Judul',
        help_text='Judul singkat misi (tampil di admin dan aplikasi)'
    )
    description = models.CharField(
        max_length=255,
        verbose_name='Deskripsi',
        help_text='Deskripsi singkat misi'
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='Aktif',
        help_text='Jika tidak aktif, misi disembunyikan dan progres tidak dihitung'
    )
    is_repeatable = models.BooleanField(
        default=False,
        verbose_name='Dapat diklaim berulang',
        help_text='Jika aktif, misi dapat diklaim berkali-kali setiap kelipatan requirement tercapai'
    )
    level = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name='Level (opsional)',
        help_text='Label tingkat/kesulitan; tidak memengaruhi perhitungan'
    )
    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        verbose_name='Jenis Misi',
        help_text='Pilih jenis misi: referral/purchase/purchase_self/service/service_self/deposit_self/withdrawal sesuai logika perhitungan'
    )
    requirement = models.PositiveIntegerField(
        verbose_name='Requirement',
        help_text='Ambang progres untuk 1 kali klaim (contoh: 20 berarti setiap 20 progres dapat klaim 1x)'
    )
    reward = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        verbose_name='Hadiah per klaim',
        help_text='Nominal hadiah per klaim'
    )
    reward_balance_type = models.CharField(
        max_length=20,
        choices=BALANCE_CHOICES,
        default='balance',
        verbose_name='Dompet hadiah',
        help_text='Pilih dompet penyaluran hadiah: Saldo Utama atau Saldo Deposit'
    )
    # Referral levels to include for counting: e.g., [1], [1,2], [1,2,3]
    referral_levels = models.JSONField(
        default=list,
        blank=True,
        verbose_name='Level downline yang dihitung',
        help_text='Daftar level downline (mis. [1], [1,2], [1,2,3]) yang disertakan dalam perhitungan'
    )

    created_at = models.DateTimeField(default=timezone.now, verbose_name='Dibuat')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Diubah')

    class Meta:
        db_table = 'missions'
        ordering = ['-created_at']

    def __str__(self):
        return f"Mission {self.id} - {self.type}: {self.description}"


class MissionUserState(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    mission = models.ForeignKey(Mission, on_delete=models.CASCADE)
    claimed_count = models.PositiveIntegerField(default=0)
    last_claimed_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'mission_user_states'
        unique_together = ('user', 'mission')

    def __str__(self):
        return f"{self.user.phone} - Mission {self.mission_id} (claimed {self.claimed_count})"
