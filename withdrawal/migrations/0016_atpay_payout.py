from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("withdrawal", "0015_ppaypros_payout"),
    ]

    operations = [
        migrations.AddField(
            model_name="withdrawalsettings",
            name="atpay_payout_api_url",
            field=models.CharField(blank=True, default="https://test.wowpay.biz", max_length=255),
        ),
        migrations.AddField(
            model_name="withdrawalsettings",
            name="atpay_payout_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="withdrawalsettings",
            name="atpay_payout_merchant_no",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="withdrawalsettings",
            name="atpay_payout_private_key",
            field=models.TextField(blank=True, default="", help_text="Dipakai jika sign_type=MD5withRsa"),
        ),
        migrations.AddField(
            model_name="withdrawalsettings",
            name="atpay_payout_public_key",
            field=models.TextField(blank=True, default="", help_text="Public key ATPAY untuk verifikasi callback MD5withRsa"),
        ),
        migrations.AddField(
            model_name="withdrawalsettings",
            name="atpay_payout_secret_key",
            field=models.CharField(blank=True, default="", help_text="Dipakai jika sign_type=MD5", max_length=255),
        ),
        migrations.AddField(
            model_name="withdrawalsettings",
            name="atpay_payout_sign_type",
            field=models.CharField(blank=True, default="MD5", help_text="MD5 atau MD5withRsa", max_length=20),
        ),
        migrations.CreateModel(
            name="AtpayWithdrawal",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("request_params", models.JSONField(default=dict)),
                ("response_payload", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("withdrawal", models.OneToOneField(on_delete=models.deletion.CASCADE, related_name="atpay_withdrawal", to="withdrawal.withdrawal")),
            ],
            options={
                "db_table": "withdrawal_atpay",
                "ordering": ["-created_at"],
            },
        ),
    ]
