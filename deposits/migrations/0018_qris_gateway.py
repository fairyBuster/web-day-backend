# Generated migration for QRIS Gateway

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deposits', '0017_extend_payment_url'),
    ]

    operations = [
        migrations.AddField(
            model_name='gatewaysettings',
            name='qris_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='gatewaysettings',
            name='qris_min_deposit_amount',
            field=models.DecimalField(decimal_places=2, default=10000, help_text='Minimal nominal deposit QRIS', max_digits=15),
        ),
        migrations.AddField(
            model_name='gatewaysettings',
            name='qris_max_deposit_amount',
            field=models.DecimalField(decimal_places=2, default=5000000, help_text='Maksimal nominal deposit QRIS (0 = tidak dibatasi)', max_digits=15),
        ),
        migrations.AddField(
            model_name='gatewaysettings',
            name='qris_expired_minutes',
            field=models.PositiveIntegerField(default=30, help_text='QR kadaluarsa setelah berapa menit (0 = tidak kadaluarsa)'),
        ),
        migrations.AddField(
            model_name='deposit',
            name='expired_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name='deposit',
            name='gateway',
            field=models.CharField(choices=[('JAYAPAY', 'Jayapay'), ('JAYAPAY_PH', 'Jayapay Philippines'), ('KLIKPAY', 'Klikpay'), ('USD_GATEWAY', 'USD Gateway'), ('PPAYPROS', 'PPay Pros'), ('CLIENTHUB', 'ClientHub'), ('SITRANSFERHUB', 'SiTransfer Hub'), ('ATPAY', 'ATPAY'), ('BANKPAY', 'BankPay'), ('QRIS', 'QRIS Manual')], max_length=20),
        ),
        migrations.CreateModel(
            name='QRISGateway',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('label', models.CharField(help_text='Label/nama QRIS (contoh: QRIS BCA, ShopeePay)', max_length=100)),
                ('qris_image', models.ImageField(blank=True, help_text='Upload gambar QRIS static', null=True, upload_to='qris/images/')),
                ('qris_raw_data', models.TextField(blank=True, default='', help_text='Raw QRIS string hasil scan (0002010102...)')),
                ('is_active', models.BooleanField(default=True, help_text='Aktifkan QR ini untuk digunakan')),
                ('max_use_count', models.PositiveIntegerField(default=0, help_text='Maksimal berapa kali QR ini bisa dipakai (0 = unlimited)')),
                ('used_count', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'QRIS Gateway',
                'verbose_name_plural': 'QRIS Gateway',
                'ordering': ['-created_at'],
                'db_table': 'deposits_qris_gateway',
            },
        ),
    ]
