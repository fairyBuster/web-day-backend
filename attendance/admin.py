from django.contrib import admin
from .models import AttendanceSettings, AttendanceLog
from .forms import AttendanceSettingsAdminForm, DAILY_ATTENDANCE_PROGRAM_DAYS


@admin.register(AttendanceSettings)
class AttendanceSettingsAdmin(admin.ModelAdmin):
    form = AttendanceSettingsAdminForm
    list_display = (
        'id', 'balance_source', 'reward_type', 'fixed_amount', 'min_amount', 'max_amount',
        'consecutive_bonus_enabled', 'bonus_claim_separate_enabled', 'bonus_7_days', 'bonus_30_days', 'is_active', 'created_at'
    )

    def has_add_permission(self, request):
        # Cukup satu konfigurasi, kalau sudah ada maka tidak bisa tambah baru
        return not AttendanceSettings.objects.exists()
    list_filter = ('is_active', 'balance_source', 'reward_type', 'consecutive_bonus_enabled', 'bonus_claim_separate_enabled')
    search_fields = ('id',)
    readonly_fields = ('created_at', 'updated_at')

    def _resolve_cycle_days(self, request, obj=None):
        return DAILY_ATTENDANCE_PROGRAM_DAYS

    def _resolve_reward_type(self, request, obj=None):
        reward_type = None
        if request.method == 'POST':
            reward_type = (request.POST.get('reward_type') or '').strip() or None
        if reward_type is None:
            reward_type = getattr(obj, 'reward_type', None)
        return reward_type

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        cycle_days = self._resolve_cycle_days(request, obj)
        reward_type = self._resolve_reward_type(request, obj)

        if 'consecutive_bonus_enabled' in form.base_fields:
            if reward_type == 'daily':
                form.base_fields['consecutive_bonus_enabled'].help_text = (
                    f'Aktifkan bonus untuk program daily 7 hari. '
                    f'Jika ON, bonus hanya tersedia saat user mencapai hari terakhir program (Day {cycle_days}).'
                )
            else:
                form.base_fields['consecutive_bonus_enabled'].help_text = (
                    'Aktifkan bonus beruntun berdasarkan milestone streak. '
                    'Jika ON, user bisa mendapat bonus saat mencapai 7 hari dan 30 hari berturut-turut.'
                )

        if 'bonus_claim_separate_enabled' in form.base_fields:
            form.base_fields['bonus_claim_separate_enabled'].help_text = (
                'Jika ON, bonus tidak ikut dibayar saat klaim attendance harian dan harus diklaim manual lewat claim bonus. '
                'Jika OFF, bonus otomatis ikut masuk ke klaim attendance saat syarat bonus terpenuhi.'
            )

        return form

    def get_fieldsets(self, request, obj=None):
        cycle_days = self._resolve_cycle_days(request, obj)
        reward_type = self._resolve_reward_type(request, obj)

        daily_fields = ('daily_cycle_days',) + tuple(f'day_{i}' for i in range(1, cycle_days + 1))
        rank_levels = []
        try:
            from accounts.models import RankLevel

            rank_levels = list(RankLevel.objects.order_by("rank").values_list("rank", flat=True))
        except Exception:
            rank_levels = []
        if not rank_levels:
            rank_levels = list(range(1, 7))
        max_rank_fields = getattr(AttendanceSettingsAdminForm, "MAX_RANK_FIELDS", 50)
        rank_fields = tuple(f"rank_{int(r)}" for r in rank_levels if int(r) <= int(max_rank_fields))

        if reward_type == 'daily':
            bonus_fields = ('consecutive_bonus_enabled', 'bonus_claim_separate_enabled', 'bonus_7_days')
            bonus_desc = (
                f'Untuk mode Daily Sequence, bonus diberikan saat user mencapai hari terakhir program (Day {cycle_days}). '
                f'Sistem tidak mengulang ke hari 1 lagi setelah selesai, dan hari yang terlewat akan hangus. '
                f'`Consecutive bonus enabled` mengaktifkan bonus ini. '
                f'`Bonus claim separate enabled` menentukan apakah bonus dibayar otomatis saat claim attendance atau harus diklaim manual terpisah.'
            )
        else:
            bonus_fields = ('consecutive_bonus_enabled', 'bonus_claim_separate_enabled', 'bonus_7_days', 'bonus_30_days')
            bonus_desc = (
                'Untuk mode selain Daily Sequence, bonus memakai milestone streak 7 hari dan 30 hari. '
                '`Consecutive bonus enabled` mengaktifkan bonus milestone tersebut. '
                '`Bonus claim separate enabled` menentukan apakah bonus dibayar otomatis saat claim attendance atau harus diklaim manual terpisah.'
            )

        fieldsets = (
            (None, {
                'fields': ('balance_source', 'reward_type', 'is_active')
            }),
            ('Base Reward', {
                'fields': ('fixed_amount', 'min_amount', 'max_amount')
            }),
            ('Rank Rewards (tanpa JSON)', {
                'fields': rank_fields,
                'description': 'Isi nominal untuk setiap rank yang tersedia. Tidak perlu JSON.'
            }),
            ('Daily Rewards (Cycle)', {
                'fields': daily_fields,
                'description': f'Isi nominal untuk setiap hari dalam program attendance (1-{cycle_days}). Setelah hari {cycle_days}, attendance selesai permanen, tidak mengulang ke hari 1, dan hari yang tidak diklaim dianggap hangus.'
            }),
            ('Bonus Beruntun', {
                'fields': bonus_fields,
                **({'description': bonus_desc} if bonus_desc else {})
            }),
            ('Timestamps', {
                'fields': ('created_at', 'updated_at'),
                'classes': ('collapse',)
            }),
        )
        return fieldsets


@admin.register(AttendanceLog)
class AttendanceLogAdmin(admin.ModelAdmin):
    list_display = ('user_phone', 'date', 'streak_count', 'amount', 'created_at')
    search_fields = ('user__phone',)
    list_filter = ('date',)
    readonly_fields = ('created_at',)

    def user_phone(self, obj):
        return obj.user.phone
    user_phone.short_description = 'Phone'
