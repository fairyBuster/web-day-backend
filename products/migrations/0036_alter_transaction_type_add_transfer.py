from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0035_remove_transaction_conversion_rate_to_idr_and_more"),
    ]

    operations = [
        migrations.AlterField(
            model_name="transaction",
            name="type",
            field=models.CharField(
                choices=[
                    ("CREDIT", "Credit"),
                    ("BONUS", "Bonus"),
                    ("DEBIT", "Debit"),
                    ("TRANSFER", "Transfer"),
                    ("DEPOSIT", "Deposit"),
                    ("WITHDRAW", "Withdraw"),
                    ("PURCHASE_COMMISSION", "Purchase Commission"),
                    ("PROFIT_COMMISSION", "Profit Commission"),
                    ("INTEREST", "Interest"),
                    ("INVESTMENTS", "Investments"),
                    ("MISSIONS", "Missions"),
                    ("VOUCHER", "Voucher"),
                    ("ATTENDANCE", "Attendance"),
                    ("CASHBACK", "Cashback"),
                    ("REJECT", "Reject"),
                    ("RETURN", "Return"),
                    ("HOLD_RELEASE", "Hold Release"),
                ],
                max_length=20,
            ),
        ),
    ]
