# Add expired_at to Deposit and qris_expired_minutes to GatewaySettings

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('deposits', '0018_qris_gateway'),
    ]

    operations = [
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
    ]
