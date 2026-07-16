from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserChangeForm
from django.utils.html import format_html
from django.urls import path, reverse
from django.shortcuts import redirect
from django.contrib import messages
from django.shortcuts import render
from .models import User
from .views import AdminDownlineOverviewView
from django import forms
from decimal import Decimal
from .models import User, GeneralSetting, RankLevel, UserAddress, PhoneOTP, AdminDecodeTool
import base64
import json
from django.conf import settings
from config import format_currency


class UserAdminForm(UserChangeForm):
    withdraw_pin_raw = forms.CharField(
        required=False,
        label='Withdraw PIN (admin set/reset)',
        help_text='Isi 6 digit PIN baru untuk reset Withdraw PIN user. Kosongkan jika tidak mengubah.'
    )
    
    class Meta(UserChangeForm.Meta):
        model = User
        fields = '__all__'


@admin.register(PhoneOTP)
class PhoneOTPAdmin(admin.ModelAdmin):
    list_display = ('phone', 'otp_display', 'source_display', 'created_at', 'verified')
    search_fields = ('phone', 'verification_id')
    list_filter = ('verified', 'created_at')
    readonly_fields = ('created_at',)

    def otp_display(self, obj):
        if obj.otp_code:
            return obj.otp_code
        return obj.verification_id or '-'
    otp_display.short_description = 'OTP Code / Verification ID'

    def source_display(self, obj):
        if getattr(obj, 'provider', None):
            return obj.provider
        if obj.verification_id:
            return "VERIFYNOW"
        return "VERIFYWAY"
    source_display.short_description = 'Provider'


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin configuration for custom User model."""
    
    list_display = ('phone', 'email', 'full_name', 'telegram', 'balance_display', 'balance_deposit_display', 'balance_hold_display', 'balance_cashback_display',
                   'banned_status_display', 'rank', 'referral_code', 'referral_by_display', 
                   'account_status_display', 'last_login_ip', 'created_at')
    # Optimization: prefetch related fields to avoid N+1 queries
    list_select_related = ('referral_by',)
    # Removed list_filter for cleaner admin interface
    search_fields = ('phone',)
    ordering = ('-created_at',)
    
    fieldsets = (
        (None, {'fields': ('username', 'email', 'password')}),
        ('Personal Info', {'fields': ('full_name', 'phone', 'telegram', 'withdraw_pin_raw')}),
        ('Balance', {'fields': ('balance', 'balance_deposit', 'balance_hold', 'balance_cashback')}),
        ('Referral System', {'fields': ('referral_code', 'referral_by', 'rank', 'downline_overview_link')}),
        ('Account Status', {
            'fields': ('banned_status', 'is_account_non_expired', 'is_account_non_locked',
                      'is_credentials_non_expired', 'is_enabled'),
        }),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Important dates', {'fields': ('last_login', 'last_login_ip', 'date_joined', 'created_at', 'updated_at')}),
    )
    
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'full_name', 'phone', 'telegram', 'password1', 'password2'),
        }),
    )
    
    readonly_fields = ('updated_at', 'last_login', 'last_login_ip', 'referral_code', 'downline_overview_link')
    form = UserAdminForm
    
    def save_model(self, request, obj, form, change):
        pin_raw = form.cleaned_data.get('withdraw_pin_raw') if hasattr(form, 'cleaned_data') else None
        super().save_model(request, obj, form, change)
        if pin_raw:
            obj.set_withdraw_pin(pin_raw)
    
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('<id>/increase-balance/<str:field>/<str:amount>/',
                 self.admin_site.admin_view(self.increase_balance),
                 name='accounts_user_increase_balance'),
            path('<id>/decrease-balance/<str:field>/<str:amount>/',
                 self.admin_site.admin_view(self.decrease_balance),
                 name='accounts_user_decrease_balance'),
            path('<id>/modify-balance/<str:field>/',
                 self.admin_site.admin_view(self.modify_balance),
                 name='accounts_user_modify_balance'),
            path('<id>/toggle-banned/',
                 self.admin_site.admin_view(self.toggle_banned),
                 name='accounts_user_toggle_banned'),
            path('downline-overview/',
                 self.admin_site.admin_view(self.downline_overview),
                 name='accounts_user_downline_overview_admin'),
            path('decode-response/',
                 self.admin_site.admin_view(self.decode_response_tool),
                 name='accounts_user_decode_response'),
        ]
        return custom_urls + urls
    
    def balance_display(self, obj):
        url = reverse('admin:accounts_user_modify_balance', args=[obj.id, 'balance'])
        return format_html(
            '{} <a href="{}">[Edit]</a>',
            format_currency(obj.balance),
            url
        )
    balance_display.short_description = 'Balance'
    
    def balance_deposit_display(self, obj):
        url = reverse('admin:accounts_user_modify_balance', args=[obj.id, 'balance_deposit'])
        return format_html(
            '{} <a href="{}">[Edit]</a>',
            format_currency(obj.balance_deposit),
            url
        )
    balance_deposit_display.short_description = 'Balance Deposit'

    def balance_hold_display(self, obj):
        url = reverse('admin:accounts_user_modify_balance', args=[obj.id, 'balance_hold'])
        return format_html(
            '{} <a href="{}">[Edit]</a>',
            format_currency(getattr(obj, 'balance_hold', 0) or 0),
            url
        )
    balance_hold_display.short_description = 'Balance Hold'

    def balance_cashback_display(self, obj):
        url = reverse('admin:accounts_user_modify_balance', args=[obj.id, 'balance_cashback'])
        return format_html(
            '{} <a href="{}">[Edit]</a>',
            format_currency(getattr(obj, 'balance_cashback', 0) or 0),
            url
        )
    balance_cashback_display.short_description = 'Balance Cashback'
    
    def banned_status_display(self, obj):
        color = 'red' if obj.banned_status else 'green'
        status = 'Banned' if obj.banned_status else 'Active'
        toggle_url = reverse('admin:accounts_user_toggle_banned', args=[obj.id])
        return format_html(
            '<span style="color: {};">{}</span> '
            '<a href="{}">[Toggle]</a>',
            color,
            status,
            toggle_url
        )
    banned_status_display.short_description = 'Ban Status'

    def downline_overview_link(self, obj):
        base_url = reverse('admin:accounts_user_downline_overview_admin')
        url = f"{base_url}?phone={obj.phone}"
        return format_html('<a href="{}" class="button">Downline Overview</a>', url)
    downline_overview_link.short_description = 'Downline Overview'
    
    def account_status_display(self, obj):
        statuses = []
        if not obj.is_account_non_expired:
            statuses.append('Expired')
        if not obj.is_account_non_locked:
            statuses.append('Locked')
        if not obj.is_credentials_non_expired:
            statuses.append('Credentials Expired')
        if not obj.is_enabled:
            statuses.append('Disabled')
        
        if not statuses:
            return format_html('<span style="color: green;">Active</span>')
        return format_html('<span style="color: red;">{}</span>', ', '.join(statuses))
    account_status_display.short_description = 'Account Status'
    
    def increase_balance(self, request, id, field, amount):
        try:
            from products.models import Transaction
            import time
            
            user = User.objects.get(pk=id)
            current_value = getattr(user, field)
            decimal_amount = Decimal(amount)
            setattr(user, field, current_value + decimal_amount)
            user.save()
            
            # Create transaction record
            Transaction.objects.create(
                user=user,
                amount=decimal_amount,
                type='CREDIT',
                status='COMPLETED',
                trx_id=f'ADM-{field.upper()}-{user.id}-{int(time.time())}',
                wallet_type=field.upper(),
                description=f'Admin increased {field} by {amount}'
            )
            
            messages.success(request, f'Successfully increased {field} by {amount}')
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
        return redirect('admin:accounts_user_change', id)

    def decrease_balance(self, request, id, field, amount):
        try:
            from products.models import Transaction
            import time
            
            user = User.objects.get(pk=id)
            current_value = getattr(user, field)
            decimal_amount = Decimal(amount)
            
            if current_value >= decimal_amount:
                setattr(user, field, current_value - decimal_amount)
                user.save()
                
                # Create transaction record
                Transaction.objects.create(
                    user=user,
                    amount=decimal_amount,
                    type='DEBIT',
                    status='COMPLETED',
                    trx_id=f'ADM-{field.upper()}-{user.id}-{int(time.time())}',
                    wallet_type=field.upper(),
                    description=f'Admin decreased {field} by {amount}'
                )
                
                messages.success(request, f'Successfully decreased {field} by {amount}')
            else:
                messages.error(request, f'Insufficient {field}')
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
        return redirect('admin:accounts_user_change', id)

    def modify_balance(self, request, id, field):
        """Form sederhana tanpa popup untuk mengubah balance/balance_deposit."""
        from products.models import Transaction
        import time

        user = User.objects.get(pk=id)

        if request.method == 'POST':
            amount_str = request.POST.get('amount', '').strip()
            action = request.POST.get('action', '').strip()

            if not amount_str:
                messages.error(request, 'Amount is required')
                return redirect(reverse('admin:accounts_user_modify_balance', args=[id, field]))
            try:
                decimal_amount = Decimal(amount_str)
                if decimal_amount <= 0:
                    raise ValueError('Amount must be positive')
            except Exception:
                messages.error(request, 'Please enter a valid positive amount')
                return redirect(reverse('admin:accounts_user_modify_balance', args=[id, field]))

            current_value = getattr(user, field)
            if action == 'increase':
                setattr(user, field, current_value + decimal_amount)
                user.save()
                Transaction.objects.create(
                    user=user,
                    amount=decimal_amount,
                    type='CREDIT',
                    status='COMPLETED',
                    trx_id=f'ADM-{field.upper()}-{user.id}-{int(time.time())}',
                    wallet_type=field.upper(),
                    description=f'Admin increased {field} by {amount_str}'
                )
                messages.success(request, f'Successfully increased {field} by {amount_str}')
            elif action == 'decrease':
                if current_value >= decimal_amount:
                    setattr(user, field, current_value - decimal_amount)
                    user.save()
                    Transaction.objects.create(
                        user=user,
                        amount=decimal_amount,
                        type='DEBIT',
                        status='COMPLETED',
                        trx_id=f'ADM-{field.upper()}-{user.id}-{int(time.time())}',
                        wallet_type=field.upper(),
                        description=f'Admin decreased {field} by {amount_str}'
                    )
                    messages.success(request, f'Successfully decreased {field} by {amount_str}')
                else:
                    messages.error(request, f'Insufficient {field}')
            else:
                messages.error(request, 'Invalid action')

            return redirect('admin:accounts_user_change', id)

        # GET: render simple form
        return render(request, 'admin/modify_balance_form.html', {
            'title': 'Modify Balance',
            'user_obj': user,
            'field': field,
            'current_value': getattr(user, field),
        })
    
    def toggle_banned(self, request, id):
        try:
            user = User.objects.get(pk=id)
            user.banned_status = not user.banned_status
            user.save()
            status = 'banned' if user.banned_status else 'unbanned'
            messages.success(request, f'User successfully {status}')
        except Exception as e:
            messages.error(request, f'Error: {str(e)}')
        return redirect('admin:accounts_user_change', id)

    def downline_overview(self, request):
        """
        Admin GUI: form input phone dan tampilkan overview downline 3 level.
        URL: /admin/accounts/user/downline-overview/
        """
        phone = request.GET.get('phone') or ''
        context = {
            'title': 'Admin Downline Overview',
            'phone': phone,
            'result': None,
            'error': None,
        }

        if phone:
            target_user = User.objects.filter(phone=phone).first()
            if not target_user:
                context['error'] = 'User dengan phone tersebut tidak ditemukan'
            else:
                # Gunakan helper dari AdminDownlineOverviewView untuk konsistensi
                helper = AdminDownlineOverviewView()
                levels_data = helper._get_downlines_by_level(target_user, max_level=3)

                total_members = sum(level['member_count'] for level in levels_data.values())
                total_profit_commission = sum(level['total_profit_commission'] for level in levels_data.values())
                total_purchase_commission = sum(level['total_purchase_commission'] for level in levels_data.values())
                total_earned_commission = sum(level['total_earned_commission'] for level in levels_data.values())
                total_investments = sum(level['total_investments'] for level in levels_data.values())
                total_investment_amount = sum(level['total_investment_amount'] for level in levels_data.values())
                active_investments = sum(level['active_investments'] for level in levels_data.values())
                total_deposits = sum(level['total_deposits'] for level in levels_data.values())
                total_deposit_amount = sum(level['total_deposit_amount'] for level in levels_data.values())
                completed_deposits = sum(level['completed_deposits'] for level in levels_data.values())

                context['result'] = {
                    'target': target_user,
                    'total_members': total_members,
                    'total_profit_commission': total_profit_commission,
                    'total_purchase_commission': total_purchase_commission,
                    'total_earned_commission': total_earned_commission,
                    'total_investments': total_investments,
                    'total_investment_amount': total_investment_amount,
                    'active_investments': active_investments,
                    'total_deposits': total_deposits,
                    'total_deposit_amount': total_deposit_amount,
                    'completed_deposits': completed_deposits,
                    'levels': [levels_data[l] for l in sorted(levels_data.keys())],
                }

        return render(request, 'accounts/admin_downline_overview.html', context)
    
    def decode_response_tool(self, request):
        payload = ''
        decoded_text = None
        decoded_json = None
        error = None
        if request.method == 'POST':
            payload = request.POST.get('payload', '').strip()
            if not payload:
                error = 'Payload wajib diisi'
            else:
                text = payload
                try:
                    obj = json.loads(payload)
                    if isinstance(obj, dict) and isinstance(obj.get('data'), str):
                        text = obj['data']
                except ValueError:
                    text = payload
                encoded = text.strip()
                salt = getattr(settings, "RESPONSE_ENCODE_SALT", "")
                try:
                    rev = encoded[::-1]
                    if salt:
                        if len(rev) <= len(salt):
                            error = 'Data terlalu pendek untuk salt yang dikonfigurasi'
                        else:
                            uns = rev[:-len(salt)]
                    else:
                        uns = rev
                    if error is None:
                        raw_bytes = base64.b64decode(uns.encode("ascii"))
                        decoded_text = raw_bytes.decode("utf-8")
                        try:
                            obj = json.loads(decoded_text)
                            decoded_json = json.dumps(obj, indent=2, ensure_ascii=False)
                        except Exception:
                            decoded_json = None
                except Exception as exc:
                    error = f'Gagal decode: {exc}'
        context = {
            'title': 'Decode API Response',
            'payload': payload,
            'decoded_text': decoded_text,
            'decoded_json': decoded_json,
            'error': error,
        }
        return render(request, 'accounts/admin_decode_response.html', context)
        
    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "referral_by":
            field = super().formfield_for_foreignkey(db_field, request, **kwargs)
            field.queryset = User.objects.order_by('phone')
            field.label_from_instance = lambda obj: f"{obj.phone}"
            field.empty_label = "phone referral by"
            field.widget.attrs.update({'style': 'width: 300px; padding: 5px;'})

            obj_id = request.resolver_match.kwargs.get('object_id')
            if obj_id:
                try:
                    user = User.objects.get(pk=obj_id)
                    if user.referral_by:
                        field.initial = user.referral_by.pk
                except User.DoesNotExist:
                    pass
            return field
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def referral_by_display(self, obj):
        if obj.referral_by:
            return obj.referral_by.phone
        return '-'
    referral_by_display.short_description = 'Referred By'
    
    class Media:
        css = {
            'all': ('admin/css/custom_admin.css',)
        }


@admin.register(GeneralSetting)
class GeneralSettingAdmin(admin.ModelAdmin):
    list_display = (
        'referral_code_case', 'referral_code_length', 'exclude_similar_chars',
        'referral_code_pattern', 'referral_daily_invite_limit', 'auto_login_on_register', 'registration_bonus_enabled', 'registration_bonus_amount', 'registration_bonus_wallet', 'deposit_cashback_enabled', 'deposit_cashback_percent', 'currency_code', 'rank_logic', 'rank_count_levels_upto', 'frontend_url', 'updated_at'
    )
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('General', {
            'fields': ('frontend_url',)
        }),
        ('Currency', {
            'fields': ('currency_code', 'secondary_currency_code', 'secondary_rate_per_main'),
        }),
        ('Referral Code', {
            'fields': ('referral_code_case', 'referral_code_length', 'exclude_similar_chars', 'referral_code_pattern', 'referral_daily_invite_limit')
        }),
        ('Autentikasi', {
            'fields': ('auto_login_on_register', 'registration_bonus_enabled', 'registration_bonus_amount', 'registration_bonus_wallet', 'require_withdraw_pin_on_register', 'require_withdraw_pin_on_purchase')
        }),
        ('Deposit Cashback', {
            'fields': ('deposit_cashback_enabled', 'deposit_cashback_percent')
        }),
        ('WhatsApp OTP', {
            'fields': ('otp_enabled', 'otp_provider', 'verifynow_customer_id', 'verifynow_api_key', 'fazpass_merchant_key', 'fazpass_gateway_key', 'verifyway_api_key'),
            'description': 'Konfigurasi OTP via WhatsApp (VerifyNow atau Legacy VerifyWay). Jika VerifyNow credentials diisi, sistem akan memprioritaskannya.'
        }),
        ('WhatsApp Number Check (Backup)', {
            'fields': ('whatsapp_check_enabled', 'checknumber_api_key'),
            'description': 'Opsi backup/alternatif: cek nomor WA aktif via checknumber.ai'
        }),
        ('Kebijakan Rank', {
            'fields': (
                'rank_logic',
                'rank_use_missions',
                'rank_use_downlines_total',
                'rank_use_downlines_active',
                'rank_use_deposit_self_total',
                'rank_use_team_deposit_level_1_total',
                'rank_count_levels_upto'
            ),
            'description': (
                'Pilih basis rank melalui flag boolean. Atur cara evaluasinya lewat field Rank Logic: OR untuk salah satu syarat aktif, AND untuk semua syarat aktif. '
                'Level downline menentukan seberapa dalam perhitungan jumlah/aktif downline. '
                'Deposit tim level 1 hanya menghitung total deposit downline langsung saja.'
            )
        }),
        ('Kebijakan Member Aktif', {
            'fields': (
                'active_member_logic',
                'active_member_use_deposit_completed',
                'active_member_use_active_investment',
            ),
            'description': (
                'Tentukan definisi member aktif untuk kebutuhan rank/missions/dll. '
                'Jika investasi dipakai, hanya investasi ACTIVE dari produk dengan qualify_as_active_investment=ON yang dihitung.'
            )
        }),
        ('Waktu', {
            'fields': ('created_at', 'updated_at')
        }),
    )

    def has_add_permission(self, request):
        # Batasi hanya satu entri GeneralSetting
        if GeneralSetting.objects.exists():
            return False
        return super().has_add_permission(request)

@admin.register(RankLevel)
class RankLevelAdmin(admin.ModelAdmin):
    list_display = (
        'rank', 'title', 'description', 'missions_required_total', 'downlines_total_required',
        'downlines_active_required', 'deposit_self_total_required',
        'team_deposit_level_1_total_required', 'created_at', 'updated_at'
    )
    list_editable = (
        'title', 'description', 'missions_required_total', 'downlines_total_required',
        'downlines_active_required', 'deposit_self_total_required',
        'team_deposit_level_1_total_required'
    )
    ordering = ('rank',)
    search_fields = ('title', 'description')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Konfigurasi Rank', {
            'fields': (
                'rank', 'title', 'description', 'missions_required_total', 'downlines_total_required',
                'downlines_active_required', 'deposit_self_total_required',
                'team_deposit_level_1_total_required'
            ),
            'description': (
                'Isi syarat untuk tiap basis. Yang akan dipakai mengikuti General Settings -> Kebijakan Rank. '
                'Jika lebih dari satu basis diaktifkan, evaluasinya mengikuti General Settings -> Rank Logic (AND/OR).'
            )
        }),
        ('Waktu', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(UserAddress)
class UserAddressAdmin(admin.ModelAdmin):
    list_display = ('user', 'recipient_name', 'phone_number', 'is_primary', 'created_at')
    search_fields = ('user__phone', 'user__email', 'recipient_name', 'phone_number', 'address_details')
    list_filter = ('is_primary', 'created_at')
    raw_id_fields = ('user',)


@admin.register(AdminDecodeTool)
class AdminDecodeToolAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        url = reverse('admin:accounts_user_decode_response')
        return redirect(url)
