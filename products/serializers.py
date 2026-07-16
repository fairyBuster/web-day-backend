from rest_framework import serializers
from .models import Product, Transaction, Investment, ProfitHolidaySettings
from vouchers.models import Voucher
from vouchers.serializers import VoucherSerializer
from accounts.models import GeneralSetting
from django.core.files.storage import default_storage
from django.conf import settings
from django.utils import timezone
from decimal import Decimal

class ProductListSerializer(serializers.ModelSerializer):
    """
    Serializer for product list view - shows detailed information
    """
    image = serializers.SerializerMethodField()
    purchase_commission_rates = serializers.SerializerMethodField()
    profit_commission_rates = serializers.SerializerMethodField()
    min_required_rank = serializers.IntegerField(read_only=True)
    require_min_rank_enabled = serializers.BooleanField(read_only=True)
    
    class Meta:
        model = Product
        fields = (
            'id', 'name', 'description', 'price', 'image', 'status',
            'purchase_limit', 'stock', 'stock_enabled', 'profit_rate', 
            'profit_type', 'profit_random_min', 'profit_random_max', 'duration', 'specifications', 'created_at', 'golongan',
            'purchase_commission_rates', 'profit_commission_rates',
            'require_min_rank_enabled', 'min_required_rank'
        )
        read_only_fields = fields

    def get_image(self, obj):
        """Return full URL for image; fallback to default if missing"""
        request = self.context.get('request')
        try:
            img = getattr(obj, 'image', None)
            if img:
                name = getattr(img, 'name', None)
                exists = bool(name) and default_storage.exists(name)
                url = img.url if exists else settings.MEDIA_URL + 'products/default.png'
            else:
                url = settings.MEDIA_URL + 'products/default.png'
        except Exception:
            url = settings.MEDIA_URL + 'products/default.png'
        # Return relative URL instead of absolute URI to hide backend domain
        # if request:
        #     return request.build_absolute_uri(url)
        return url

    def get_purchase_commission_rates(self, obj):
        """Return purchase commission rates for levels 1-5 as percentages"""
        return [
            float(getattr(obj, f'purchase_rebate_level_{i}', 0))
            for i in range(1, 6)
        ]

    def get_profit_commission_rates(self, obj):
        """Return profit commission rates for levels 1-5 as percentages"""
        return [
            float(getattr(obj, f'profit_rebate_level_{i}', 0))
            for i in range(1, 6)
        ]

class ProductDetailSerializer(serializers.ModelSerializer):
    """
    Serializer for product detail view - shows all information
    """
    
    class Meta:
        model = Product
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')


