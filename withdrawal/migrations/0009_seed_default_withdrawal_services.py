from django.db import migrations, models
from decimal import Decimal


def seed_default_withdrawal_services(apps, schema_editor):
    WithdrawalService = apps.get_model('withdrawal', 'WithdrawalService')

    defaults = [
        {
            'name': 'Cepat 6 Jam',
            'description': 'Proses withdraw sekitar 6 jam kerja',
            'duration_hours': 6,
            'fee_percent': Decimal('10.00'),
            'sort_order': 1,
        },
        {
            'name': 'Standar 24 Jam',
            'description': 'Proses withdraw sekitar 24 jam',
            'duration_hours': 24,
            'fee_percent': Decimal('5.00'),
            'sort_order': 2,
        },
        {
            'name': 'Hemat 48 Jam',
            'description': 'Proses withdraw sekitar 48 jam',
            'duration_hours': 48,
            'fee_percent': Decimal('2.00'),
            'sort_order': 3,
        },
    ]

    if WithdrawalService.objects.exists():
        return

    for data in defaults:
        WithdrawalService.objects.get_or_create(
            name=data['name'],
            defaults={
                'description': data['description'],
                'duration_hours': data['duration_hours'],
                'fee_percent': data['fee_percent'],
                'is_active': True,
                'sort_order': data['sort_order'],
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        ('withdrawal', '0008_withdrawalservice_withdrawal_withdrawal_service'),
    ]

    operations = [
        migrations.RunPython(seed_default_withdrawal_services, migrations.RunPython.noop),
    ]

