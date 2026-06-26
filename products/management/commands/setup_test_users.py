from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from decimal import Decimal

User = get_user_model()

class Command(BaseCommand):
    help = 'Setup test users with referral relationships for testing purchase limits and rebate commissions'

    def handle(self, *args, **kwargs):
        # Create referral hierarchy for testing
        # Level 1 (Top): parent_user
        # Level 2: child_user1 (upline: parent_user)
        # Level 3: child_user2 (upline: child_user1)
        # Level 4: test_user (upline: child_user2) - This will be our main test user
        
        # Create parent user (top of hierarchy)
        parent_user, created = User.objects.get_or_create(
            phone='08123456789',
            defaults={
                'username': 'parent_user',
                'email': 'parent@example.com',
                'balance': Decimal('10000000.00'),  # 10 million balance
                'balance_deposit': Decimal('5000000.00'),  # 5 million deposit balance
                'is_active': True
            }
        )
        if created:
            parent_user.set_password('password123')
            parent_user.save()
            self.stdout.write(self.style.SUCCESS(f'Created parent user: {parent_user.phone}'))
        else:
            # Update balance for testing
            parent_user.balance = Decimal('10000000.00')
            parent_user.balance_deposit = Decimal('5000000.00')
            parent_user.save()
            self.stdout.write(self.style.WARNING(f'Updated existing parent user: {parent_user.phone}'))

        # Create child user 1 (Level 2)
        child_user1, created = User.objects.get_or_create(
            phone='08123456790',
            defaults={
                'username': 'child_user1',
                'email': 'child1@example.com',
                'balance': Decimal('5000000.00'),
                'balance_deposit': Decimal('3000000.00'),
                'referral_by': parent_user,  # Set referral relationship
                'is_active': True
            }
        )
        if created:
            child_user1.set_password('password123')
            child_user1.save()
            self.stdout.write(self.style.SUCCESS(f'Created child user 1: {child_user1.phone}'))
        else:
            child_user1.balance = Decimal('5000000.00')
            child_user1.balance_deposit = Decimal('3000000.00')
            child_user1.referral_by = parent_user
            child_user1.save()
            self.stdout.write(self.style.WARNING(f'Updated existing child user 1: {child_user1.phone}'))

        # Create child user 2 (Level 3)
        child_user2, created = User.objects.get_or_create(
            phone='08123456791',
            defaults={
                'username': 'child_user2',
                'email': 'child2@example.com',
                'balance': Decimal('3000000.00'),
                'balance_deposit': Decimal('2000000.00'),
                'referral_by': child_user1,  # Set referral relationship
                'is_active': True
            }
        )
        if created:
            child_user2.set_password('password123')
            child_user2.save()
            self.stdout.write(self.style.SUCCESS(f'Created child user 2: {child_user2.phone}'))
        else:
            child_user2.balance = Decimal('3000000.00')
            child_user2.balance_deposit = Decimal('2000000.00')
            child_user2.referral_by = child_user1
            child_user2.save()
            self.stdout.write(self.style.WARNING(f'Updated existing child user 2: {child_user2.phone}'))

        # Create test user (Level 4) - This will be our main testing user
        test_user, created = User.objects.get_or_create(
            phone='08123456792',
            defaults={
                'username': 'test_user',
                'email': 'test@example.com',
                'balance': Decimal('2000000.00'),
                'balance_deposit': Decimal('1000000.00'),
                'referral_by': child_user2,  # Set referral relationship
                'is_active': True
            }
        )
        if created:
            test_user.set_password('password123')
            test_user.save()
            self.stdout.write(self.style.SUCCESS(f'Created test user: {test_user.phone}'))
        else:
            test_user.balance = Decimal('2000000.00')
            test_user.balance_deposit = Decimal('1000000.00')
            test_user.referral_by = child_user2
            test_user.save()
            self.stdout.write(self.style.WARNING(f'Updated existing test user: {test_user.phone}'))

        # Display the referral hierarchy
        self.stdout.write(self.style.SUCCESS('\n=== REFERRAL HIERARCHY ==='))
        self.stdout.write(f'Level 1: {parent_user.phone} (parent_user)')
        self.stdout.write(f'Level 2: {child_user1.phone} (child_user1) -> upline: {parent_user.phone}')
        self.stdout.write(f'Level 3: {child_user2.phone} (child_user2) -> upline: {child_user1.phone}')
        self.stdout.write(f'Level 4: {test_user.phone} (test_user) -> upline: {child_user2.phone}')
        
        self.stdout.write(self.style.SUCCESS('\n=== TESTING INSTRUCTIONS ==='))
        self.stdout.write('1. Use test_user (08123456792) to make purchases')
        self.stdout.write('2. Products with purchase_limit=1 should reject second purchase attempts')
        self.stdout.write('3. Rebate commissions should be distributed to upline users')
        self.stdout.write('4. Login credentials for all users: password123')
        
        self.stdout.write(self.style.SUCCESS('\n=== API TESTING ==='))
        self.stdout.write('Login as test_user:')
        self.stdout.write('POST /api/auth/login/')
        self.stdout.write('{"phone": "08123456792", "password": "password123"}')
        self.stdout.write('')
        self.stdout.write('Make a purchase:')
        self.stdout.write('POST /api/products/purchase/')
        self.stdout.write('{"product_id": 1, "quantity": 1}')
        self.stdout.write('')
        self.stdout.write('Try to purchase the same product again (should fail if purchase_limit=1)')