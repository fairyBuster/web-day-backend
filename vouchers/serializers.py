from rest_framework import serializers
from django.utils import timezone
from zoneinfo import ZoneInfo
from .models import Voucher, VoucherUsage


class VoucherSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    is_claimable = serializers.SerializerMethodField()

    class Meta:
        model = Voucher
        fields = ['id', 'code', 'type', 'claim_mode', 'amount', 'min_amount', 'max_amount', 'rank_rewards', 'balance_type', 'usage_limit', 'used_count', 'is_active', 'is_daily_claim', 'start_at', 'expires_at', 'created_at', 'updated_at', 'status', 'is_claimable']

    def get_status(self, obj):
        request = self.context.get('request')
        # If no user context, assume available or just return basic status
        if not request or not request.user.is_authenticated:
            return 'unauthenticated'
        
        user = request.user
        now = timezone.now()
        jakarta_tz = ZoneInfo('Asia/Jakarta')
        now_local = timezone.localtime(now, jakarta_tz) if timezone.is_aware(now) else now

        # 1. Check time
        if obj.start_at and now < obj.start_at:
            return 'not_started'
        if obj.expires_at and now >= obj.expires_at:
            return 'expired'
            
        # 2. Check quota (Global/Daily)
        if obj.is_daily_claim:
             today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
             
             # Note: This might be slow for many vouchers; optimization would require annotating the queryset
             daily_usage_count = VoucherUsage.objects.filter(
                 voucher=obj, 
                 used_at__gte=today_start_local
             ).count()
             
             if daily_usage_count >= obj.usage_limit:
                 return 'quota_full'
        else:
             if obj.used_count >= obj.usage_limit:
                 return 'quota_full'
        
        # 3. Check User Claim Status
        if obj.is_daily_claim:
             today_start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
             
             if VoucherUsage.objects.filter(voucher=obj, user=user, used_at__gte=today_start_local).exists():
                 return 'claimed'
        else:
             if VoucherUsage.objects.filter(voucher=obj, user=user).exists():
                 return 'claimed'
                 
        return 'available'

    def get_is_claimable(self, obj):
        return self.get_status(obj) == 'available'


class ClaimVoucherSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=50)


class VoucherListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    results = VoucherSerializer(many=True)


class ClaimVoucherResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    voucher_code = serializers.CharField()
    amount = serializers.CharField()
    wallet_type = serializers.CharField()
    transaction_id = serializers.CharField()
    balance = serializers.CharField()
