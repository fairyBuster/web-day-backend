from django.core.management.base import BaseCommand
from products.models import Product
from decimal import Decimal

class Command(BaseCommand):
    help = 'Seed products data'

    def handle(self, *args, **kwargs):
        # Delete existing products
        Product.objects.all().delete()
        
        # Sample product data
        products = [
            {
                'name': 'Daily Investment Plan',
                'description': 'Short term investment plan with daily returns. Perfect for beginners.',
                'price': Decimal('100000.00'),
                'profit_rate': Decimal('5.0'),  # 5% per day
                'profit_type': 'percentage',
                'profit_method': 'manual',
                'duration': 24,  # 24 hours
                'balance_source': 'balance',
                'claim_reset_mode': 'at_00',
                'stock': 1000,
                'stock_enabled': True,
                'status': 1,
                'rebate_purchase_levels': 3,
                'rebate_profit_levels': 3,
                'rebate_settings': {
                    'purchase': {
                        'level1': 5,  # 5% dari harga produk
                        'level2': 3,
                        'level3': 2
                    },
                    'profit': {
                        'level1': 10,  # 10% dari profit
                        'level2': 5,
                        'level3': 3
                    }
                }
            },
            {
                'name': 'Weekly Growth Fund',
                'description': 'Medium term investment with weekly profit claims.',
                'price': Decimal('250000.00'),
                'profit_rate': Decimal('7.0'),  # 7% per week
                'profit_type': 'percentage',
                'profit_method': 'manual',
                'duration': 168,  # 7 days in hours
                'balance_source': 'balance',
                'claim_reset_mode': 'after_purchase',
                'stock': 500,
                'stock_enabled': True,
                'status': 1,
                'rebate_purchase_levels': 4,
                'rebate_profit_levels': 3,
                'rebate_settings': {
                    'purchase': {
                        'level1': 8,
                        'level2': 5,
                        'level3': 3,
                        'level4': 2
                    },
                    'profit': {
                        'level1': 12,
                        'level2': 6,
                        'level3': 4
                    }
                }
            },
            {
                'name': 'Monthly Premium Investment',
                'description': 'High yield monthly investment plan for serious investors.',
                'price': Decimal('500000.00'),
                'profit_rate': Decimal('10.0'),  # 10% per month
                'profit_type': 'percentage',
                'profit_method': 'manual',
                'duration': 720,  # 30 days in hours
                'balance_source': 'balance',
                'claim_reset_mode': 'after_purchase',
                'stock': 100,
                'stock_enabled': True,
                'status': 1,
                'rebate_purchase_levels': 5,
                'rebate_profit_levels': 4,
                'rebate_settings': {
                    'purchase': {
                        'level1': 10,
                        'level2': 7,
                        'level3': 5,
                        'level4': 3,
                        'level5': 2
                    },
                    'profit': {
                        'level1': 15,
                        'level2': 10,
                        'level3': 7,
                        'level4': 5
                    }
                }
            },
            {
                'name': 'Fixed Return Package',
                'description': 'Guaranteed fixed return investment package.',
                'price': Decimal('1000000.00'),
                'profit_rate': Decimal('50000.00'),  # Fixed Rp 50,000 per claim
                'profit_type': 'fixed',
                'profit_method': 'auto',
                'duration': 1440,  # 60 days in hours
                'balance_source': 'balance_deposit',
                'claim_reset_mode': 'at_00',
                'stock': 200,
                'stock_enabled': True,
                'status': 1,
                'rebate_purchase_levels': 3,
                'rebate_profit_levels': 3,
                'rebate_settings': {
                    'purchase': {
                        'level1': 3,
                        'level2': 2,
                        'level3': 1
                    },
                    'profit': {
                        'level1': 5000,  # Fixed amounts for profit sharing
                        'level2': 3000,
                        'level3': 2000
                    }
                }
            },
            {
                'name': 'VIP Investment Plan',
                'description': 'Exclusive investment plan for VIP members with high returns.',
                'price': Decimal('2000000.00'),
                'profit_rate': Decimal('15.0'),  # 15% per period
                'profit_type': 'percentage',
                'profit_method': 'manual',
                'duration': 168,  # 7 days in hours
                'balance_source': 'balance_deposit',
                'claim_reset_mode': 'after_purchase',
                'stock': 50,
                'stock_enabled': True,
                'status': 1,
                'rebate_purchase_levels': 5,
                'rebate_profit_levels': 5,
                'rebate_settings': {
                    'purchase': {
                        'level1': 15,
                        'level2': 10,
                        'level3': 7,
                        'level4': 5,
                        'level5': 3
                    },
                    'profit': {
                        'level1': 20,
                        'level2': 15,
                        'level3': 10,
                        'level4': 7,
                        'level5': 5
                    }
                }
            }
        ]
        
        # Create products
        for product_data in products:
            product = Product.objects.create(**product_data)
            self.stdout.write(self.style.SUCCESS(f'Created product: {product.name}'))
        
        self.stdout.write(self.style.SUCCESS(f'Successfully created {len(products)} products'))