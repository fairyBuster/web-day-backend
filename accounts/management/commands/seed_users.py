from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from decimal import Decimal
import random

User = get_user_model()

class Command(BaseCommand):
    help = 'Seed users data'

    def handle(self, *args, **kwargs):
        # Delete existing users except superuser
        User.objects.filter(is_superuser=False).delete()
        
        # Create users with referral relationships
        users_data = [
            {
                'username': 'user1',
                'email': 'user1@example.com',
                'phone': '085100000001',
                'full_name': 'User One',
                'balance': Decimal('10000000.00'),
                'balance_deposit': Decimal('50000000.00'),
                'rank': 'GOLD',
                'is_account_non_expired': True,
                'is_account_non_locked': True,
                'is_credentials_non_expired': True,
                'is_enabled': True,
                'banned_status': False
            },
            {
                'username': 'user2',
                'email': 'user2@example.com',
                'phone': '085100000002',
                'full_name': 'User Two',
                'balance': Decimal('5000000.00'),
                'balance_deposit': Decimal('25000000.00'),
                'rank': 'SILVER',
                'referral_by': 'user1',
                'is_account_non_expired': True,
                'is_account_non_locked': True,
                'is_credentials_non_expired': True,
                'is_enabled': True,
                'banned_status': False
            },
            {
                'username': 'user3',
                'email': 'user3@example.com',
                'phone': '085100000003',
                'full_name': 'User Three',
                'balance': Decimal('2000000.00'),
                'balance_deposit': Decimal('10000000.00'),
                'rank': 'BRONZE',
                'referral_by': 'user1',
                'is_account_non_expired': True,
                'is_account_non_locked': True,
                'is_credentials_non_expired': True,
                'is_enabled': True,
                'banned_status': False
            },
            {
                'username': 'user4',
                'email': 'user4@example.com',
                'phone': '085100000004',
                'full_name': 'User Four',
                'balance': Decimal('1000000.00'),
                'balance_deposit': Decimal('5000000.00'),
                'rank': 'BRONZE',
                'referral_by': 'user2',
                'is_account_non_expired': True,
                'is_account_non_locked': True,
                'is_credentials_non_expired': True,
                'is_enabled': True,
                'banned_status': False
            },
            {
                'username': 'user5',
                'email': 'user5@example.com',
                'phone': '085100000005',
                'full_name': 'User Five',
                'balance': Decimal('500000.00'),
                'balance_deposit': Decimal('2500000.00'),
                'rank': 'BRONZE',
                'referral_by': 'user2',
                'is_account_non_expired': True,
                'is_account_non_locked': True,
                'is_credentials_non_expired': True,
                'is_enabled': True,
                'banned_status': False
            },
            # Banned user example
            {
                'username': 'banned_user',
                'email': 'banned@example.com',
                'phone': '085100000006',
                'full_name': 'Banned User',
                'balance': Decimal('0.00'),
                'balance_deposit': Decimal('0.00'),
                'rank': 'BRONZE',
                'referral_by': 'user1',
                'is_account_non_expired': False,
                'is_account_non_locked': False,
                'is_credentials_non_expired': False,
                'is_enabled': False,
                'banned_status': True
            }
        ]
        
        # First pass: Create all users without referrals
        created_users = {}
        for data in users_data:
            referral_by = data.pop('referral_by', None)
            user = User.objects.create_user(
                password='password123',
                **data
            )
            created_users[user.username] = {'user': user, 'referral_by': referral_by}
            self.stdout.write(f'Created user: {user.username} ({user.phone})')
        
        # Second pass: Set up referral relationships
        for username, info in created_users.items():
            if info['referral_by']:
                user = info['user']
                referrer = created_users[info['referral_by']]['user']
                user.referral_by = referrer
                user.save()
                self.stdout.write(f'Set referral for {user.username} to {referrer.username}')
        
        self.stdout.write(self.style.SUCCESS(f'Successfully created {len(users_data)} users'))