from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("withdrawal", "0009_seed_default_withdrawal_services"),
    ]

    operations = [
        migrations.AddField(
            model_name="withdrawalsettings",
            name="require_withdraw_service",
            field=models.BooleanField(default=True, help_text="Jika ON, user wajib memilih WithdrawalService aktif; jika OFF, boleh tanpa service"),
        ),
    ]