class TransactionSerializer(serializers.ModelSerializer):
    user_phone = serializers.CharField(source='user.phone', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    upline_phone = serializers.CharField(source='upline_user.phone', read_only=True)
    transaction_id = serializers.SerializerMethodField()
    bank_account_name = serializers.SerializerMethodField()
    bank_account_number = serializers.SerializerMethodField()
    bank_name = serializers.SerializerMethodField()
    withdrawal_service_name = serializers.SerializerMethodField()
    withdrawal_service_duration_hours = serializers.SerializerMethodField()
    withdrawal_service_fee_percent = serializers.SerializerMethodField()
    withdrawal_service_fee_fixed = serializers.SerializerMethodField()
    voucher = serializers.SerializerMethodField()
    
    class Meta:
        model = Transaction
        fields = '__all__'
        read_only_fields = (
            'created_at',
            'trx_id',
            'user_phone',
            'product_name',
            'upline_phone',
            'currency_code',
            'original_amount',
            'original_currency_code',
            'conversion_rate',
            'bank_account_name',
            'bank_account_number',
            'bank_name',
            'withdrawal_service_name',
            'withdrawal_service_duration_hours',
            'withdrawal_service_fee_percent',
            'withdrawal_service_fee_fixed',
        )

    def get_transaction_id(self, obj):
        try:
            if obj.type == 'INTEREST':
                if obj.related_transaction:
                    return obj.related_transaction.trx_id
                if obj.product and obj.user:
                    from .models import Transaction
                    qs = Transaction.objects.filter(
                        user=obj.user,
                        product=obj.product,
                        type='INVESTMENTS',
                        status='COMPLETED',
                        created_at__lte=obj.created_at
                    ).order_by('-created_at')
                    purchase = qs.first() or Transaction.objects.filter(
                        user=obj.user, product=obj.product, type='INVESTMENTS'
                    ).order_by('-created_at').first()
                    if purchase:
                        return purchase.trx_id
        except Exception:
            return None
        return None

    def validate(self, data):
        # Validate amount is positive
        if data.get('amount', 0) <= 0:
            raise serializers.ValidationError({
                'amount': 'Nominal harus lebih dari 0'
            })
        
        # Validate investment quantity if product is provided
        if data.get('product') and data.get('investment_quantity'):
            if data['investment_quantity'] > data['product'].purchase_limit:
                raise serializers.ValidationError({
                    'investment_quantity': f'Tidak boleh membeli lebih dari {data["product"].purchase_limit} unit'
                })
            
            if data['product'].stock_enabled and data['product'].stock < data['investment_quantity']:
                raise serializers.ValidationError({
                    'investment_quantity': 'Stok tidak mencukupi'
                })
        
        return data

    def get_bank_account_name(self, obj):
        try:
            wd_manager = getattr(obj, 'related_withdrawal', None)
            wd = None
            if wd_manager:
                # Handle reverse ForeignKey (manager)
                if hasattr(wd_manager, 'all'):
                    # Use .all() to leverage prefetch_related cache if present
                    wds = wd_manager.all()
                    if wds:
                        wd = wds[0]
                else:
                    wd = wd_manager
                
            if wd and hasattr(wd, 'bank_account') and wd.bank_account:
                return wd.bank_account.account_name
        except Exception:
            pass
        return None

    def get_bank_account_number(self, obj):
        try:
            wd = self._get_withdrawal(obj)
            if wd and hasattr(wd, 'bank_account') and wd.bank_account:
                return wd.bank_account.account_number
        except Exception:
            pass
        return None

    def get_bank_name(self, obj):
        try:
            wd_manager = getattr(obj, 'related_withdrawal', None)
            wd = None
            if wd_manager:
                # Handle reverse ForeignKey (manager)
                if hasattr(wd_manager, 'all'):
                    wds = wd_manager.all()
                    if wds:
                        wd = wds[0]
                else:
                    wd = wd_manager

            if wd and hasattr(wd, 'bank_account') and wd.bank_account and wd.bank_account.bank:
                return wd.bank_account.bank.name
        except Exception:
            pass
        return None

    def _get_withdrawal(self, obj):
        wd_manager = getattr(obj, 'related_withdrawal', None)
        wd = None
        if wd_manager:
            if hasattr(wd_manager, 'all'):
                wds = wd_manager.all()
                if wds:
                    wd = wds[0]
            else:
                wd = wd_manager
        return wd

    def get_withdrawal_service_name(self, obj):
        try:
            wd = self._get_withdrawal(obj)
            service = getattr(wd, 'withdrawal_service', None) if wd else None
            if service:
                return service.name
        except Exception:
            pass
        return None

    def get_withdrawal_service_duration_hours(self, obj):
        try:
            wd = self._get_withdrawal(obj)
            service = getattr(wd, 'withdrawal_service', None) if wd else None
            if service:
                return service.duration_hours
        except Exception:
            pass
        return None

    def get_withdrawal_service_fee_percent(self, obj):
        try:
            wd = self._get_withdrawal(obj)
            service = getattr(wd, 'withdrawal_service', None) if wd else None
            if service:
                return str(service.fee_percent)
        except Exception:
            pass
        return None

    def get_withdrawal_service_fee_fixed(self, obj):
        try:
            wd = self._get_withdrawal(obj)
            service = getattr(wd, 'withdrawal_service', None) if wd else None
            if service:
                return str(service.fee_fixed)
        except Exception:
            pass
        return None

    def get_voucher(self, obj):
        try:
            if obj.voucher:
                return VoucherSerializer(obj.voucher, context=self.context).data
        except Exception:
            pass
        return None


class InvestmentSerializer(serializers.ModelSerializer):
    user_phone = serializers.CharField(source='user.phone', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_price = serializers.DecimalField(source='product.price', max_digits=15, decimal_places=2, read_only=True)
    product_golongan = serializers.CharField(source='product.golongan', read_only=True, allow_null=True)
    product_specification = serializers.CharField(source='product.specifications', read_only=True, allow_blank=True)
    product_description = serializers.CharField(source='product.description', read_only=True, allow_blank=True)
    transaction_id = serializers.CharField(source='transaction.trx_id', read_only=True)
    daily_profit = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    total_potential_profit = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    remaining_profit = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    can_claim_today = serializers.SerializerMethodField()
    can_claim_manually = serializers.SerializerMethodField()
    can_claim_principal = serializers.SerializerMethodField()
    principal_claim_locked_reason = serializers.SerializerMethodField()
    next_claim_time_calculated = serializers.SerializerMethodField()
    product_image = serializers.SerializerMethodField()
    profit_holiday_active = serializers.SerializerMethodField()
    profit_holiday_extend_duration_on_holidays = serializers.SerializerMethodField()
    profit_holiday_weekdays_disabled = serializers.SerializerMethodField()
    profit_holiday_disabled_dates = serializers.SerializerMethodField()
    profit_holiday_is_blocked_today = serializers.SerializerMethodField()

    def _get_profit_holiday_settings(self):
        if hasattr(self, "_profit_holiday_settings_cache"):
            return self._profit_holiday_settings_cache
        self._profit_holiday_settings_cache = ProfitHolidaySettings.get_settings()
        return self._profit_holiday_settings_cache

    def get_next_claim_time_calculated(self, obj):
        """Get next claim time even for new investments"""
        return obj.get_next_claim_time()

    def get_can_claim_today(self, obj):
        try:
            obj.update_remaining_days()
        except Exception:
            pass
        try:
            return bool(obj.can_claim_today())
        except Exception:
            return False

    def get_can_claim_manually(self, obj):
        try:
            obj.update_remaining_days()
        except Exception:
            pass
        try:
            return bool(obj.can_claim_manually())
        except Exception:
            return False

    def get_can_claim_principal(self, obj):
        try:
            obj.update_remaining_days()
        except Exception:
            pass
        try:
            return bool(obj.can_return_principal())
        except Exception:
            return False

    def get_principal_claim_locked_reason(self, obj):
        try:
            obj.update_remaining_days()
        except Exception:
            pass
        try:
            return obj.get_principal_return_block_reason()
        except Exception:
            return 'Status pengembalian modal tidak dapat ditentukan'

    def get_profit_holiday_active(self, obj):
        s = self._get_profit_holiday_settings()
        return bool(s.is_active) if s else False

    def get_profit_holiday_extend_duration_on_holidays(self, obj):
        s = self._get_profit_holiday_settings()
        return bool(getattr(s, "extend_duration_on_holidays", False)) if s else False

    def get_profit_holiday_weekdays_disabled(self, obj):
        s = self._get_profit_holiday_settings()
        if not s or not s.is_active:
            return []
        disabled = []
        if getattr(s, "disable_monday", False):
            disabled.append("monday")
        if getattr(s, "disable_tuesday", False):
            disabled.append("tuesday")
        if getattr(s, "disable_wednesday", False):
            disabled.append("wednesday")
        if getattr(s, "disable_thursday", False):
            disabled.append("thursday")
        if getattr(s, "disable_friday", False):
            disabled.append("friday")
        if getattr(s, "disable_saturday", False):
            disabled.append("saturday")
        if getattr(s, "disable_sunday", False):
            disabled.append("sunday")
        return disabled

    def get_profit_holiday_disabled_dates(self, obj):
        s = self._get_profit_holiday_settings()
        if not s or not s.is_active:
            return []
        try:
            return list(s.disabled_dates or [])
        except Exception:
            return []

    def get_profit_holiday_is_blocked_today(self, obj):
        s = self._get_profit_holiday_settings()
        if not s or not s.is_active:
            return False
        now_dt = timezone.now()
        today = timezone.localdate(now_dt) if timezone.is_aware(now_dt) else now_dt.date()
        return ProfitHolidaySettings.is_profit_blocked_today(today)
    
    def get_product_image(self, obj):
        product = obj.product
        request = self.context.get('request')
        try:
            if product and getattr(product, 'image', None):
                img = product.image
                name = getattr(img, 'name', None)
                exists = bool(name) and default_storage.exists(name)
                url = img.url if exists else settings.MEDIA_URL + 'products/default.png'
            else:
                url = settings.MEDIA_URL + 'products/default.png'
        except Exception:
            url = settings.MEDIA_URL + 'products/default.png'
        if request:
            return request.build_absolute_uri(url)
        return url

    class Meta:
        model = Investment
        fields = '__all__'
        read_only_fields = (
            'user', 'transaction', 'total_amount', 'profit_type', 'profit_rate', 
            'profit_method', 'claim_reset_mode', 'claim_reset_hours', 'duration_days', 'expires_at',
            'last_claim_time', 'next_claim_time', 'total_claimed_profit', 'status',
            'created_at', 'updated_at', 'user_phone', 'product_name', 'product_price', 'product_golongan', 'product_specification', 'product_description', 'transaction_id', 'daily_profit',
            'total_potential_profit', 'remaining_profit', 'can_claim_today', 'can_claim_manually',
            'can_claim_principal', 'principal_claim_locked_reason',
            'next_claim_time_calculated', 'profit_random_min', 'profit_random_max'
        )


class ProductPurchaseSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, default=1)
    withdraw_pin = serializers.CharField(write_only=True, required=False, allow_blank=True)
    
    def validate_product_id(self, value):
        try:
            product = Product.objects.get(id=value, status=1)
        except Product.DoesNotExist:
            raise serializers.ValidationError("Produk tidak ditemukan atau tidak aktif.")
        return value
    
    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Kuantitas harus lebih dari 0.")
        return value
    
    def validate(self, data):
        product = Product.objects.get(id=data['product_id'])
        quantity = data['quantity']
        user = self.context['request'].user
        
        # Rank restriction check
        if getattr(product, 'require_min_rank_enabled', False):
            min_rank = getattr(product, 'min_required_rank', None)
            user_rank = getattr(user, 'rank', None)
            if min_rank is not None:
                if user_rank is None or int(user_rank) < int(min_rank):
                    raise serializers.ValidationError({
                        'product_id': f'Produk ini hanya bisa dibeli oleh user dengan rank minimal {min_rank}. Rank Anda: {user_rank or "-"}'
                    })

        required_product = getattr(product, 'required_product', None)
        if required_product:
            if required_product.id == product.id:
                raise serializers.ValidationError({
                    'product_id': 'Konfigurasi produk tidak valid (required_product sama dengan produk ini).'
                })
            if not Investment.objects.filter(user=user, product=required_product).exists():
                raise serializers.ValidationError({
                    'product_id': f'Anda harus memiliki produk "{required_product.name}" terlebih dahulu sebelum membeli produk ini.'
                })

        required_golongan = (getattr(product, 'required_golongan', None) or '').strip()
        if required_golongan:
            if not Investment.objects.filter(user=user, product__golongan=required_golongan).exists():
                raise serializers.ValidationError({
                    'product_id': f'Anda harus sudah membeli produk golongan "{required_golongan}" terlebih dahulu sebelum membeli produk ini.'
                })
        
        if product.stock_enabled and product.stock < quantity:
            raise serializers.ValidationError({
                'quantity': f'Stok tidak mencukupi. Tersedia: {product.stock}'
            })
        
        if quantity > product.purchase_limit:
            raise serializers.ValidationError({
                'quantity': f'Kuantitas melebihi batas pembelian {product.purchase_limit}'
            })
        
        existing_investments = Investment.objects.filter(
            user=user, 
            product=product
        ).count()
        
        if existing_investments >= product.purchase_limit:
            raise serializers.ValidationError({
                'product_id': f'Batas pembelian tercapai. Anda hanya bisa membeli produk ini {product.purchase_limit} kali. Saat ini sudah {existing_investments} kali.'
            })
        
        settings_obj = GeneralSetting.objects.order_by('-updated_at').first()
        withdraw_pin_raw = (data.get('withdraw_pin') or '').strip()
        require_withdraw_pin = bool(getattr(product, 'require_withdraw_pin_on_purchase', False))
        if settings_obj and settings_obj.require_withdraw_pin_on_purchase:
            require_withdraw_pin = True
        if require_withdraw_pin:
            if not withdraw_pin_raw:
                raise serializers.ValidationError({
                    'withdraw_pin': 'Withdraw PIN wajib diisi untuk melakukan pembelian.'
                })
        if withdraw_pin_raw:
            if not (len(withdraw_pin_raw) == 6 and withdraw_pin_raw.isdigit()):
                raise serializers.ValidationError({
                    'withdraw_pin': 'Withdraw PIN harus 6 digit angka.'
                })
            if not user.withdraw_pin:
                raise serializers.ValidationError({
                    'withdraw_pin': 'Withdraw PIN belum diset di akun Anda.'
                })
            if not user.check_withdraw_pin(withdraw_pin_raw):
                raise serializers.ValidationError({
                    'withdraw_pin': 'Withdraw PIN salah.'
                })
        
        return data


class ClaimProfitSerializer(serializers.Serializer):
    investment_id = serializers.IntegerField()
    
    def validate_investment_id(self, value):
        request = self.context.get('request')
        if not request or not request.user:
            raise serializers.ValidationError("Autentikasi diperlukan")
        
        try:
            Investment.objects.get(id=value, user=request.user)
        except Investment.DoesNotExist:
            raise serializers.ValidationError("Investasi tidak ditemukan atau bukan milik user")
        
        return value


class ClaimPrincipalSerializer(serializers.Serializer):
    investment_id = serializers.IntegerField()
    
    def validate_investment_id(self, value):
        request = self.context.get('request')
        if not request or not request.user:
            raise serializers.ValidationError("Autentikasi diperlukan")
        
        try:
            Investment.objects.get(id=value, user=request.user)
        except Investment.DoesNotExist:
            raise serializers.ValidationError("Investasi tidak ditemukan atau bukan milik user")
        
        return value


class ClaimCashbackSerializer(serializers.Serializer):
    transaction_id = serializers.CharField(max_length=50)
    
    def validate_transaction_id(self, value):
        request = self.context.get('request')
        if not request or not request.user:
            raise serializers.ValidationError("Autentikasi diperlukan")
        
        try:
            # Find the purchase transaction
            transaction = Transaction.objects.get(
                trx_id=value, 
                user=request.user,
                type='INVESTMENTS',
                status='COMPLETED'
            )
            
            # Check if product has cashback enabled
            if not transaction.product or not transaction.product.cashback_enabled:
                raise serializers.ValidationError("Transaksi ini tidak memenuhi syarat cashback")
            
            # Rule: satu cashback per produk per user
            product = transaction.product
            existing_cashback = Transaction.objects.filter(
                user=request.user,
                product=product,
                type='CASHBACK'
            ).exists()
            
            if existing_cashback:
                raise serializers.ValidationError("Cashback untuk produk ini sudah pernah diklaim")
                
        except Transaction.DoesNotExist:
            raise serializers.ValidationError("Transaksi tidak ditemukan atau tidak memenuhi syarat untuk klaim cashback")
        
        return value
