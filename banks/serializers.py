from rest_framework import serializers
from .models import Bank, UserBank, BankSettings


class BankSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bank
        fields = (
            'id', 'code', 'name', 'currency_code', 'is_active', 'logo', 'min_withdrawal',
            'max_withdrawal', 'withdrawal_fee', 'withdrawal_fee_fixed', 'processing_time', 'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')


class UserBankSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = UserBank
        fields = (
            'id', 'user', 'bank', 'account_name', 'account_number', 'phone', 'is_default', 'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')

    def validate(self, attrs):
        bank = attrs.get('bank')
        user = attrs.get('user')
        
        # Validasi bank harus aktif
        if bank and not bank.is_active:
            raise serializers.ValidationError('Bank tidak aktif.')
        
        # Validasi limit maksimal bank per user (hanya untuk create)
        if not self.instance:  # Create mode
            currency_code = getattr(bank, "currency_code", None) if bank else None
            max_banks = BankSettings.get_max_banks_per_user_by_currency(currency_code)
            if (currency_code or "").upper() == "IDR":
                current_bank_count = UserBank.objects.filter(user=user, bank__currency_code="IDR").count()
                limit_label = "bank IDR"
            else:
                current_bank_count = UserBank.objects.filter(user=user).exclude(bank__currency_code="IDR").count()
                limit_label = "bank non-IDR"

            if current_bank_count >= max_banks:
                raise serializers.ValidationError(f'User sudah mencapai batas maksimal {max_banks} {limit_label}.')
            
            # Validasi tidak boleh duplikat bank yang sama
            if UserBank.objects.filter(user=user, bank=bank).exists():
                raise serializers.ValidationError('User sudah memiliki bank ini.')
        
        return attrs

    def create(self, validated_data):
        user = validated_data['user']
        
        # Jika ini bank pertama user, set sebagai default
        if not UserBank.objects.filter(user=user).exists():
            validated_data['is_default'] = True
        
        return super().create(validated_data)

    def update(self, instance, validated_data):
        # Jika mengubah is_default menjadi True, unset default lainnya
        if validated_data.get('is_default', False):
            UserBank.objects.filter(user=instance.user, is_default=True).exclude(id=instance.id).update(is_default=False)
        
        return super().update(instance, validated_data)


class UserBankListSerializer(serializers.ModelSerializer):
    """Serializer untuk list semua bank user"""
    bank_name = serializers.CharField(source='bank.name', read_only=True)
    bank_code = serializers.CharField(source='bank.code', read_only=True)
    currency_code = serializers.CharField(source='bank.currency_code', read_only=True)
    withdrawal_fee = serializers.DecimalField(source='bank.withdrawal_fee', max_digits=7, decimal_places=2, read_only=True)
    withdrawal_fee_fixed = serializers.DecimalField(source='bank.withdrawal_fee_fixed', max_digits=15, decimal_places=2, read_only=True)
    
    class Meta:
        model = UserBank
        fields = (
            'id', 'bank', 'bank_name', 'bank_code', 'currency_code', 'withdrawal_fee', 'withdrawal_fee_fixed', 'account_name', 
            'account_number', 'phone', 'is_default', 'created_at', 'updated_at'
        )
        read_only_fields = ('id', 'created_at', 'updated_at')
