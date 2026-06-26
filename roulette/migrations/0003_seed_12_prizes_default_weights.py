from decimal import Decimal
from django.db import migrations


OLD_SEED_NAMES = {
    "Zonk",
    "Rp 1.000",
    "Rp 5.000",
    "Rp 20.000",
    "Rp 100.000",
}


def seed_12_prizes_default_weights(apps, schema_editor):
    RouletteSettings = apps.get_model("roulette", "RouletteSettings")
    RoulettePrize = apps.get_model("roulette", "RoulettePrize")

    if not RouletteSettings.objects.exists():
        RouletteSettings.objects.create(
            is_active=True,
            tickets_per_level1_purchase=1,
            ticket_cost=1,
        )

    existing_count = RoulettePrize.objects.count()
    if existing_count == 0:
        should_seed = True
    else:
        existing_names = set(RoulettePrize.objects.values_list("name", flat=True))
        should_seed = existing_count == 5 and existing_names == OLD_SEED_NAMES

    if not should_seed:
        return

    RoulettePrize.objects.all().delete()

    prizes = [
        {
            "name": "Zonk 1",
            "description": "Belum beruntung, coba lagi",
            "prize_type": "NONE",
            "amount": Decimal("0.00"),
            "weight": 300,
            "sort_order": 1,
        },
        {
            "name": "Zonk 2",
            "description": "Belum beruntung, coba lagi",
            "prize_type": "NONE",
            "amount": Decimal("0.00"),
            "weight": 300,
            "sort_order": 2,
        },
        {
            "name": "Zonk 3",
            "description": "Belum beruntung, coba lagi",
            "prize_type": "NONE",
            "amount": Decimal("0.00"),
            "weight": 300,
            "sort_order": 3,
        },
        {
            "name": "Rp 1.000",
            "description": "Bonus saldo Rp 1.000",
            "prize_type": "BALANCE",
            "amount": Decimal("1000.00"),
            "weight": 25,
            "sort_order": 4,
        },
        {
            "name": "Rp 2.000",
            "description": "Bonus saldo Rp 2.000",
            "prize_type": "BALANCE",
            "amount": Decimal("2000.00"),
            "weight": 20,
            "sort_order": 5,
        },
        {
            "name": "Rp 3.000",
            "description": "Bonus saldo Rp 3.000",
            "prize_type": "BALANCE",
            "amount": Decimal("3000.00"),
            "weight": 15,
            "sort_order": 6,
        },
        {
            "name": "Rp 5.000",
            "description": "Bonus saldo Rp 5.000",
            "prize_type": "BALANCE",
            "amount": Decimal("5000.00"),
            "weight": 12,
            "sort_order": 7,
        },
        {
            "name": "Rp 10.000",
            "description": "Bonus saldo Rp 10.000",
            "prize_type": "BALANCE",
            "amount": Decimal("10000.00"),
            "weight": 10,
            "sort_order": 8,
        },
        {
            "name": "Rp 20.000",
            "description": "Bonus saldo Rp 20.000",
            "prize_type": "BALANCE",
            "amount": Decimal("20000.00"),
            "weight": 7,
            "sort_order": 9,
        },
        {
            "name": "Rp 50.000",
            "description": "Bonus saldo Rp 50.000",
            "prize_type": "BALANCE",
            "amount": Decimal("50000.00"),
            "weight": 5,
            "sort_order": 10,
        },
        {
            "name": "Rp 100.000",
            "description": "Bonus saldo Rp 100.000",
            "prize_type": "BALANCE",
            "amount": Decimal("100000.00"),
            "weight": 4,
            "sort_order": 11,
        },
        {
            "name": "Rp 200.000",
            "description": "Bonus saldo Rp 200.000",
            "prize_type": "BALANCE",
            "amount": Decimal("200000.00"),
            "weight": 2,
            "sort_order": 12,
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
        ("roulette", "0002_seed_default_roulette_data"),
    ]

    operations = [
        migrations.RunPython(seed_12_prizes_default_weights, migrations.RunPython.noop),
    ]

