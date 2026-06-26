from django.contrib import admin
from .models import Mission, MissionUserState
from .forms import MissionAdminForm


@admin.register(Mission)
class MissionAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'title', 'description', 'type_display', 'requirement', 'reward', 'reward_balance_display',
        'is_active', 'is_repeatable', 'level', 'created_at'
    )
    search_fields = ('title', 'description', 'type')
    list_filter = ('type', 'is_active', 'is_repeatable', 'reward_balance_type')
    readonly_fields = ('created_at', 'updated_at')
    form = MissionAdminForm
    fieldsets = (
        ('Informasi Misi', {
            'fields': ('title', 'description', 'type', 'level', 'is_active', 'is_repeatable'),
            'description': (
                'Tipe misi: referral (jumlah downline), active_downline (jumlah downline dengan investasi aktif), purchase (downline punya investasi), purchase_self (pembelian/aktivasi oleh user sendiri), '
                'service (downline pernah klaim profit), service_self (klaim profit oleh user sendiri), deposit (downline memiliki deposit), deposit_self (total nominal deposit oleh user sendiri), '
                'withdrawal (jumlah penarikan selesai oleh user). '
                'Level adalah penanda kesulitan (opsional). '
                'Jika aktif, misi akan muncul dan progres dihitung.'
            )
        }),
        ('Syarat & Hadiah', {
            'fields': ('requirement', 'reward', 'reward_balance_type'),
            'description': (
                'Requirement adalah ambang progres untuk 1 kali klaim. '
                'Reward adalah nominal hadiah per klaim. '
                'Dompet hadiah dapat dipilih: balance atau balance_deposit. '
                'Jika misi repeatable, Anda dapat klaim berkali-kali setiap kelipatan requirement tercapai.'
            )
        }),
        ('Level Referral yang Dihitung', {
            'fields': ('referral_levels_field',),
            'description': (
                'Centang level downline yang masuk perhitungan: Level 1, Level 2, Level 3. '
                'Contoh: jika hanya Level 1 dicentang, maka yang dihitung hanya anggota di level 1. '
                'Jika semua dicentang, maka gabungan Level 1+2+3 akan dihitung. '
                'Catatan: pengaturan level ini tidak berlaku untuk tipe withdrawal, service_self, purchase_self, atau deposit_self.'
            )
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def type_display(self, obj):
        return obj.get_type_display()
    type_display.short_description = 'Jenis Misi'

    def reward_balance_display(self, obj):
        return obj.get_reward_balance_type_display()
    reward_balance_display.short_description = 'Dompet Hadiah'


@admin.register(MissionUserState)
class MissionUserStateAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'mission', 'claimed_count', 'last_claimed_at', 'created_at')
    search_fields = ('user__phone', 'mission__description')
    readonly_fields = ('created_at', 'updated_at')
