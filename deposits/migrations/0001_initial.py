from django.db import migrations, models
from django.conf import settings


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('products', '0002_investment'),
    ]

    operations = [
        migrations.CreateModel(
            name='GatewaySettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('default_wallet_type', models.CharField(choices=[('BALANCE', 'Balance'), ('BALANCE_DEPOSIT', 'Balance Deposit')], default='BALANCE', max_length=20)),
                ('app_domain', models.CharField(blank=True, default='', help_text='Contoh: myapp.example.com (tanpa http/https)', max_length=255)),
                ('jayapay_enabled', models.BooleanField(default=True)),
                ('klikpay_enabled', models.BooleanField(default=False)),
                ('jayapay_merchant_code', models.CharField(blank=True, default='', max_length=100)),
                ('jayapay_private_key', models.TextField(blank=True, default='', help_text='Paste RSA PRIVATE KEY body ONLY (without BEGIN/END headers)')),
                ('jayapay_public_key', models.TextField(blank=True, default='', help_text='Optional: PUBLIC KEY untuk verifikasi/dekripsi callback bila diperlukan')),
                ('klikpay_api_url', models.CharField(blank=True, default='', max_length=255)),
                ('klikpay_merchant_code', models.CharField(blank=True, default='', max_length=100)),
                ('klikpay_secret_key', models.CharField(blank=True, default='', max_length=255)),
                ('klikpay_public_key', models.TextField(blank=True, default='', help_text='Optional: PUBLIC KEY jika penyedia memerlukan')),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Gateway Settings',
                'verbose_name_plural': 'Gateway Settings',
            },
        ),
        migrations.CreateModel(
            name='Deposit',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('gateway', models.CharField(choices=[('JAYAPAY', 'Jayapay'), ('KLIKPAY', 'Klikpay')], max_length=20)),
                ('order_num', models.CharField(max_length=60, unique=True)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=15)),
                ('wallet_type', models.CharField(choices=[('BALANCE', 'Balance'), ('BALANCE_DEPOSIT', 'Balance Deposit')], max_length=20)),
                ('status', models.CharField(choices=[('PENDING', 'Pending'), ('PROCESSING', 'Processing'), ('COMPLETED', 'Completed'), ('FAILED', 'Failed'), ('CANCELLED', 'Cancelled')], default='PENDING', max_length=20)),
                ('payment_url', models.CharField(blank=True, default='', max_length=500)),
                ('request_params', models.JSONField(blank=True, default=dict)),
                ('response_payload', models.JSONField(blank=True, null=True)),
                ('callback_payload', models.JSONField(blank=True, null=True)),
                ('callback_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('transaction', models.ForeignKey(blank=True, null=True, on_delete=models.deletion.SET_NULL, to='products.transaction')),
                ('user', models.ForeignKey(on_delete=models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'deposits',
                'ordering': ['-created_at'],
            },
        ),
    ]