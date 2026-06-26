from rest_framework import serializers
from .models import RoulettePrize


class RoulettePrizeSerializer(serializers.ModelSerializer):
    probability_percent = serializers.SerializerMethodField()

    class Meta:
        model = RoulettePrize
        fields = ("id", "name", "description", "prize_type", "amount", "probability_percent")

    def get_probability_percent(self, obj):
        total_weight = self.context.get("total_weight") or 0
        if not total_weight:
            return "0"
        try:
            return str(round((obj.weight / total_weight) * 100, 4))
        except Exception:
            return "0"


class RouletteStatusResponseSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()
    ticket_cost = serializers.IntegerField()
    tickets = serializers.IntegerField()
    prizes = RoulettePrizeSerializer(many=True)


class RouletteSpinResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    tickets_before = serializers.IntegerField()
    tickets_after = serializers.IntegerField()
    prize_id = serializers.IntegerField(allow_null=True)
    prize_name = serializers.CharField(allow_null=True)
    prize_type = serializers.CharField()
    prize_amount = serializers.CharField()
    transaction_id = serializers.CharField(allow_null=True)


class RouletteEarnMethodsResponseSerializer(serializers.Serializer):
    is_active = serializers.BooleanField()
    grant_tickets_from_level1_purchase = serializers.BooleanField()
    tickets_per_level1_purchase = serializers.IntegerField()
    grant_tickets_from_self_deposit = serializers.BooleanField()
    tickets_per_completed_deposit = serializers.IntegerField()
    min_deposit_amount_for_tickets = serializers.CharField()
    ticket_cost = serializers.IntegerField()
