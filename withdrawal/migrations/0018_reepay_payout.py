# Generated migration for Reepay Payout (withdrawal)

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('withdrawal', '0017_bankpay_payout'),
    ]

    operations = [
        migrations.AddField(
            model_name='withdrawalsettings',
            name='reepay_payout_enabled',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='withdrawalsettings',
            name='reepay_payout_api_url',
            field=models.CharField(blank=True, default='https://api.roguecdn.online', help_text='Base URL Reepay', max_length=255),
        ),
        migrations.AddField(
            model_name='withdrawalsettings',
            name='reepay_payout_api_key',
            field=models.CharField(blank=True, default='', help_text='X-API-Key merchant (ak_...)', max_length=255),
        ),
        migrations.AddField(
            model_name='withdrawalsettings',
            name='reepay_payout_secret_key',
            field=models.CharField(blank=True, default='', help_text='Secret key untuk HMAC-SHA256 signature payout', max_length=255),
        ),
        migrations.CreateModel(
            name='ReepayWithdrawal',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('request_params', models.JSONField(default=dict)),
                ('response_payload', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('withdrawal', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='reepay_withdrawal', to='withdrawal.withdrawal')),
            ],
            options={
                'db_table': 'withdrawal_reepay',
                'ordering': ['-created_at'],
            },
        ),
    ]
