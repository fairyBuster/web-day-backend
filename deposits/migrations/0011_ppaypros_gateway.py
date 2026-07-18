from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("deposits", "0010_jayapay_ph_gateway"),
    ]

    operations = [
        migrations.AddField(
            model_name="gatewaysettings",
            name="ppaypros_api_url",
            field=models.CharField(blank=True, default="https://pay.ppaypros.com", max_length=255),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="ppaypros_app_id",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="ppaypros_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="ppaypros_ext_param",
            field=models.CharField(blank=True, default="", help_text="Kode bank/wallet default, contoh: BRI, BNI, dana, gopay", max_length=64),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="ppaypros_mch_no",
            field=models.CharField(blank=True, default="", max_length=100),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="ppaypros_private_key",
            field=models.CharField(blank=True, default="", help_text="Private key/sign key untuk MD5 signature", max_length=255),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="ppaypros_return_url",
            field=models.CharField(blank=True, default="", help_text="URL redirect setelah pembayaran selesai", max_length=512),
        ),
        migrations.AddField(
            model_name="gatewaysettings",
            name="ppaypros_way_code",
            field=models.CharField(blank=True, default="809", help_text="wayCode default, contoh: 808 (bank) atau 809 (e-wallet)", max_length=32),
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
                ],
                max_length=20,
            ),
        ),
    ]
