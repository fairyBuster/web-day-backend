# Generated migration for Reepay Gateway (deposit)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deposits', '0018_qris_gateway'),
    ]

    operations = [
        migrations.AddField(
            model_name='gatewaysettings',
            name='reepay_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='gatewaysettings',
            name='reepay_api_url',
            field=models.CharField(blank=True, default='https://api.roguecdn.online', help_text='Base URL Reepay', max_length=255),
        ),
        migrations.AddField(
            model_name='gatewaysettings',
            name='reepay_api_key',
            field=models.CharField(blank=True, default='', help_text='X-API-Key merchant (ak_...)', max_length=255),
        ),
        migrations.AddField(
            model_name='gatewaysettings',
            name='reepay_secret_key',
            field=models.CharField(blank=True, default='', help_text='Secret key untuk HMAC-SHA256 signature', max_length=255),
        ),
        migrations.AddField(
            model_name='gatewaysettings',
            name='reepay_return_url',
            field=models.CharField(blank=True, default='', help_text='URL redirect setelah pembayaran selesai (opsional)', max_length=512),
        ),
        migrations.AlterField(
            model_name='deposit',
            name='gateway',
            field=models.CharField(choices=[('JAYAPAY', 'Jayapay'), ('JAYAPAY_PH', 'Jayapay Philippines'), ('KLIKPAY', 'Klikpay'), ('USD_GATEWAY', 'USD Gateway'), ('PPAYPROS', 'PPay Pros'), ('CLIENTHUB', 'ClientHub'), ('SITRANSFERHUB', 'SiTransfer Hub'), ('ATPAY', 'ATPAY'), ('BANKPAY', 'BankPay'), ('QRIS', 'QRIS Manual'), ('REEPAY', 'Reepay')], max_length=20),
        ),
    ]
