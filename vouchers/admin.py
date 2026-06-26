from django.contrib import admin
from django.db import transaction, connection, IntegrityError
from .models import Voucher, VoucherUsage
from .forms import VoucherAdminForm


def _sync_table_id_sequence(table_name: str):
    allowed = {"vouchers", "voucher_usages"}
    if table_name not in allowed:
        return

    with connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass(%s)", [f"public.{table_name}"])
        table_ref = cursor.fetchone()[0] or None
        if not table_ref:
            cursor.execute("SELECT to_regclass(%s)", [table_name])
            table_ref = cursor.fetchone()[0] or None
        if not table_ref:
            return

        cursor.execute("SELECT pg_get_serial_sequence(%s, 'id')", [str(table_ref)])
        seq = cursor.fetchone()[0] or None
        if not seq:
            cursor.execute("SELECT pg_get_identity_sequence(%s, 'id')", [str(table_ref)])
            seq = cursor.fetchone()[0] or None
        if not seq:
            return

        cursor.execute(
            f"""
            SELECT setval(
                %s,
                COALESCE(MAX(id), 1),
                MAX(id) IS NOT NULL
            )
            FROM {table_ref}
            """,
            [seq],
        )


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    form = VoucherAdminForm
    list_display = (
        'code', 'type', 'claim_mode', 'amount', 'min_amount', 'max_amount', 'balance_type',
        'usage_limit', 'used_count', 'is_active', 'is_daily_claim', 'start_at', 'expires_at', 'created_at'
    )
    search_fields = ('code',)
    list_filter = ('is_active', 'is_daily_claim', 'balance_type', 'type', 'claim_mode')
    readonly_fields = ('created_at', 'updated_at')

    fieldsets = (
        (None, {
            'fields': ('code', 'claim_mode', 'is_active', 'is_daily_claim', 'start_at', 'expires_at', 'balance_type', 'usage_limit')
        }),
        ('Reward Type', {
            'fields': ('type',)
        }),
        ('Fixed/Random Config', {
            'fields': ('amount', 'min_amount', 'max_amount'),
            'description': 'Isi untuk tipe fixed/random. Untuk random, gunakan min/max.'
        }),
        ('Rank Rewards (tanpa JSON)', {
            'fields': ('rank_1', 'rank_2', 'rank_3', 'rank_4', 'rank_5', 'rank_6'),
            'description': 'Masukkan nominal reward untuk rank 1–6. Tidak perlu input JSON.'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        try:
            with transaction.atomic():
                obj.save()
        except IntegrityError as e:
            if "vouchers_pkey" in str(e):
                _sync_table_id_sequence("vouchers")
                with transaction.atomic():
                    obj.save()
            else:
                raise


@admin.register(VoucherUsage)
class VoucherUsageAdmin(admin.ModelAdmin):
    list_display = (
        'voucher_code', 'user', 'amount_received', 'balance_type', 'used_at'
    )
    search_fields = ('voucher_code', 'user__phone')
    readonly_fields = ('used_at',)

    def save_model(self, request, obj, form, change):
        try:
            with transaction.atomic():
                obj.save()
        except IntegrityError as e:
            if "voucher_usages_pkey" in str(e):
                _sync_table_id_sequence("voucher_usages")
                with transaction.atomic():
                    obj.save()
            else:
                raise


# Register your models here.
