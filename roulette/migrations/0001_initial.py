import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("products", "0024_alter_transaction_type"),
    ]

    operations = [
        migrations.CreateModel(
            name="RoulettePrize",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=120)),
                ("description", models.TextField(blank=True)),
                ("prize_type", models.CharField(choices=[("BALANCE", "Balance"), ("BALANCE_DEPOSIT", "Balance Deposit"), ("NONE", "None")], default="BALANCE", max_length=20)),
                ("amount", models.DecimalField(decimal_places=2, default=0, max_digits=15)),
                ("weight", models.PositiveIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "roulette_prizes",
                "ordering": ["sort_order", "id"],
            },
        ),
        migrations.CreateModel(
            name="RouletteSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=True)),
                ("tickets_per_level1_purchase", models.PositiveIntegerField(default=1)),
                ("ticket_cost", models.PositiveIntegerField(default=1)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "roulette_settings",
            },
        ),
        migrations.CreateModel(
            name="RouletteTicketWallet",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("balance", models.PositiveIntegerField(default=0)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="roulette_wallet", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "roulette_ticket_wallets",
            },
        ),
        migrations.CreateModel(
            name="RouletteTicketLedger",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("delta", models.IntegerField()),
                ("reason", models.CharField(choices=[("LEVEL1_PURCHASE", "Level 1 Purchase"), ("SPIN_COST", "Spin Cost"), ("ADMIN_ADJUST", "Admin Adjust")], max_length=30)),
                ("created_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("source_transaction", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="roulette_ticket_ledgers", to="products.transaction")),
                ("source_user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="roulette_ticket_sources", to=settings.AUTH_USER_MODEL)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="roulette_ticket_ledgers", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "roulette_ticket_ledgers",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.CreateModel(
            name="RouletteSpin",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("prize_type", models.CharField(default="NONE", max_length=20)),
                ("prize_amount", models.DecimalField(decimal_places=2, default="0.00", max_digits=15)),
                ("created_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("prize", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="spins", to="roulette.rouletteprize")),
                ("transaction", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="roulette_spins", to="products.transaction")),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name="roulette_spins", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "roulette_spins",
                "ordering": ["-created_at", "-id"],
            },
        ),
        migrations.AddConstraint(
            model_name="rouletteticketledger",
            constraint=models.UniqueConstraint(condition=models.Q(("reason", "LEVEL1_PURCHASE")), fields=("source_transaction",), name="uniq_roulette_ticket_source_tx_level1"),
        ),
    ]

