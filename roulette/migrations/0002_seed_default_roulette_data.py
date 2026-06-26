from decimal import Decimal
from django.db import migrations


def seed_default_roulette_data(apps, schema_editor):
    RouletteSettings = apps.get_model("roulette", "RouletteSettings")
    RoulettePrize = apps.get_model("roulette", "RoulettePrize")

    if not RouletteSettings.objects.exists():
        RouletteSettings.objects.create(
            is_active=True,
            tickets_per_level1_purchase=1,
            ticket_cost=1,
        )

    if RoulettePrize.objects.exists():
        return

    prizes = [
        {
            "name": "Zonk",
            "description": "Belum beruntung, coba lagi",
            "prize_type": "NONE",
            "amount": Decimal("0.00"),
            "weight": 600,
            "sort_order": 1,
        },
        {
            "name": "Rp 1.000",
            "description": "Bonus saldo Rp 1.000",
            "prize_type": "BALANCE",
            "amount": Decimal("1000.00"),
            "weight": 250,
            "sort_order": 2,
        },
        {
            "name": "Rp 5.000",
            "description": "Bonus saldo Rp 5.000",
            "prize_type": "BALANCE",
            "amount": Decimal("5000.00"),
            "weight": 100,
            "sort_order": 3,
        },
        {
            "name": "Rp 20.000",
            "description": "Bonus saldo Rp 20.000",
            "prize_type": "BALANCE",
            "amount": Decimal("20000.00"),
            "weight": 40,
            "sort_order": 4,
        },
        {
            "name": "Rp 100.000",
            "description": "Bonus saldo Rp 100.000",
            "prize_type": "BALANCE",
            "amount": Decimal("100000.00"),
            "weight": 10,
            "sort_order": 5,
        },
    ]

    for p in prizes:
        RoulettePrize.objects.create(
            name=p["name"],
            description=p["description"],
            prize_type=p["prize_type"],
            amount=p["amount"],
            weight=p["weight"],
            is_active=True,
            sort_order=p["sort_order"],
        )


class Migration(migrations.Migration):
    dependencies = [
        ("roulette", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed_default_roulette_data, migrations.RunPython.noop),
    ]

