from datetime import datetime, time, timedelta
from django.db import transaction
from django.db.models import Sum, Count, Q
from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth import authenticate
from .models import User, RankLevel, UserAddress, GeneralSetting
from products.models import Transaction, Investment
from deposits.models import Deposit
from django.core.exceptions import ValidationError
from django.utils import timezone

class GeneralSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeneralSetting
        fields = '__all__'


class PublicGeneralSettingSerializer(serializers.ModelSerializer):
    """Serializer untuk setting publik yang aman dibuka ke frontend"""
    class Meta:
        model = GeneralSetting
        fields = ('frontend_url',)


class UserSerializer(serializers.ModelSerializer):
    """Serializer for User model - used for GET requests"""
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'full_name', 'phone', 'telegram', 'balance', 
                 'balance_deposit', 'balance_hold', 'balance_cashback', 'banned_status', 'referral_by', 'referral_code', 
                 'rank', 'is_account_non_expired', 'is_account_non_locked', 
                 'is_credentials_non_expired', 'is_enabled', 'created_at', 'updated_at')
        read_only_fields = ('balance', 'balance_deposit', 'balance_hold', 'balance_cashback', 'banned_status', 'referral_code', 
                          'rank', 'is_account_non_expired', 'is_account_non_locked', 
                          'is_credentials_non_expired', 'is_enabled', 'created_at', 'updated_at')

class RegisterSerializer(serializers.ModelSerializer):
    """Serializer for registering new users"""
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password2 = serializers.CharField(write_only=True, required=True)
    referral_code = serializers.CharField(required=False, allow_blank=True, write_only=True)
    otp = serializers.CharField(required=False, allow_blank=True, write_only=True, help_text='OTP code (required if OTP is enabled)')
    withdraw_pin = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = User
        fields = ('username', 'password', 'password2', 'email', 'full_name',
                 'phone', 'referral_code', 'otp', 'withdraw_pin')

    def validate_phone(self, value):
        # Pass-through: jangan ubah nilai phone sama sekali
        return value

    def validate(self, attrs):
        if attrs['password'] != attrs['password2']:
            raise serializers.ValidationError({"password": "Password fields didn't match."})
        
        # Validate phone number uniqueness
        phone = attrs.get('phone')
        if User.objects.filter(phone=phone).exists():
            raise serializers.ValidationError({"phone": "This phone number is already in use."})
        
        settings_obj = GeneralSetting.objects.order_by('-updated_at').first()
        withdraw_pin = (attrs.get('withdraw_pin') or '').strip()
        if settings_obj and settings_obj.require_withdraw_pin_on_register and not withdraw_pin:
            raise serializers.ValidationError({"withdraw_pin": "Withdraw PIN wajib diisi saat pendaftaran."})
        if withdraw_pin:
            if not (len(withdraw_pin) == 6 and withdraw_pin.isdigit()):
                raise serializers.ValidationError({"withdraw_pin": "Withdraw PIN harus 6 digit angka."})

        # Validate referral code if provided
        referral_code = attrs.pop('referral_code', None)
        if referral_code:
            try:
                referrer = User.objects.get(referral_code=referral_code)
                settings_obj = GeneralSetting.objects.order_by('-updated_at').first()
                daily_limit = int(getattr(settings_obj, 'referral_daily_invite_limit', 0) or 0) if settings_obj else 0
                if daily_limit > 0:
                    now_dt = timezone.now()
                    today = timezone.localdate(now_dt) if timezone.is_aware(now_dt) else now_dt.date()
                    if timezone.is_aware(now_dt):
                        start_dt = timezone.make_aware(datetime.combine(today, time.min), timezone.get_current_timezone())
                    else:
                        start_dt = datetime.combine(today, time.min)
                    end_dt = start_dt + timedelta(days=1)
                    invited_today = User.objects.filter(referral_by=referrer, created_at__gte=start_dt, created_at__lt=end_dt).count()
                    if invited_today >= daily_limit:
                        raise serializers.ValidationError({"referral_code": f"Batas undang harian tercapai ({daily_limit}/hari)."})
                attrs['referral_by'] = referrer
            except User.DoesNotExist:
                raise serializers.ValidationError({"referral_code": "Invalid referral code."})
        
        return attrs

    def create(self, validated_data):
        validated_data.setdefault('rank', 0)
        validated_data.pop('password2', None)
        validated_data.pop('otp', None)
        withdraw_pin = (validated_data.pop('withdraw_pin', None) or '').strip()
        referral_by = validated_data.get('referral_by')
        if referral_by:
            settings_obj = GeneralSetting.objects.order_by('-updated_at').first()
            daily_limit = int(getattr(settings_obj, 'referral_daily_invite_limit', 0) or 0) if settings_obj else 0
            if daily_limit > 0:
                now_dt = timezone.now()
                today = timezone.localdate(now_dt) if timezone.is_aware(now_dt) else now_dt.date()
                if timezone.is_aware(now_dt):
                    start_dt = timezone.make_aware(datetime.combine(today, time.min), timezone.get_current_timezone())
                else:
                    start_dt = datetime.combine(today, time.min)
                end_dt = start_dt + timedelta(days=1)
                with transaction.atomic():
                    referrer_locked = User.objects.select_for_update().get(pk=referral_by.pk)
                    invited_today = User.objects.filter(referral_by=referrer_locked, created_at__gte=start_dt, created_at__lt=end_dt).count()
                    if invited_today >= daily_limit:
                        raise serializers.ValidationError({"referral_code": f"Batas undang harian tercapai ({daily_limit}/hari)."})
                    validated_data['referral_by'] = referrer_locked
                    user = User.objects.create_user(**validated_data)
            else:
                user = User.objects.create_user(**validated_data)
        else:
            user = User.objects.create_user(**validated_data)
        if withdraw_pin:
            user.set_withdraw_pin(withdraw_pin)
        return user

