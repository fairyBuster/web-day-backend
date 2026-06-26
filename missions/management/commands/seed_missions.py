from decimal import Decimal
from django.core.management.base import BaseCommand
from missions.models import Mission


class Command(BaseCommand):
    help = "Seed default missions for testing purposes"

    def handle(self, *args, **options):
        missions_data = [
            {
                'description': 'Refer 10 users (L1 only)',
                'type': 'referral',
                'requirement': 10,
                'reward': Decimal('50000.00'),
                'reward_balance_type': 'balance',
                'is_active': True,
                'is_repeatable': False,
                'level': 1,
                'referral_levels': [1],
            },
            {
                'description': 'Refer 20 users (L1+L2)',
                'type': 'referral',
                'requirement': 20,
                'reward': Decimal('100000.00'),
                'reward_balance_type': 'balance',
                'is_active': True,
                'is_repeatable': False,
                'level': 2,
                'referral_levels': [1, 2],
            },
            {
                'description': '5 downlines have investments (L1 only)',
                'type': 'purchase',
                'requirement': 5,
                'reward': Decimal('75000.00'),
                'reward_balance_type': 'balance',
                'is_active': True,
                'is_repeatable': True,
                'level': 1,
                'referral_levels': [1],
            },
            {
                'description': '3 downlines claimed profit (service)',
                'type': 'service',
                'requirement': 3,
                'reward': Decimal('50000.00'),
                'reward_balance_type': 'balance_deposit',
                'is_active': True,
                'is_repeatable': True,
                'level': 1,
                'referral_levels': [1, 2, 3],
            },
            {
                'description': 'Refer 50 users (L1+L2+L3)',
                'type': 'referral',
                'requirement': 50,
                'reward': Decimal('300000.00'),
                'reward_balance_type': 'balance',
                'is_active': True,
                'is_repeatable': True,
                'level': 3,
                'referral_levels': [1, 2, 3],
            },
        ]

        created = 0
        updated = 0

        for data in missions_data:
            obj, exists = Mission.objects.get_or_create(
                description=data['description'],
                type=data['type'],
                defaults={
                    'requirement': data['requirement'],
                    'reward': data['reward'],
                    'reward_balance_type': data['reward_balance_type'],
                    'is_active': data['is_active'],
                    'is_repeatable': data['is_repeatable'],
                    'level': data['level'],
                    'referral_levels': data['referral_levels'],
                }
            )
            if exists:
                # Update fields in case they changed
                obj.requirement = data['requirement']
                obj.reward = data['reward']
                obj.reward_balance_type = data['reward_balance_type']
                obj.is_active = data['is_active']
                obj.is_repeatable = data['is_repeatable']
                obj.level = data['level']
                obj.referral_levels = data['referral_levels']
                obj.save()
                updated += 1
            else:
                created += 1

        self.stdout.write(self.style.SUCCESS(
            f"Seeded missions: created={created}, updated={updated}, total={Mission.objects.count()}"
        ))