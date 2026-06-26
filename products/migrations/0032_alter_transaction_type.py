from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("products", "0031_product_required_product"),
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