class ChangePasswordByPhoneSerializer(serializers.Serializer):
    """Serializer to change password using phone and current password"""
    phone = serializers.CharField(required=True)
    old_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, required=True, validators=[validate_password])

    def validate(self, attrs):
        phone = attrs.get('phone')
        old_password = attrs.get('old_password')

        try:
            user = User.objects.get(phone=phone)
        except User.DoesNotExist:
            raise serializers.ValidationError({"phone": "User with this phone does not exist."})

        if not user.check_password(old_password):
            raise serializers.ValidationError({"old_password": "Current password is incorrect."})

        attrs['user'] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data['user']
        new_password = self.validated_data['new_password']
        user.set_password(new_password)
        user.save(update_fields=["password"])
        return user


class ResetPasswordWithOTPSerializer(serializers.Serializer):
    phone = serializers.CharField(required=True)
    password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True, required=True)
    otp = serializers.CharField(write_only=True, required=True)

    def validate(self, attrs):
        phone = attrs.get('phone')
        password = attrs.get('password')
        password_confirm = attrs.get('password_confirm')

        try:
            user = User.objects.get(phone=phone)
        except User.DoesNotExist:
            raise serializers.ValidationError({"phone": "User dengan nomor ini tidak ditemukan."})

        if password != password_confirm:
            raise serializers.ValidationError({"password_confirm": "Konfirmasi password tidak sama."})

        attrs['user'] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data['user']
        password = self.validated_data['password']
        user.set_password(password)
        user.save(update_fields=["password"])
        return user


class ChangePasswordWithOldPasswordAndOTPSerializer(serializers.Serializer):
    phone = serializers.CharField(required=True)
    old_password = serializers.CharField(write_only=True, required=True)
    new_password = serializers.CharField(write_only=True, required=True, validators=[validate_password])
    new_password_confirm = serializers.CharField(write_only=True, required=True)
    otp = serializers.CharField(write_only=True, required=True)

    def validate(self, attrs):
        phone = attrs.get('phone')
        old_password = attrs.get('old_password')
        new_password = attrs.get('new_password')
        new_password_confirm = attrs.get('new_password_confirm')

        try:
            user = User.objects.get(phone=phone)
        except User.DoesNotExist:
            raise serializers.ValidationError({"phone": "User dengan nomor ini tidak ditemukan."})

        if not user.check_password(old_password):
            raise serializers.ValidationError({"old_password": "Kata sandi lama salah."})

        if new_password != new_password_confirm:
            raise serializers.ValidationError({"new_password_confirm": "Konfirmasi kata sandi baru tidak sama."})

        attrs['user'] = user
        return attrs

    def save(self, **kwargs):
        user = self.validated_data['user']
        new_password = self.validated_data['new_password']
        user.set_password(new_password)
        user.save(update_fields=["password"])
        return user


