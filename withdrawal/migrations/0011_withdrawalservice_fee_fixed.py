from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("withdrawal", "0010_withdrawalsettings_require_withdraw_service"),
    ]

    operations = [
        migrations.AddField(
            model_name="withdrawalservice",
            name="fee_fixed",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=15),
        ),
    ]

