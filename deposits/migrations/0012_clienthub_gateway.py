from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("deposits", "0011_ppaypros_gateway"),
    ]

    operations = [
        migrations.AddField(
            model_name="gatewaysettings",
            name="clienthub_base_url",
            field=models.CharField(blank=True, default="", help_text="Contoh: https://api.totc.site", max_length=255),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="clienthub_client_id",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="clienthub_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="clienthub_expired_minutes",
            field=models.PositiveIntegerField(default=60, help_text="Masa berlaku invoice dalam menit"),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="clienthub_method",
            field=models.CharField(blank=True, default="BRIVA", max_length=50),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="clienthub_return_url",
            field=models.CharField(blank=True, default="", help_text="URL redirect setelah pembayaran selesai", max_length=512),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="clienthub_secret_key",
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
                ],
                max_length=20,
            ),
        ),
    ]
