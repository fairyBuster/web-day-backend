from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deposits', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='gatewaysettings',
            name='jayapay_api_url',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='gatewaysettings',
            name='jayapay_callback_path',
            field=models.CharField(blank=True, default='', help_text='Contoh: gateway/payment/notify_xxx', max_length=255),
        ),
        migrations.AddField(
            model_name='gatewaysettings',
            name='jayapay_redirect_url',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
        migrations.AddField(
            model_name='gatewaysettings',
            name='klikpay_private_key',
            field=models.TextField(blank=True, default='', help_text='Optional: PRIVATE KEY jika penyedia memerlukan RSA signing'),
        ),
        migrations.AddField(
            model_name='gatewaysettings',
            name='klikpay_callback_path',
            field=models.CharField(blank=True, default='', help_text='Contoh: gateway/payment/notify_xxx', max_length=255),
        ),
        migrations.AddField(
            model_name='gatewaysettings',
            name='klikpay_redirect_url',
            field=models.CharField(blank=True, default='', max_length=255),
        ),
    ]