class ChangeWithdrawPinWithOldPinAndOTPSerializer(serializers.Serializer):
    phone = serializers.CharField(required=True)
    old_withdraw_pin = serializers.CharField(write_only=True, required=True)
    new_withdraw_pin = serializers.CharField(write_only=True, required=True)
    new_withdraw_pin_confirm = serializers.CharField(write_only=True, required=True)
    otp = serializers.CharField(write_only=True, required=True)

    def validate(self, attrs):
        phone = attrs.get('phone')
        old_pin = (attrs.get('old_withdraw_pin') or '').strip()
        new_pin = (attrs.get('new_withdraw_pin') or '').strip()
        new_pin_confirm = (attrs.get('new_withdraw_pin_confirm') or '').strip()

        try:
            user = User.objects.get(phone=phone)
        except User.DoesNotExist:
            raise serializers.ValidationError({"phone": "User dengan nomor ini tidak ditemukan."})

        if not user.withdraw_pin:
            raise serializers.ValidationError({"old_withdraw_pin": "User belum punya withdraw PIN."})

        if not user.check_withdraw_pin(old_pin):
            raise serializers.ValidationError({"old_withdraw_pin": "Withdraw PIN lama salah."})

        if not (len(new_pin) == 6 and new_pin.isdigit()):
            raise serializers.ValidationError({"new_withdraw_pin": "Withdraw PIN baru harus 6 digit angka."})

        if new_pin != new_pin_confirm:
            raise serializers.ValidationError({"new_withdraw_pin_confirm": "Konfirmasi withdraw PIN baru tidak sama."})

        attrs['user'] = user
        attrs['clean_new_pin'] = new_pin
        return attrs

    def save(self, **kwargs):
        user = self.validated_data['user']
        new_pin = self.validated_data['clean_new_pin']
        user.set_withdraw_pin(new_pin)
        return user


class AccountInfoSerializer(serializers.ModelSerializer):
    """Serializer for user account information - returns safe user data"""
    referral_by_username = serializers.SerializerMethodField()
    referral_by_phone = serializers.SerializerMethodField()
    root_parent_username = serializers.SerializerMethodField()
    root_parent_phone = serializers.SerializerMethodField()
    ip_address = serializers.SerializerMethodField()
    active_investments_count = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'full_name', 'phone', 'telegram', 'balance', 
                 'balance_deposit', 'balance_hold', 'balance_cashback', 'referral_by_username', 'referral_by_phone', 
                 'root_parent_username', 'root_parent_phone',
                 'referral_code', 'rank', 'created_at', 'updated_at', 'ip_address', 'active_investments_count')
        read_only_fields = ('id', 'username', 'email', 'full_name', 'phone', 'telegram', 'balance', 
                           'balance_deposit', 'balance_hold', 'balance_cashback', 'referral_by_username', 'referral_by_phone', 
                           'root_parent_username', 'root_parent_phone',
                           'referral_code', 'rank', 'created_at', 'updated_at', 'active_investments_count')

    def get_active_investments_count(self, obj):
        return Investment.objects.filter(user=obj, status='ACTIVE').count()

    def get_ip_address(self, obj):
        request = self.context.get('request')
        if request:
            meta = request.META
            forwarded_client_ip = meta.get('HTTP_X_ORIGINAL_CLIENT_IP') or meta.get('HTTP_X_CLIENT_IP')
            if forwarded_client_ip and '{' not in forwarded_client_ip and '}' not in forwarded_client_ip:
                return forwarded_client_ip
            cf_ip = meta.get('HTTP_CF_CONNECTING_IP')
            if cf_ip and '{' not in cf_ip and '}' not in cf_ip:
                return cf_ip
            x_forwarded_for = meta.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip = x_forwarded_for.split(',')[0].strip()
                if ip and '{' not in ip and '}' not in ip:
                    return ip
            x_real_ip = meta.get('HTTP_X_REAL_IP')
            if x_real_ip and '{' not in x_real_ip and '}' not in x_real_ip:
                return x_real_ip
            ip = meta.get('REMOTE_ADDR')
            if ip and '{' not in ip and '}' not in ip:
                return ip
            return None
        return None

    def get_referral_by_username(self, obj):
        """Get the username of the direct referrer"""
        if obj.referral_by:
            return obj.referral_by.username
        return None
    
    def get_referral_by_phone(self, obj):
        """Get the phone of the direct referrer"""
        if obj.referral_by:
            return obj.referral_by.phone
        return None
    
    def get_root_parent_username(self, obj):
        """Get the username of the root parent (top-level referrer)"""
        current_user = obj
        while current_user.referral_by:
            current_user = current_user.referral_by
        
        # If current_user is not the same as obj, then we found a root parent
        if current_user != obj:
            return current_user.username
        return None

    def get_root_parent_phone(self, obj):
        """Get the phone of the root parent (top-level referrer)"""
        current_user = obj
        while current_user.referral_by:
            current_user = current_user.referral_by

        # If current_user is not the same as obj, then we found a root parent
        if current_user != obj:
            return current_user.phone
        return None

