from django.contrib import admin
from .models import Bank, UserBank, BankSettings


@admin.register(BankSettings)
class BankSettingsAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'max_banks_per_user',
        'max_banks_idr_per_user',
        'max_banks_foreign_per_user',
        'created_at',
        'updated_at',
    )
    readonly_fields = ('created_at', 'updated_at')
    
    def has_add_permission(self, request):
        # Hanya boleh ada satu settings record
        return not BankSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        # Tidak boleh delete settings
        return False


@admin.register(Bank)
class BankAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'code', 'name', 'currency_code', 'is_active', 'min_withdrawal', 'max_withdrawal',
        'withdrawal_fee', 'withdrawal_fee_fixed', 'processing_time', 'created_at'
    )
    search_fields = ('code', 'name')
    list_filter = ('currency_code', 'is_active',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(UserBank)
class UserBankAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'bank', 'account_name', 'account_number', 'phone', 'is_default', 'created_at')
    search_fields = ('user__phone', 'bank__name', 'account_number', 'phone')
    list_filter = ('bank', 'is_default')
    readonly_fields = ('created_at', 'updated_at')
    autocomplete_fields = ('user', 'bank')
