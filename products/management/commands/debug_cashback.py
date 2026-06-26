from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from products.models import Transaction
from products.serializers import ClaimCashbackSerializer

class Command(BaseCommand):
    help = "Debug cashback claim eligibility for a user"

    def add_arguments(self, parser):
        parser.add_argument('--phone', required=True, help='User phone number (e.g., 0815xxxxxx)')
        parser.add_argument('--trx', required=False, help='Specific purchase transaction ID to check')

    def handle(self, *args, **options):
        phone = options['phone']
        trx = options.get('trx')
        User = get_user_model()

        try:
            user = User.objects.get(phone=phone)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"User not found with phone {phone}"))
            return

        self.stdout.write(self.style.SUCCESS(f"User: id={user.id} phone={user.phone} balance={user.balance} deposit={user.balance_deposit}"))

        purchases = Transaction.objects.filter(user=user, type='INVESTMENTS', status='COMPLETED')
        if trx:
            purchases = purchases.filter(trx_id=trx)
            if not purchases.exists():
                self.stdout.write(self.style.WARNING(f"No completed purchase transaction with trx_id={trx}"))
                return

        self.stdout.write(f"Completed purchases: {purchases.count()}")

        for t in purchases:
            product = t.product
            pname = product.name if product else 'None'
            cashback_enabled = getattr(product, 'cashback_enabled', False)
            cashback_percentage = getattr(product, 'cashback_percentage', 0)
            self.stdout.write(f"- TRX {t.trx_id} product={pname} cashback_enabled={cashback_enabled} percentage={cashback_percentage} amount={t.amount}")

            existing = Transaction.objects.filter(user=user, product=product, type='CASHBACK')
            self.stdout.write(f"  Existing CASHBACK count for product: {existing.count()}")
            for cb in existing:
                related = cb.related_transaction.trx_id if cb.related_transaction else None
                self.stdout.write(f"    CASHBACK trx={cb.trx_id} amount={cb.amount} related={related}")

            # Run serializer validation to see exact errors
            data = {'transaction_id': t.trx_id}
            # Minimal request-like object for serializer context
            request_like = type('Req', (object,), {'user': user})()
            serializer = ClaimCashbackSerializer(data=data, context={'request': request_like})
            is_valid = serializer.is_valid()
            self.stdout.write(f"  Serializer is_valid={is_valid}")
            if not is_valid:
                self.stdout.write(f"  Errors={serializer.errors}")
            else:
                self.stdout.write(self.style.SUCCESS("  Eligible to claim cashback for this transaction."))