from decimal import Decimal
from django.core.management.base import BaseCommand

from banks.models import Bank
from withdrawal.integrations.jayapay_ph_banks import JAYAPAY_PH_PAYOUT_BANKS


class Command(BaseCommand):
    help = "Seed Jayapay Philippines pay-out bank codes into Bank table (currency_code=PHP)"

    def handle(self, *args, **options):
        created = 0
        updated = 0

        for item in (JAYAPAY_PH_PAYOUT_BANKS or []):
            code = (item.get("bankCode") or "").strip()
            name = (item.get("bankName") or "").strip() or code
            if not code:
                continue

            obj, was_created = Bank.objects.get_or_create(
                code=code,
                defaults={
                    "name": name,
                    "currency_code": "PHP",
                    "is_active": True,
                    "logo": "",
                    "min_withdrawal": Decimal("0"),
                    "max_withdrawal": Decimal("0"),
                    "withdrawal_fee": Decimal("0"),
                    "withdrawal_fee_fixed": Decimal("0"),
                    "processing_time": 1,
                },
            )

            if was_created:
                created += 1
                continue

            changed = False
            if obj.name != name:
                obj.name = name
                changed = True
            if obj.currency_code != "PHP":
                obj.currency_code = "PHP"
                changed = True
            if not obj.is_active:
                obj.is_active = True
                changed = True
            if changed:
                obj.save(update_fields=["name", "currency_code", "is_active", "updated_at"])
                updated += 1

        self.stdout.write(self.style.SUCCESS(f"Seed PH banks done: created={created}, updated={updated}"))

