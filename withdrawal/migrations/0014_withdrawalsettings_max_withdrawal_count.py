from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("withdrawal", "0013_withdrawalsettings_jayapay_and_ph_payout"),
    ]

    operations = [
        migrations.AddField(
            model_name="withdrawalsettings",
            name="max_withdrawal_count",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Batas maksimal jumlah penarikan per user. 0 = tanpa batas. Hanya menghitung request PENDING, PROCESSING, dan COMPLETED.",
            ),
        ),
    ]
