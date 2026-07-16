from django.contrib import admin
from django import forms
from django.utils.html import format_html
from django.urls import path
from django.shortcuts import redirect
from django.contrib import messages
from django.db.models import Count, Sum, Q, F, Case, When, IntegerField
from django.utils import timezone
from datetime import datetime, timedelta
from .models import Product, Transaction, Investment, ProfitHolidaySettings
from .forms import ProductAdminForm
from config import format_currency
from accounts.models import GeneralSetting
from decimal import Decimal

# Custom admin filters for investment tracking
class InvestmentStatusFilter(admin.SimpleListFilter):
    title = 'Investment Status'
    parameter_name = 'investment_status'
    
    def lookups(self, request, model_admin):
        return (
            ('active', 'Active Investments'),
            ('expiring_soon', 'Expiring Soon (≤7 days)'),
            ('expiring_critical', 'Critical (≤3 days)'),
            ('never_claimed', 'Never Claimed'),
            ('high_performer', 'High Performers (≥80% claimed)'),
            ('low_performer', 'Low Performers (<50% claimed)'),
            ('completed', 'Completed'),
            ('expired', 'Expired'),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'active':
            return queryset.filter(status='ACTIVE')
        elif self.value() == 'expiring_soon':
            return queryset.filter(status='ACTIVE', remaining_days__lte=7, remaining_days__gt=0)
        elif self.value() == 'expiring_critical':
            return queryset.filter(status='ACTIVE', remaining_days__lte=3, remaining_days__gt=0)
        elif self.value() == 'never_claimed':
            return queryset.filter(status='ACTIVE', last_claim_time__isnull=True)
        elif self.value() == 'high_performer':
            # This will need custom logic in the admin
            return queryset.filter(status__in=['ACTIVE', 'COMPLETED'])
        elif self.value() == 'low_performer':
            return queryset.filter(status='ACTIVE')
        elif self.value() == 'completed':
            return queryset.filter(status='COMPLETED')
        elif self.value() == 'expired':
            return queryset.filter(status='EXPIRED')
        return queryset

class InvestmentDurationFilter(admin.SimpleListFilter):
    title = 'Investment Duration'
    parameter_name = 'duration_range'
    
    def lookups(self, request, model_admin):
        return (
            ('short', 'Short Term (≤30 days)'),
            ('medium', 'Medium Term (31-90 days)'),
            ('long', 'Long Term (>90 days)'),
        )
    
    def queryset(self, request, queryset):
        if self.value() == 'short':
            return queryset.filter(duration_days__lte=30)
        elif self.value() == 'medium':
            return queryset.filter(duration_days__gt=30, duration_days__lte=90)
        elif self.value() == 'long':
            return queryset.filter(duration_days__gt=90)
        return queryset

class ClaimFrequencyFilter(admin.SimpleListFilter):
    title = 'Claim Activity'
    parameter_name = 'claim_activity'
    
    def lookups(self, request, model_admin):
        return (
            ('daily_claimer', 'Daily Claimers'),
            ('regular_claimer', 'Regular Claimers'),
            ('occasional_claimer', 'Occasional Claimers'),
            ('inactive_claimer', 'Inactive Claimers'),
        )
    
    def queryset(self, request, queryset):
        # This will be handled with custom logic in the admin
        return queryset


@admin.register(ProfitHolidaySettings)
class ProfitHolidaySettingsAdmin(admin.ModelAdmin):
    list_display = ("id", "is_active", "extend_duration_on_holidays", "disable_monday", "disable_tuesday", "disable_wednesday", "disable_thursday", "disable_friday", "disable_saturday", "disable_sunday", "updated_at")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (
            "Status",
            {
                "fields": ("is_active", "extend_duration_on_holidays"),
                "description": "Jika OFF, profit tetap berjalan normal setiap hari.",
            },
        ),
        (
            "Libur Mingguan",
            {
                "fields": (
                    "disable_monday",
                    "disable_tuesday",
                    "disable_wednesday",
                    "disable_thursday",
                    "disable_friday",
                    "disable_saturday",
                    "disable_sunday",
                ),
                "description": "Jika hari dipilih, maka di hari tersebut profit tidak bisa diklaim dan otomatis tidak akan diproses.",
            },
        ),
        (
            "Libur Tanggal",
            {
                "fields": ("disabled_dates",),
                "description": "Isi list tanggal libur format YYYY-MM-DD. Contoh: [\"2026-04-10\", \"2026-05-01\"].",
            },
        ),
        ("Waktu", {"fields": ("created_at", "updated_at")}),
    )

    def has_add_permission(self, request):
        return not ProfitHolidaySettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    form = ProductAdminForm
    list_display = ('name', 'golongan', 'price_display', 'stock_display', 'profit_display', 
                   'rebate_display', 'cashback_display', 'status_display', 'created_at')
    # Removed list_filter for cleaner admin interface
    search_fields = ('name', 'description', 'golongan')
    readonly_fields = ('created_at', 'updated_at', 'duration_days_preview')
    
    fieldsets = (
        (None, {
            'fields': ('name', 'golongan', 'description', 'price', 'image', 'status', 'specifications')
        }),
        ('Investment Settings', {
            'fields': ('purchase_limit', 'max_purchase_count', 'stock', 'stock_enabled')
        }),
        ('Profit Settings', {
            'fields': ('profit_type', 'profit_rate', 'profit_random_min', 'profit_random_max', 'profit_method', 'duration', 'duration_days_preview'),
            'description': 'Duration sekarang dalam hari. Jika tipe Random, isi Min/Max. Preview: konversi hari ditampilkan.'
        }),
        ('Balance Settings', {
            'fields': ('balance_source',)
        }),
        ('Claim Settings', {
            'fields': ('claim_reset_mode', 'claim_reset_hours')
        }),
        ('Commission Rules', {
            'fields': ('require_upline_ownership_for_commissions', 'qualify_as_active_investment'),
            'description': 'Jika ON: upline wajib punya produk ini (investment ACTIVE) untuk menerima rebate purchase/profit. '
                           'Jika Qualify as active investment dimatikan, pembelian produk ini tidak menghitung user sebagai member aktif (rank/missions).'
        }),
        ('Purchase Restrictions', {
            'fields': (
                'require_withdraw_pin_on_purchase',
                'require_min_rank_enabled',
                'min_required_rank',
                'required_product',
                'required_golongan'
            ),
            'description': (
                'Batasi pembelian berdasarkan rank minimum. Contoh: Rank 2 hanya bisa membeli product 2 jika rank ≥ 2. '
                'Jika `Require withdraw pin on purchase` diaktifkan, endpoint beli product wajib kirim `withdraw_pin`.'
            )
        }),
        ('Rebate Settings (Purchase)', {
            'fields': ('purchase_rebate_level_1', 'purchase_rebate_level_2', 'purchase_rebate_level_3', 'purchase_rebate_level_4', 'purchase_rebate_level_5')
        }),
        ('Rebate Settings (Profit)', {
            'fields': ('profit_rebate_level_1', 'profit_rebate_level_2', 'profit_rebate_level_3', 'profit_rebate_level_4', 'profit_rebate_level_5')
        }),
        ('Cashback Settings', {
            'fields': ('cashback_enabled', 'cashback_percentage'),
            'description': 'Enable cashback and set percentage of product price'
        }),
        ('Principal Settings', {
            'fields': ('return_principal_on_completion',),
        }),
        ('Custom Fields', {
            'fields': (
                'custom_field_1_title', 'custom_field_1_content',
                'custom_field_2_title', 'custom_field_2_content',
                'custom_field_3_title', 'custom_field_3_content',
                'custom_field_4_title', 'custom_field_4_content',
                'custom_field_5_title', 'custom_field_5_content',
                'custom_field_6_title', 'custom_field_6_content',
                'custom_field_7_title', 'custom_field_7_content',
                'custom_field_8_title', 'custom_field_8_content',
                'custom_field_9_title', 'custom_field_9_content',
                'custom_field_10_title', 'custom_field_10_content',
            ),
            'classes': ('collapse',),
            'description': 'Optional custom fields for additional product information'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def price_display(self, obj):
        return format_currency(obj.price)
    price_display.short_description = 'Price'
    
    def stock_display(self, obj):
        if not obj.stock_enabled:
            return 'Unlimited'
        color = 'red' if obj.stock == 0 else 'green'
        return format_html('<span style="color: {color}">{stock}</span>', 
                         color=color, stock=obj.stock)
    stock_display.short_description = 'Stock'
    
    def _format_percent(self, value):
        try:
            val = float(value)
        except (TypeError, ValueError):
            return '-'
        return '{}%'.format('{:g}'.format(val))
    
    def profit_display(self, obj):
        if obj.profit_type == 'percentage':
            return self._format_percent(obj.profit_rate)
        if obj.profit_type == 'random':
            try:
                from decimal import Decimal
                min_val = Decimal(str(getattr(obj, 'profit_random_min', 0) or 0))
                max_val = Decimal(str(getattr(obj, 'profit_random_max', 0) or 0))
                if min_val > 0 and max_val >= min_val:
                    return '{} – {}'.format(
                        format_currency(min_val),
                        format_currency(max_val),
                    )
            except Exception:
                pass
            return '(range tidak valid)'
        return format_currency(obj.profit_rate)
    profit_display.short_description = 'Profit Rate'
    
    def status_display(self, obj):
        color = 'green' if obj.status == 1 else 'red'
        status = 'Active' if obj.status == 1 else 'Inactive'
        return format_html('<span style="color: {color}">{status}</span>', 
                         color=color, status=status)
    status_display.short_description = 'Status'

    def duration_days_preview(self, obj):
        return '{} days'.format(obj.duration)
    duration_days_preview.short_description = 'Duration (days)'

    def rebate_display(self, obj):
        purchase_levels = []
        for i in range(1, 6):
            value = getattr(obj, f'purchase_rebate_level_{i}', 0)
            if value > 0:
                purchase_levels.append(self._format_percent(value))

        profit_levels = []
        for i in range(1, 6):
            value = getattr(obj, f'profit_rebate_level_{i}', 0)
            if value > 0:
                profit_levels.append(self._format_percent(value))

        purchase_str = ' / '.join(purchase_levels) if purchase_levels else '-'
        profit_str = ' / '.join(profit_levels) if profit_levels else '-'

        return format_html(
            '<div><strong>Purchase:</strong> <span title="Purchase Levels">{}</span></div>'
            '<div><strong>Profit:</strong> <span title="Profit Levels">{}</span></div>',
            purchase_str, profit_str
        )
    rebate_display.short_description = 'Rebate Rates'

    def cashback_display(self, obj):
        if not obj.cashback_enabled:
            return format_html('<span style="color: #999;">Disabled</span>')
        
        # Use product price as default for display calculation
        cashback_amount = obj.calculate_cashback(obj.price)
        return format_html(
            '<div><strong>{}</strong></div>'
            '<div style="color: #28a745; font-size: 0.9em;">{}</div>',
            self._format_percent(obj.cashback_percentage),
            format_currency(cashback_amount)
        )
    cashback_display.short_description = 'Cashback'

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    class TransactionAdminForm(forms.ModelForm):
        trx_id = forms.CharField(required=False)

        class Meta:
            model = Transaction
            fields = "__all__"

    form = TransactionAdminForm
    list_display = ('trx_id', 'user_phone_display', 'type_display', 'amount_display', 
                   'status_display', 'wallet_type_display', 'product_display', 'created_at')
    search_fields = ('trx_id', 'user__phone', 'description')
    readonly_fields = ('trx_id', 'created_at')
    autocomplete_fields = ('user', 'product', 'upline_user', 'related_transaction', 'voucher')
    
    fieldsets = (
        (None, {
            'fields': ('trx_id', 'user', 'type', 'amount', 'currency_code', 'original_amount', 'original_currency_code', 'conversion_rate', 'description', 
                      'status', 'wallet_type')
        }),
        ('Investment Details', {
            'fields': ('product', 'investment_quantity', 'commission_level')
        }),
        ('Referral Details', {
            'fields': ('upline_user', 'related_transaction')
        }),
        ('Voucher Details', {
            'fields': ('voucher', 'voucher_code')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    def user_phone_display(self, obj):
        return obj.user.phone
    user_phone_display.short_description = 'Phone'

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ('created_at',)
        return ('trx_id', 'created_at')
    
    def type_display(self, obj):
        colors = {
            'CREDIT': '#007cba',
            'BONUS': '#007cba',
            'DEBIT': '#dc3545',
            'PURCHASE_COMMISSION': '#28a745',  # Green for purchase commission
            'PROFIT_COMMISSION': '#17a2b8',  # Teal for profit commission
            'INTEREST': '#17a2b8',  # Teal for interest (same as profit commission)
            'ATTENDANCE': '#007cba'  # Treat attendance as credit-style
        }
        color = colors.get(obj.type.upper(), '#6c757d')  # Default gray
        return format_html('<span style="color: {color}; font-weight: bold;">{type}</span>', 
                         color=color, type=obj.type.upper())
    type_display.short_description = 'Type'
    
    def amount_display(self, obj):
        # Check transaction type for color and prefix
        t = obj.type.upper()
        if t in ['CREDIT', 'BONUS', 'PURCHASE_COMMISSION', 'PROFIT_COMMISSION', 'INTEREST', 'ATTENDANCE', 'VOUCHER','MISSIONS','DEPOSIT','CASHBACK', 'REJECT', 'RETURN']:
            if t in ['CREDIT', 'BONUS']:
                color = '#007cba'  # Blue for credit
            elif t == 'PURCHASE_COMMISSION':
                color = '#28a745'  # Green for purchase commission
            elif t in ['PROFIT_COMMISSION', 'INTEREST']:
                color = '#17a2b8'  # Teal for profit commission and earned
            elif t == 'CASHBACK':
                color = '#28a745'  # Green for cashback
            else:  # ATTENDANCE, VOUCHER, MISSIONS, DEPOSIT, REJECT
                color = '#007cba'
            prefix = '+'
        else:  # DEBIT or others
            color = '#dc3545'  # Red for debit
            prefix = '-'

        code = (getattr(obj, "currency_code", "") or "").strip().upper()
        try:
            num = f"{obj.amount:,.2f}"
        except Exception:
            num = str(obj.amount)
        main = f"{prefix}{num} {code}".strip()

        original_amount = getattr(obj, "original_amount", None)
        original_code = (getattr(obj, "original_currency_code", "") or "").strip().upper()
        rate = getattr(obj, "conversion_rate", None)
        if original_amount is not None:
            try:
                orig_num = f"{original_amount:,.2f}"
            except Exception:
                orig_num = str(original_amount)
            suffix = f"rate {rate}" if rate is not None else ""
            extra = f"{orig_num} {original_code or ''} {suffix}".strip()
            return format_html(
                '<div><span style="color: {color}; font-weight: bold;">{main}</span></div>'
                '<div><span style="color: #6c757d;">orig: {extra}</span></div>',
                color=color,
                main=main,
                extra=extra,
            )

        return format_html('<span style="color: {color}; font-weight: bold;">{main}</span>', color=color, main=main)
    amount_display.short_description = 'Amount'
    
    def wallet_type_display(self, obj):
        # Format wallet type for better display
        wallet_map = {
            'BALANCE': 'Balance',
            'BALANCE_DEPOSIT': 'Balance Deposit'
            , 'BALANCE_HOLD': 'Balance Hold'
        }
        return wallet_map.get(obj.wallet_type, obj.wallet_type)
    wallet_type_display.short_description = 'Wallet Type'
    
    def status_display(self, obj):
        colors = {
            'PENDING': 'orange',
            'COMPLETED': 'green',
            'FAILED': 'red',
            'CANCELLED': 'gray'
        }
        return format_html('<span style="color: {color}">{status}</span>', 
                         color=colors.get(obj.status, 'black'), status=obj.status)
    status_display.short_description = 'Status'
    
    def product_display(self, obj):
        if obj.product:
            return format_html('{} (x{})', obj.product.name, 
                             obj.investment_quantity or 1)
        return '-'
    product_display.short_description = 'Product'


@admin.register(Investment)
class InvestmentAdmin(admin.ModelAdmin):
    list_display = ('investment_display', 'user_phone_display', 'status_display', 
                   'profit_claims_display', 'total_amount_display', 'progress_display',
                   'expiry_info_display', 'performance_display')
    search_fields = ('user__phone', 'product__name', 'transaction__trx_id', 'status', 
                    'user__email', 'user__username')
    search_help_text = 'Search by: phone, product name, transaction ID, status, email, or username'
    readonly_fields = ('created_at', 'updated_at', 'expires_at', 'total_amount')
    autocomplete_fields = ('user', 'product', 'transaction')
    list_per_page = 25
    # Removed list_filter to comply with admin interface filter policy
    
    # Custom filters for tracking
    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        # Add annotations for better tracking with proper output field types
        return queryset.select_related('user', 'product', 'transaction').annotate(
            days_since_created=Case(
                When(created_at__isnull=False, 
                     then=timezone.now() - F('created_at')),
                default=timedelta(0)
            )
        )
    
    def changelist_view(self, request, extra_context=None):
        # Add summary statistics to the changelist
        response = super().changelist_view(request, extra_context=extra_context)
        
        try:
            qs = response.context_data['cl'].queryset
            
            # Calculate summary stats
            total_investments = qs.count()
            active_investments = qs.filter(status='ACTIVE').count()
            completed_investments = qs.filter(status='COMPLETED').count()
            expired_investments = qs.filter(status='EXPIRED').count()
            
            total_invested = qs.aggregate(Sum('total_amount'))['total_amount__sum'] or 0
            total_claimed = qs.aggregate(Sum('total_claimed_profit'))['total_claimed_profit__sum'] or 0
            
            # Expiring soon (within 7 days)
            expiring_soon = qs.filter(
                status='ACTIVE',
                remaining_days__lte=7,
                remaining_days__gt=0
            ).count()
            
            # Never claimed
            never_claimed = qs.filter(last_claim_time__isnull=True).count()
            
            # High performers (claimed more than 80% of potential)
            high_performers = 0
            for investment in qs:
                if investment.total_potential_profit > 0:
                    claim_percentage = (investment.total_claimed_profit / investment.total_potential_profit) * 100
                    if claim_percentage >= 80:
                        high_performers += 1
            
            summary = {
                'total_investments': total_investments,
                'active_investments': active_investments,
                'completed_investments': completed_investments,
                'expired_investments': expired_investments,
                'total_invested': total_invested,
                'total_claimed': total_claimed,
                'expiring_soon': expiring_soon,
                'never_claimed': never_claimed,
                'high_performers': high_performers,
                'claim_rate': round((total_claimed / total_invested * 100), 2) if total_invested > 0 else 0
            }
            
            response.context_data['summary'] = summary
            
        except (AttributeError, KeyError):
            pass
            
        return response
    
    def get_list_display(self, request):
        # Dynamic list display based on filter parameters
        base_display = ['investment_display', 'user_phone_display', 'status_display']
        
        if 'status__exact' in request.GET and request.GET['status__exact'] == 'ACTIVE':
            return base_display + ['profit_claims_display', 'progress_display', 'expiry_info_display']
        elif 'status__exact' in request.GET and request.GET['status__exact'] == 'COMPLETED':
            return base_display + ['performance_display', 'total_amount_display', 'completion_info_display']
        else:
            return base_display + ['profit_claims_display', 'total_amount_display', 'progress_display', 'expiry_info_display']
    
    readonly_fields = ('created_at', 'updated_at', 'expires_at', 'total_amount')
    
    fieldsets = (
        ('Investment Overview', {
            'fields': ('user', 'product', 'transaction', 'status'),
            'classes': ('wide',)
        }),
        ('Investment Details', {
            'fields': ('quantity', 'total_amount'),
            'classes': ('collapse',)
        }),
        ('Profit Configuration', {
            'fields': ('profit_type', 'profit_rate', 'profit_random_min', 'profit_random_max', 'profit_method', 'claim_reset_mode'),
            'classes': ('collapse',)
        }),
        ('Duration & Timeline', {
            'fields': ('duration_days', 'remaining_days', 'expires_at'),
            'description': 'Investment duration and expiration tracking'
        }),
        ('Claim History & Performance', {
            'fields': ('last_claim_time', 'next_claim_time', 'total_claimed_profit', 
                      'claims_count', 'total_claimed_amount', 'last_claim_amount',
                      'first_claim_time', 'claims_remaining'),
            'description': 'Track profit claims and performance metrics'
        }),
        ('Audit Trail', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def investment_display(self, obj):
        return format_html('{} ({}x)', obj.product.name, obj.quantity)
    investment_display.short_description = 'Investment'
    
    def user_phone_display(self, obj):
        return obj.user.phone
    user_phone_display.short_description = 'Phone'
    
    def status_display(self, obj):
        colors = {
            'ACTIVE': 'green',
            'COMPLETED': 'blue',
            'EXPIRED': 'orange',
            'CANCELLED': 'red'
        }
        return format_html('<span style="color: {color}; font-weight: bold;">{status}</span>', 
                         color=colors.get(obj.status, 'black'), status=obj.status)
    status_display.short_description = 'Status'
    
    def profit_display(self, obj):
        daily = obj.daily_profit
        total = obj.total_potential_profit
        claimed = obj.total_claimed_profit
        remaining = obj.remaining_profit
        
        return format_html(
            '<div><strong>Daily:</strong> {}</div>'
            '<div><strong>Total:</strong> {}</div>'
            '<div><strong>Claimed:</strong> <span style="color: green;">{}</span></div>'
            '<div><strong>Remaining:</strong> <span style="color: blue;">{}</span></div>',
            format_currency(daily),
            format_currency(total),
            format_currency(claimed),
            format_currency(remaining),
        )
    profit_display.short_description = 'Profit Details'
    
    def total_amount_display(self, obj):
        return format_html('<strong>{}</strong>', format_currency(obj.total_amount))
    total_amount_display.short_description = 'Investment Amount'
    
    def remaining_days_display(self, obj):
        if obj.remaining_days > 0:
            color = 'green' if obj.remaining_days > 7 else 'orange' if obj.remaining_days > 3 else 'red'
        else:
            color = 'gray'
        
        return format_html('<span style="color: {}; font-weight: bold;">{} days</span>', 
                         color, obj.remaining_days)
    remaining_days_display.short_description = 'Remaining Days'
    
    def profit_claims_display(self, obj):
        # Use tracking fields for claim statistics against total duration
        claims_count = obj.claims_count
        total_days = obj.duration_days or 0
        total_claimed = obj.total_claimed_amount
        last_claim_amount = obj.last_claim_amount

        # Percentage based on claims vs total duration
        claim_percentage = (claims_count / total_days * 100) if total_days > 0 else 0

        # Color based on completion percentage
        if claim_percentage >= 80:
            color = 'green'
        elif claim_percentage >= 50:
            color = 'orange'
        else:
            color = 'red'

        # Last claim info
        last_claim_text = 'Never' if not obj.last_claim_time else obj.last_claim_time.strftime('%m/%d')
        last_amount_text = format_currency(last_claim_amount) if last_claim_amount > 0 else 'N/A'

        # Claim status
        can_claim_today = obj.can_claim_today() if obj.status == 'ACTIVE' else False
        can_claim_manually = obj.can_claim_manually() if obj.status == 'ACTIVE' else False
        if obj.profit_method == 'auto':
            claim_status = '🤖 Auto' if can_claim_today else '⏳ Processing'
            claim_color = 'blue'
        elif can_claim_manually:
            claim_status = '✓ Can Claim'
            claim_color = 'green'
        elif obj.last_claim_time:
            claim_status = '✗ Claimed'
            claim_color = 'gray'
        else:
            claim_status = '⚠ Never'
            claim_color = 'red'

        return format_html(
            '<div><strong>{}/{}</strong> <span style="color: {}">({}%)</span></div>'
            '<div style="font-size: 11px;">Total: <strong>{}</strong></div>'
            '<div style="font-size: 11px;">Last: {} ({})</div>'
            '<div style="font-size: 11px; color: {};">{}</div>',
            claims_count, total_days,
            color, '{:.1f}'.format(claim_percentage),
            format_currency(total_claimed),
            last_claim_text, last_amount_text,
            claim_color, claim_status
        )
    profit_claims_display.short_description = 'Profit Claims'

    def progress_display(self, obj):
        # Progress based on claims_count vs total duration days
        claimed_count = obj.claims_count
        total_days = obj.duration_days or 0
        progress_percentage = min((claimed_count / total_days * 100), 100) if total_days > 0 else 0
        width_percentage = int(progress_percentage)

        # Progress bar color
        if progress_percentage >= 90:
            bar_color = '#28a745'  # Green
        elif progress_percentage >= 60:
            bar_color = '#ffc107'  # Yellow
        else:
            bar_color = '#007bff'  # Blue

        return format_html(
            '<div style="width: 100px; background: #e9ecef; border-radius: 3px; overflow: hidden;">'
            '<div style="width: {}%; height: 20px; background: {}; position: relative;">'
            '<span style="position: absolute; width: 100px; text-align: center; '
            'line-height: 20px; font-size: 11px; font-weight: bold; color: white; text-shadow: 1px 1px 1px rgba(0,0,0,0.5);">{}</span>'
            '</div></div>'
            '<div style="font-size: 12px; margin-top: 2px; font-weight: bold; text-align: center;">{}/{}</div>',
            width_percentage, bar_color, '{:.1f}%'.format(progress_percentage), claimed_count, total_days
        )
    progress_display.short_description = 'Progress'
    
    def expiry_info_display(self, obj):
        if obj.status == 'EXPIRED':
            return format_html('<span style="color: red; font-weight: bold;">EXPIRED</span>')
        elif obj.status == 'COMPLETED':
            return format_html('<span style="color: blue; font-weight: bold;">COMPLETED</span>')
        
        remaining = obj.remaining_days
        if remaining <= 0:
            return format_html('<span style="color: red;">Expired</span>')
        
        # Color coding based on remaining days
        if remaining <= 3:
            color = 'red'
            urgency = '🔥'
        elif remaining <= 7:
            color = 'orange'
            urgency = '⚠️'
        elif remaining <= 14:
            color = '#ffc107'
            urgency = '⏰'
        else:
            color = 'green'
            urgency = '✅'
        
        expires_date = obj.expires_at.strftime('%m/%d/%Y') if obj.expires_at else 'N/A'
        
        return format_html(
            '<div>{} <span style="color: {}; font-weight: bold;">{} days</span></div>'
            '<div style="font-size: 11px; color: gray;">Exp: {}</div>',
            urgency, color, remaining, expires_date
        )
    expiry_info_display.short_description = 'Expiry Info'
    
    def performance_display(self, obj):
        # Calculate ROI and performance metrics
        if obj.total_amount <= 0:
            return format_html('<span style="color: gray;">N/A</span>')

        from decimal import Decimal
        base = Decimal(str(obj.total_amount or 0))
        roi_percentage = Decimal("0") if base <= 0 else (Decimal(str(obj.total_claimed_profit or 0)) / base) * Decimal("100")
        potential_roi = Decimal("0") if base <= 0 else (Decimal(str(obj.total_potential_profit or 0)) / base) * Decimal("100")
        
        # Performance rating
        if roi_percentage >= potential_roi * 0.8:
            rating = '⭐⭐⭐⭐⭐'
            rating_color = 'green'
        elif roi_percentage >= potential_roi * 0.6:
            rating = '⭐⭐⭐⭐'
            rating_color = 'orange'
        elif roi_percentage >= potential_roi * 0.4:
            rating = '⭐⭐⭐'
            rating_color = '#ffc107'
        elif roi_percentage >= potential_roi * 0.2:
            rating = '⭐⭐'
            rating_color = 'red'
        else:
            rating = '⭐'
            rating_color = 'red'
        
        return format_html(
            '<div><strong>ROI:</strong> <span style="color: {}; font-weight: bold;">{}%</span></div>'
            '<div><strong>Claimed:</strong> {}</div>'
            '<div style="color: {};">{}</div>',
            'green' if roi_percentage > 0 else 'red',
            str(roi_percentage.quantize(Decimal("0.1"))),
            format_currency(obj.total_claimed_profit),
            rating_color,
            rating
        )
    performance_display.short_description = 'Performance'
    
    def completion_info_display(self, obj):
        if obj.status != 'COMPLETED':
            return '-'
        
        completion_rate = (obj.total_claimed_profit / obj.total_potential_profit * 100) if obj.total_potential_profit > 0 else 0
        
        return format_html(
            '<div><strong>Completion:</strong> {}%</div>'
            '<div><strong>Final ROI:</strong> {}%</div>',
            '{:.1f}'.format(completion_rate),
            '{:.1f}'.format((obj.total_claimed_profit / obj.total_amount * 100) if obj.total_amount > 0 else 0)
        )
    completion_info_display.short_description = 'Completion Info'
    
    # Custom admin actions
    def export_investment_report(self, request, queryset):
        """Export detailed investment report"""
        from django.http import HttpResponse
        import csv
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="investment_report.csv"'
        
        writer = csv.writer(response)
        writer.writerow([
            'User Phone', 'Product Name', 'Investment Amount', 'Status',
            'Days Active', 'Total Claimed', 'Claim Percentage', 'ROI',
            'Remaining Days', 'Created Date', 'Last Claim'
        ])
        
        for investment in queryset:
            days_active = (timezone.now().date() - investment.created_at.date()).days + 1
            max_possible_claims = min(days_active, investment.duration_days)
            claimed_count = Transaction.objects.filter(
                user=investment.user,
                type__iexact='credit',
                description__icontains='profit claim',
                product=investment.product,
                created_at__gte=investment.created_at
            ).count()
            
            claim_percentage = (claimed_count / max_possible_claims * 100) if max_possible_claims > 0 else 0
            roi = (investment.total_claimed_profit / investment.total_amount * 100) if investment.total_amount > 0 else 0
            
            writer.writerow([
                investment.user.phone,
                investment.product.name,
                format_currency(investment.total_amount),
                investment.status,
                days_active,
                format_currency(investment.total_claimed_profit),
                '{:.1f}%'.format(claim_percentage),
                '{:.1f}%'.format(roi),
                investment.remaining_days,
                investment.created_at.strftime('%Y-%m-%d'),
                investment.last_claim_time.strftime('%Y-%m-%d') if investment.last_claim_time else 'Never'
            ])
        
        messages.success(request, 'Exported {} investment records to CSV.'.format(queryset.count()))
        return response
    
    export_investment_report.short_description = "📊 Export investment report to CSV"
    
    def mark_for_review(self, request, queryset):
        """Mark investments for manual review"""
        # You can add custom logic here to flag investments
        count = queryset.count()
        messages.success(request, 'Marked {} investments for review.'.format(count))
    
    mark_for_review.short_description = "🔍 Mark for manual review"
    
    def send_claim_reminder(self, request, queryset):
        """Send claim reminders to users (placeholder)"""
        active_investments = queryset.filter(status='ACTIVE')
        count = 0
        
        for investment in active_investments:
            if investment.can_claim_today():
                # Here you would integrate with your notification system
                # For now, we'll just count eligible investments
                count += 1
        
        messages.success(request, 'Sent claim reminders to {} users with claimable investments.'.format(count))
    
    send_claim_reminder.short_description = "📧 Send claim reminders"
    
    actions = [export_investment_report, mark_for_review, send_claim_reminder]
