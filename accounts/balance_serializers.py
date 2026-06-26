from rest_framework import serializers


class ActiveProductSummarySerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    name = serializers.CharField()
    active_count = serializers.IntegerField()
    total_quantity = serializers.IntegerField()
    total_amount = serializers.DecimalField(max_digits=15, decimal_places=2)


class BalanceStatisticsSerializer(serializers.Serializer):
    balance = serializers.DecimalField(max_digits=15, decimal_places=2)
    balance_deposit = serializers.DecimalField(max_digits=15, decimal_places=2)
    balance_hold = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_deposit_completed = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_deposit_count = serializers.IntegerField()
    total_withdraw_completed = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_withdraw_count = serializers.IntegerField()
    total_commission = serializers.DecimalField(max_digits=15, decimal_places=2)
    profit_commission = serializers.DecimalField(max_digits=15, decimal_places=2)
    purchase_commission = serializers.DecimalField(max_digits=15, decimal_places=2)
    # Interest total (claim profit) & cashback total
    interest_total = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_cashback = serializers.DecimalField(max_digits=15, decimal_places=2)
    # Tambahan: total attendance credit dari transaksi type 'ATTENDANCE'
    attendance_total = serializers.DecimalField(max_digits=15, decimal_places=2)
    bonus_total = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_income = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_transactions = serializers.IntegerField()
    period = serializers.CharField()
    # Produk/investasi aktif yang dimiliki user saat ini
    active_investments_count = serializers.IntegerField()
    active_products = ActiveProductSummarySerializer(many=True)
    # Anggota aktif per level downline (1-3)
    active_members_level_1 = serializers.IntegerField()
    active_members_level_2 = serializers.IntegerField()
    active_members_level_3 = serializers.IntegerField()
    active_members_total_1_3 = serializers.IntegerField()


class HoldBalanceTransferSerializer(serializers.Serializer):
    amount_transferred = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    balance = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    balance_hold = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    transaction_id = serializers.CharField(read_only=True)
    message = serializers.CharField(read_only=True)


class CashbackBalanceSerializer(serializers.Serializer):
    balance_cashback = serializers.DecimalField(max_digits=15, decimal_places=2)


class CashbackBalanceTransferSerializer(serializers.Serializer):
    amount_transferred = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    balance = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    balance_cashback = serializers.DecimalField(max_digits=15, decimal_places=2, read_only=True)
    transaction_id = serializers.CharField(read_only=True)
    message = serializers.CharField(read_only=True)


class CashbackTransferredStatsSerializer(serializers.Serializer):
    total_transferred = serializers.DecimalField(max_digits=15, decimal_places=2)
    transfer_count = serializers.IntegerField()
