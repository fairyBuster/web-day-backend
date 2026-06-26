from rest_framework import serializers
from .models import Mission
from .utils import compute_mission_progress


class MissionSerializer(serializers.ModelSerializer):
    progress = serializers.SerializerMethodField()
    progress_amount = serializers.SerializerMethodField()
    claimable_times = serializers.SerializerMethodField()
    remaining = serializers.SerializerMethodField()
    can_claim = serializers.SerializerMethodField()
    claimed = serializers.SerializerMethodField()
    claimed_count = serializers.SerializerMethodField()
    last_claimed_at = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()

    class Meta:
        model = Mission
        fields = (
            'id', 'title', 'description', 'type', 'requirement', 'reward', 'reward_balance_type',
            'is_active', 'is_repeatable', 'level', 'referral_levels', 'created_at', 'updated_at',
            'progress', 'progress_amount', 'claimable_times', 'remaining', 'can_claim', 'claimed', 'claimed_count', 'last_claimed_at', 'status'
        )

    def get_progress(self, obj):
        pm = self.context.get('progress_map')
        if pm and obj.id in pm:
            return pm[obj.id]
        user = self.context.get('request').user
        return compute_mission_progress(obj, user)

    def get_progress_amount(self, obj):
        pm = self.context.get('progress_map')
        if obj.type == 'deposit_self':
            total = self.context.get('deposit_self_total')
            if total is not None:
                return str(total)
        if obj.type == 'deposit':
            dm = self.context.get('deposit_totals_map') or {}
            if obj.id in dm:
                return str(dm[obj.id])
        if pm and obj.id in pm:
            return str(pm[obj.id])
        user = self.context.get('request').user
        return str(compute_mission_progress(obj, user))

    def get_claimable_times(self, obj):
        progress = self.get_progress(obj)
        sm = self.context.get('state_map') or {}
        state = sm.get(obj.id)
        claimed = state.claimed_count if state else 0
        times = progress // obj.requirement
        available = times - claimed
        if not obj.is_repeatable:
            available = 1 if (progress >= obj.requirement and claimed == 0) else 0
        return max(0, available)

    def get_remaining(self, obj):
        progress = self.get_progress(obj)
        rem = obj.requirement - (progress % obj.requirement if obj.is_repeatable else progress)
        return max(0, rem)

    def get_claimed_count(self, obj):
        sm = self.context.get('state_map') or {}
        state = sm.get(obj.id)
        return state.claimed_count if state else 0

    def get_last_claimed_at(self, obj):
        sm = self.context.get('state_map') or {}
        state = sm.get(obj.id)
        return state.last_claimed_at.isoformat() if state and state.last_claimed_at else None

    def get_claimed(self, obj):
        return self.get_claimed_count(obj) > 0

    def get_can_claim(self, obj):
        if not obj.is_active:
            return False
        progress = self.get_progress(obj)
        claimed = self.get_claimed_count(obj)
        if not obj.is_repeatable:
            return progress >= obj.requirement and claimed == 0
        times = progress // obj.requirement
        return (times - claimed) > 0

    def get_status(self, obj):
        if not obj.is_active:
            return 'inactive'
        if self.get_can_claim(obj):
            return 'available'
        claimed = self.get_claimed_count(obj)
        progress = self.get_progress(obj)
        if not obj.is_repeatable and claimed > 0:
            return 'claimed'
        times = progress // obj.requirement
        if progress < obj.requirement:
            return 'in_progress'
        if obj.is_repeatable and times <= claimed:
            return 'exhausted'
        return 'in_progress'


class ClaimMissionSerializer(serializers.Serializer):
    mission_id = serializers.IntegerField(required=True)
    times = serializers.IntegerField(required=False, min_value=1, default=1)


# No placeholders; compute_mission_progress is defined in utils


class MissionListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    results = MissionSerializer(many=True)


class ClaimMissionResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    mission_id = serializers.IntegerField()
    times_claimed = serializers.IntegerField()
    reward_amount = serializers.CharField()
    wallet_type = serializers.CharField()
    transaction_id = serializers.CharField()
    new_balance = serializers.CharField()
