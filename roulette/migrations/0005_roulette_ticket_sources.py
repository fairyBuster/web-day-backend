from django.db import migrations, models
from django.db.models import Q


class Migration(migrations.Migration):

    dependencies = [
        ("roulette", "0004_alter_rouletteprize_options_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="roulettesettings",
            name="grant_tickets_from_level1_purchase",
            field=models.BooleanField(
                default=True,
                help_text="Jika ON, upline mendapat tiket saat downline level-1 membeli produk.",
            ),
        ),
        migrations.AddField(
            model_name="roulettesettings",
            name="grant_tickets_from_self_deposit",
            field=models.BooleanField(
                default=False,
                help_text="Jika ON, user mendapat tiket saat depositnya berstatus COMPLETED.",
            ),
        ),
        migrations.AddField(
            model_name="roulettesettings",
            name="tickets_per_completed_deposit",
            field=models.PositiveIntegerField(
                default=0,
                help_text="Jumlah tiket yang didapat user untuk setiap deposit COMPLETED (jika fitur deposit diaktifkan).",
            ),
        ),
        migrations.AddField(
            model_name="roulettesettings",
            name="min_deposit_amount_for_tickets",
            field=models.DecimalField(
                decimal_places=2,
                default=0,
                help_text="Minimum amount deposit agar dapat tiket (0 = tanpa minimum).",
                max_digits=15,
            ),
        ),
        migrations.AlterField(
            model_name="rouletteticketledger",
            name="reason",
            field=models.CharField(
                choices=[
                    ("LEVEL1_PURCHASE", "Level 1 Purchase"),
                    ("SELF_DEPOSIT", "Self Deposit"),
                    ("SPIN_COST", "Spin Cost"),
                    ("ADMIN_ADJUST", "Admin Adjust"),
                ],
                max_length=30,
            ),
        ),
        migrations.AddConstraint(
            model_name="rouletteticketledger",
            constraint=models.UniqueConstraint(
                fields=("source_transaction",),
                condition=Q(reason="SELF_DEPOSIT"),
                name="uniq_roulette_ticket_source_tx_self_deposit",
            ),
        ),
    ]

