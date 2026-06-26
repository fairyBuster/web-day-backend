from decimal import Decimal
from django.core.management.base import BaseCommand
from banks.models import Bank


class Command(BaseCommand):
    help = "Seed default banks for withdraw requirements"

    def handle(self, *args, **options):
        banks_data = [
            {
                'code': 'BCA',
                'name': 'BCA',
                'is_active': True,
                'logo': '',
                'min_withdrawal': Decimal('10000.00'),
                'max_withdrawal': Decimal('5000000.00'),
                'withdrawal_fee': Decimal('15.00'),
                'processing_time': 1,
            },
            {
                'code': 'BRI',
                'name': 'BRI',
                'is_active': True,
                'logo': '',
                'min_withdrawal': Decimal('10000.00'),
                'max_withdrawal': Decimal('3000000.00'),
                'withdrawal_fee': Decimal('12.50'),
                'processing_time': 1,
            },
            {
                'code': 'MANDIRI',
                'name': 'Mandiri',
                'is_active': True,
                'logo': '',
                'min_withdrawal': Decimal('10000.00'),
                'max_withdrawal': Decimal('4000000.00'),
                'withdrawal_fee': Decimal('10.00'),
                'processing_time': 1,
            },
            {
                'code': 'BNI',
                'name': 'BNI',
                'is_active': True,
                'logo': '',
                'min_withdrawal': Decimal('10000.00'),
                'max_withdrawal': Decimal('3500000.00'),
                'withdrawal_fee': Decimal('10.00'),
                'processing_time': 1,
            },
            {
                'code': 'CIMB',
                'name': 'CIMB Niaga',
                'is_active': True,
                'logo': '',
                'min_withdrawal': Decimal('10000.00'),
                'max_withdrawal': Decimal('2500000.00'),
                'withdrawal_fee': Decimal('8.00'),
                'processing_time': 2,
            },
            {
                'code': 'PERMATA',
                'name': 'Permata',
                'is_active': True,
                'logo': '',
                'min_withdrawal': Decimal('10000.00'),
                'max_withdrawal': Decimal('2000000.00'),
                'withdrawal_fee': Decimal('7.50'),
                'processing_time': 2,
            },
        ]

        created = 0
        updated = 0

        for data in banks_data:
            obj, exists = Bank.objects.get_or_create(
                code=data['code'],
                defaults={
                    'name': data['name'],
                    'is_active': data['is_active'],
                    'logo': data['logo'],
                    'min_withdrawal': data['min_withdrawal'],
                    'max_withdrawal': data['max_withdrawal'],
                    'withdrawal_fee': data['withdrawal_fee'],
                    'processing_time': data['processing_time'],
                }
            )
            if exists:
                obj.name = data['name']
                obj.is_active = data['is_active']
                obj.logo = data['logo']
                obj.min_withdrawal = data['min_withdrawal']
                obj.max_withdrawal = data['max_withdrawal']
                obj.withdrawal_fee = data['withdrawal_fee']
                obj.processing_time = data['processing_time']
                obj.save()
                updated += 1
            else:
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Seeded banks: created={created}, updated={updated}, total={Bank.objects.count()}"
        ))