class AccountStatsSerializer(serializers.ModelSerializer):
    """Serializer for summarizing user account statistics and transactions"""
    total_profit_commission = serializers.SerializerMethodField()
    total_purchase_commission = serializers.SerializerMethodField()
    total_earned_commission = serializers.SerializerMethodField()
    commission_count = serializers.SerializerMethodField()
    total_investments = serializers.SerializerMethodField()
    total_investment_amount = serializers.SerializerMethodField()
    active_investments = serializers.SerializerMethodField()
    total_deposits = serializers.SerializerMethodField()
    total_deposit_amount = serializers.SerializerMethodField()
    completed_deposits = serializers.SerializerMethodField()
    is_active = serializers.SerializerMethodField()
    transaction_history = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ('id', 'username', 'phone', 'full_name', 'created_at', 
                 'total_profit_commission', 'total_purchase_commission', 'total_earned_commission', 'commission_count',
                 'total_investments', 'total_investment_amount', 'active_investments',
                 'total_deposits', 'total_deposit_amount', 'completed_deposits',
                 'is_active', 'transaction_history')

    def get_total_profit_commission(self, obj):
        # Sum of completed TRANSACTION type 'PROFIT' linked to user
        if hasattr(obj, 'total_profit_commission_val'):
            return obj.total_profit_commission_val
        return Transaction.objects.filter(user=obj, type='PROFIT', status='COMPLETED').aggregate(total=Sum('amount'))['total'] or 0

    def get_total_purchase_commission(self, obj):
        # Sum of completed TRANSACTION type 'COMMISSIONS' linked to user
        if hasattr(obj, 'total_purchase_commission_val'):
            return obj.total_purchase_commission_val
        return Transaction.objects.filter(user=obj, type='COMMISSIONS', status='COMPLETED').aggregate(total=Sum('amount'))['total'] or 0

    def get_total_earned_commission(self, obj):
        return self.get_total_profit_commission(obj) + self.get_total_purchase_commission(obj)

    def get_commission_count(self, obj):
        if hasattr(obj, 'commission_count_val'):
            return obj.commission_count_val
        return Transaction.objects.filter(user=obj, type__in=['COMMISSIONS', 'PROFIT'], status='COMPLETED').count()

    def get_total_investments(self, obj):
        if hasattr(obj, 'total_investments_val'):
            return obj.total_investments_val
        return Investment.objects.filter(user=obj).count()

    def get_total_investment_amount(self, obj):
        if hasattr(obj, 'total_investment_amount_val'):
            return obj.total_investment_amount_val
        return Investment.objects.filter(user=obj).aggregate(total=Sum('amount'))['total'] or 0

    def get_active_investments(self, obj):
        if hasattr(obj, 'active_investments_val'):
            return obj.active_investments_val
        return Investment.objects.filter(user=obj, status='ACTIVE').count()

    def get_total_deposits(self, obj):
        if hasattr(obj, 'total_deposits_val'):
            return obj.total_deposits_val
        return Deposit.objects.filter(user=obj).count()

    def get_total_deposit_amount(self, obj):
        if hasattr(obj, 'total_deposit_amount_val'):
            return obj.total_deposit_amount_val
        return Deposit.objects.filter(user=obj, status='COMPLETED').aggregate(total=Sum('amount'))['total'] or 0

    def get_completed_deposits(self, obj):
        if hasattr(obj, 'completed_deposits_val'):
            return obj.completed_deposits_val
        return Deposit.objects.filter(user=obj, status='COMPLETED').count()

    def get_is_active(self, obj):
        return obj.is_enabled and obj.is_account_non_expired and obj.is_account_non_locked and obj.is_credentials_non_expired

    def get_transaction_history(self, obj):
        qs = Transaction.objects.filter(user=obj).order_by('-created_at')[:10]
        return [
            {
                'trx_id': t.trx_id,
                'type': t.type,
                'amount': str(t.amount),
                'currency_code': getattr(t, 'currency_code', '') or '',
                'original_amount': str(getattr(t, 'original_amount', '') or ''),
                'original_currency_code': getattr(t, 'original_currency_code', '') or '',
                'status': t.status,
                'created_at': t.created_at,
            }
            for t in qs
        ]

class ProfileUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating user profile - full_name, username, and telegram"""
    
    class Meta:
        model = User
        fields = ('full_name', 'username', 'telegram')
    
    def validate_username(self, value):
        """Validate that username is unique (excluding current user)"""
        user = self.instance
        if User.objects.filter(username=value).exclude(id=user.id).exists():
            raise serializers.ValidationError("Username sudah digunakan oleh user lain.")
        return value

class WithdrawPinSerializer(serializers.Serializer):
    pin = serializers.CharField(write_only=True)
    current_pin = serializers.CharField(write_only=True, required=False, allow_blank=True)
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = self.context['request'].user
        new_pin = (attrs.get('pin') or '').strip()
        current_pin = (attrs.get('current_pin') or '').strip()
        password = (attrs.get('password') or '').strip()

        # 1. Verify login password for security (Always required)
        if not user.check_password(password):
            raise serializers.ValidationError({'password': 'Kata sandi salah.'})

        # 2. Require exactly 6 digits for new PIN
        if not (len(new_pin) == 6 and new_pin.isdigit()):
            raise serializers.ValidationError({'pin': 'PIN harus 6 digit angka.'})

        # 3. Validate Current PIN (Required only if user has a PIN set)
        if user.withdraw_pin:
            if not current_pin:
                raise serializers.ValidationError({'current_pin': 'PIN saat ini wajib diisi karena Anda sudah mengatur PIN sebelumnya.'})
            
            if not (len(current_pin) == 6 and current_pin.isdigit()):
                raise serializers.ValidationError({'current_pin': 'PIN saat ini harus 6 digit angka.'})
            
            if not user.check_withdraw_pin(current_pin):
                raise serializers.ValidationError({'current_pin': 'PIN saat ini salah.'})
        
        # If user hasn't set a PIN, current_pin is ignored (can be empty)

        attrs['user'] = user
        attrs['new_pin'] = new_pin
        return attrs

    def save(self, **kwargs):
        user = self.validated_data['user']
        new_pin = self.validated_data['new_pin']
        user.set_withdraw_pin(new_pin)
        return user


class AdminWithdrawPinSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(required=False)
    phone = serializers.CharField(required=False, allow_blank=True)
    new_pin = serializers.CharField(write_only=True)
    
    def validate(self, attrs):
        user_id = attrs.get('user_id')
        phone = (attrs.get('phone') or '').strip()
        new_pin = (attrs.get('new_pin') or '').strip()
        
        if not user_id and not phone:
            raise serializers.ValidationError({'detail': 'Harus mengisi user_id atau phone.'})
        
        target = None
        if user_id:
            target = User.objects.filter(id=user_id).first()
        elif phone:
            target = User.objects.filter(phone=phone).first()
        
        if not target:
            raise serializers.ValidationError({'detail': 'User tidak ditemukan.'})
        
        if not (len(new_pin) == 6 and new_pin.isdigit()):
            raise serializers.ValidationError({'new_pin': 'PIN harus 6 digit angka.'})
        
        attrs['target_user'] = target
        attrs['clean_pin'] = new_pin
        return attrs
    
    def save(self, **kwargs):
        user = self.validated_data['target_user']
        pin = self.validated_data['clean_pin']
        user.set_withdraw_pin(pin)
        return user

class DownlineStatsLevelSerializer(serializers.Serializer):
    level = serializers.IntegerField()
    members_total = serializers.IntegerField()
    members_active = serializers.IntegerField()
    members_inactive = serializers.IntegerField()
    deposits_total_count = serializers.IntegerField()
    deposits_total_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    withdrawals_completed_count = serializers.IntegerField()
    withdrawals_completed_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    profit_commission_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    purchase_commission_amount = serializers.DecimalField(max_digits=15, decimal_places=2)

class DownlineStatsResponseSerializer(serializers.Serializer):
    levels = DownlineStatsLevelSerializer(many=True)


class RankLevelSerializer(serializers.ModelSerializer):
    is_current_rank = serializers.SerializerMethodField()
    is_unlocked = serializers.SerializerMethodField()
    user_progress_val = serializers.SerializerMethodField()
    user_progress_missions = serializers.SerializerMethodField()
    user_progress_downlines_total = serializers.SerializerMethodField()
    user_progress_downlines_active = serializers.SerializerMethodField()
    user_progress_deposit_self_total = serializers.SerializerMethodField()
    user_progress_team_deposit_level_1_total = serializers.SerializerMethodField()

    class Meta:
        model = RankLevel
        fields = (
            'rank',
            'title',
            'missions_required_total',
            'downlines_total_required',
            'downlines_active_required',
            'deposit_self_total_required',
            'team_deposit_level_1_total_required',
            'is_current_rank',
            'is_unlocked',
            'user_progress_val',
            'user_progress_missions',
            'user_progress_downlines_total',
            'user_progress_downlines_active',
            'user_progress_deposit_self_total',
            'user_progress_team_deposit_level_1_total',
        )

    def get_is_current_rank(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated and request.user.rank is not None:
            return obj.rank == request.user.rank
        return False

    def get_is_unlocked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated and request.user.rank is not None:
            return obj.rank <= request.user.rank
        return False

    def get_user_progress_val(self, obj):
        up = self.context.get('user_progress')
        if isinstance(up, dict):
            return up.get('max', 0)
        return up or 0

    def get_user_progress_missions(self, obj):
        up = self.context.get('user_progress')
        if isinstance(up, dict):
            return up.get('missions', 0)
        return None

    def get_user_progress_downlines_total(self, obj):
        up = self.context.get('user_progress')
        if isinstance(up, dict):
            return up.get('downlines_total', 0)
        return None

    def get_user_progress_downlines_active(self, obj):
        up = self.context.get('user_progress')
        if isinstance(up, dict):
            return up.get('downlines_active', 0)
        return None

    def get_user_progress_deposit_self_total(self, obj):
        up = self.context.get('user_progress')
        if isinstance(up, dict):
            return up.get('deposit_self_total', 0)
        return None

    def get_user_progress_team_deposit_level_1_total(self, obj):
        up = self.context.get('user_progress')
        if isinstance(up, dict):
            return up.get('team_deposit_level_1_total', 0)
        return None


class RankStatusResponseSerializer(serializers.Serializer):
    current_rank = serializers.IntegerField(allow_null=True)
    current_title = serializers.CharField(allow_null=True)
    completed_missions = serializers.IntegerField()
    next_rank = serializers.IntegerField(allow_null=True)
    next_title = serializers.CharField(allow_null=True)
    next_required_missions = serializers.IntegerField(allow_null=True)
    downlines_total = serializers.IntegerField(required=False)
    downlines_active = serializers.IntegerField(required=False)
    deposit_self_total = serializers.DecimalField(max_digits=15, decimal_places=2, required=False)
    team_deposit_level_1_total = serializers.DecimalField(max_digits=15, decimal_places=2, required=False)
    next_required_downlines_total = serializers.IntegerField(allow_null=True, required=False)
    next_required_downlines_active = serializers.IntegerField(allow_null=True, required=False)
    next_required_deposit_self_total = serializers.DecimalField(max_digits=15, decimal_places=2, allow_null=True, required=False)
    next_required_team_deposit_level_1_total = serializers.DecimalField(max_digits=15, decimal_places=2, allow_null=True, required=False)


class UserAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserAddress
        fields = ['id', 'recipient_name', 'phone_number', 'address_details', 'house_number', 'is_primary', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']
    
    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)


class TransactionDetailSerializer(serializers.ModelSerializer):
    """Serializer for detailed transaction information"""
    product_name = serializers.CharField(source='product.name', read_only=True)
    upline_phone = serializers.CharField(source='upline_user.phone', read_only=True)
    
    class Meta:
        model = Transaction
        fields = (
            'trx_id', 'type', 'amount', 'currency_code', 'original_amount', 'original_currency_code', 'conversion_rate', 'description', 'status', 'wallet_type',
            'product_name', 'upline_phone', 'investment_quantity', 'commission_level', 'created_at'
        )

class DownlineMemberSerializer(serializers.Serializer):
    """Serializer for downline member details and aggregates"""
    username = serializers.CharField()
    phone = serializers.CharField()
    referral_code = serializers.CharField()
    rank = serializers.IntegerField(allow_null=True)
    registration_date = serializers.DateTimeField(source='created_at', read_only=True)
    
    # Commission data
    total_profit_commission = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_purchase_commission = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_earned_commission = serializers.DecimalField(max_digits=15, decimal_places=2)
    commission_count = serializers.IntegerField()
    
    # Investment/Product data
    total_investments = serializers.IntegerField()
    total_investment_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    active_investments = serializers.IntegerField()
    
    # Deposit data
    total_deposits = serializers.IntegerField()
    total_deposit_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    completed_deposits = serializers.IntegerField()
    
    # Active status
    is_active = serializers.BooleanField()
    
    # Transaction history
    transaction_history = TransactionDetailSerializer(many=True, read_only=True)

class DownlineLevelSerializer(serializers.Serializer):
    """Serializer for downline level summary with investment and deposit totals"""
    level = serializers.IntegerField()
    member_count = serializers.IntegerField()
    active_member_count = serializers.IntegerField()
    total_profit_commission = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_purchase_commission = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_earned_commission = serializers.DecimalField(max_digits=15, decimal_places=2)
    
    # Investment totals for this level
    total_investments = serializers.IntegerField()
    total_investment_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    active_investments = serializers.IntegerField()
    
    # Deposit totals for this level
    total_deposits = serializers.IntegerField()
    total_deposit_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    completed_deposits = serializers.IntegerField()
    
    members = DownlineMemberSerializer(many=True)
    members_pagination = serializers.DictField(required=False)


class DownlineOverviewSerializer(serializers.Serializer):
    """Serializer for complete downline overview with investment and deposit data"""
    total_members = serializers.IntegerField()
    total_profit_commission = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_purchase_commission = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_earned_commission = serializers.DecimalField(max_digits=15, decimal_places=2)
    
    # Overall investment totals
    total_investments = serializers.IntegerField()
    total_investment_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    active_investments = serializers.IntegerField()
    
    # Overall deposit totals
    total_deposits = serializers.IntegerField()
    total_deposit_amount = serializers.DecimalField(max_digits=15, decimal_places=2)
    completed_deposits = serializers.IntegerField()
    
    levels = DownlineLevelSerializer(many=True)


class ProfileUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating user profile - full_name, username, and telegram"""
    
    class Meta:
        model = User
        fields = ('full_name', 'username', 'telegram')
    
    def validate_username(self, value):
        """Validate that username is unique (excluding current user)"""
        user = self.instance
        if User.objects.filter(username=value).exclude(id=user.id).exists():
            raise serializers.ValidationError("Username sudah digunakan oleh user lain.")
        return value
