from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("withdrawal", "0014_withdrawalsettings_max_withdrawal_count"),
    ]

    operations = [
        migrations.AddField(
            model_name="withdrawalsettings",
            name="ppaypros_payout_api_url",
            field=models.CharField(blank=True, default="https://pay.ppaypros.com", max_length=255),
        ),
        migrations.AddField(
            model_name="withdrawalsettings",
            name="ppaypros_payout_app_id",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="withdrawalsettings",
            name="ppaypros_payout_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="withdrawalsettings",
            name="ppaypros_payout_entry_type",
            field=models.CharField(blank=True, default="BANK_CARD", help_text="Default entryType payout, contoh: BANK_CARD", max_length=32),
        ),
        migrations.AddField(
            model_name="withdrawalsettings",
            name="ppaypros_payout_mch_no",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="withdrawalsettings",
            name="ppaypros_payout_private_key",
            field=models.CharField(blank=True, default="", help_text="Private key/sign key untuk MD5 signature", max_length=255),
        ),
        migrations.CreateModel(
            name="PPayProsWithdrawal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_params", models.JSONField(default=dict)),
                ("response_payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "withdrawal",
                    models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="ppaypros_withdrawal", to="withdrawal.withdrawal"),
                ),
            ],
            options={
                "db_table": "withdrawal_ppaypros",
                "ordering": ["-created_at"],
            },
        ),
    ]
