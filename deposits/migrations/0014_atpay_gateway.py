from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("deposits", "0013_sitransferhub_gateway"),
    ]

    operations = [
        migrations.AddField(
            model_name="gatewaysettings",
            name="atpay_api_url",
            field=models.CharField(blank=True, default="https://test.wowpay.biz", max_length=255),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="atpay_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="atpay_merchant_no",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="atpay_private_key",
            field=models.TextField(blank=True, default="", help_text="Dipakai jika sign_type=MD5withRsa"),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="atpay_public_key",
            field=models.TextField(blank=True, default="", help_text="Public key ATPAY untuk verifikasi callback MD5withRsa"),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="atpay_return_url",
            field=models.CharField(blank=True, default="", help_text="URL redirect setelah pembayaran selesai", max_length=512),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="atpay_secret_key",
            field=models.CharField(blank=True, default="", help_text="Dipakai jika sign_type=MD5", max_length=255),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="atpay_sign_type",
            field=models.CharField(blank=True, default="MD5", help_text="MD5 atau MD5withRsa", max_length=20),
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
                    ("ATPAY", "ATPAY"),
                ],
                max_length=20,
            ),
        ),
    ]
