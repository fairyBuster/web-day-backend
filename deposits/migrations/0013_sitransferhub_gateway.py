from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("deposits", "0012_clienthub_gateway"),
    ]

    operations = [
        migrations.AddField(
            model_name="gatewaysettings",
            name="sitransferhub_base_url",
            field=models.CharField(blank=True, default="", help_text="Contoh: https://api.totc.site", max_length=255),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="sitransferhub_channel",
            field=models.CharField(blank=True, default="QRIS", help_text="Channel default: QRIS atau DANA", max_length=20),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="sitransferhub_client_id",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="sitransferhub_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="sitransferhub_secret_key",
            field=models.CharField(blank=True, default="", help_text="Secret key untuk HMAC request/callback", max_length=255),
        ),
        migrations.AlterField(
            model_name="deposit",
            name="gateway",
            field=models.CharField(
                choices=[
                    ("JAYAPAY", "Jayapay"),
                    ("JAYAPAY_PH", "Jayapay Philippines"),
                    ("KLIKPAY", "Klikpay"),
                    ("USD_GATEWAY", "USD Gateway"),
                    ("PPAYPROS", "PPay Pros"),
                    ("CLIENTHUB", "ClientHub"),
                    ("SITRANSFERHUB", "SiTransfer Hub"),
                ],
                max_length=20,
            ),
        ),
    ]
