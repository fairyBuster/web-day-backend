from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("banks", "0003_banksettings_remove_userbank_unique_user_bank_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="bank",
            name="withdrawal_fee_fixed",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=15),
        ),
    ]

