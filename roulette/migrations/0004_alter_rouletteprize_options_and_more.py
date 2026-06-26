from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("roulette", "0003_seed_12_prizes_default_weights"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="rouletteprize",
            options={
                "ordering": ["sort_order", "id"],
                "verbose_name": "Roulette Prize",
                "verbose_name_plural": "Roulette Prizes",
            },
        ),
        migrations.AlterModelOptions(
            name="roulettesettings",
            options={
                "verbose_name": "Roulette Settings",
                "verbose_name_plural": "Roulette Settings",
            },
        ),
        migrations.AlterModelOptions(
            name="roulettespin",
            options={
                "ordering": ["-created_at", "-id"],
                "verbose_name": "Roulette Spin",
                "verbose_name_plural": "Roulette Spins",
            },
        ),
        migrations.AlterModelOptions(
            name="rouletteticketledger",
            options={
                "ordering": ["-created_at", "-id"],
                "verbose_name": "Roulette Ticket Ledger",
                "verbose_name_plural": "Roulette Ticket Ledgers",
            },
        ),
        migrations.AlterModelOptions(
            name="rouletteticketwallet",
            options={
                "verbose_name": "Roulette Ticket Wallet",
                "verbose_name_plural": "Roulette Ticket Wallets",
            },
        ),
        migrations.AlterField(
            model_name="rouletteprize",
            name="amount",
            field=models.DecimalField(decimal_places=2, default=0, help_text="Jumlah hadiah. Jika prize_type=NONE, nilai ini diabaikan.", max_digits=15),
        ),
        migrations.AlterField(
            model_name="rouletteprize",
            name="is_active",
            field=models.BooleanField(default=True, help_text="Jika OFF, hadiah tidak ikut undian."),
        ),
        migrations.AlterField(
            model_name="rouletteprize",
            name="prize_type",
            field=models.CharField(choices=[("BALANCE", "Balance"), ("BALANCE_DEPOSIT", "Balance Deposit"), ("NONE", "None")], default="BALANCE", help_text="BALANCE/BALANCE_DEPOSIT akan mengkredit saldo user. NONE berarti zonk (tanpa hadiah).", max_length=20),
        ),
        migrations.AlterField(
            model_name="rouletteprize",
            name="sort_order",
            field=models.PositiveSmallIntegerField(default=0, help_text="Urutan tampilan hadiah di aplikasi (lebih kecil tampil lebih dulu)."),
        ),
        migrations.AlterField(
            model_name="rouletteprize",
            name="weight",
            field=models.PositiveIntegerField(default=0, help_text="Bobot peluang menang. Peluang = weight / total_weight. Contoh: zonk=90, Rp1000=10."),
        ),
        migrations.AlterField(
            model_name="roulettesettings",
            name="is_active",
            field=models.BooleanField(default=True, help_text="Jika OFF, fitur roulette tidak bisa dipakai user."),
        ),
        migrations.AlterField(
            model_name="roulettesettings",
            name="ticket_cost",
            field=models.PositiveIntegerField(default=1, help_text="Biaya tiket untuk 1x spin."),
        ),
        migrations.AlterField(
            model_name="roulettesettings",
            name="tickets_per_level1_purchase",
            field=models.PositiveIntegerField(default=1, help_text="Jumlah tiket yang didapat upline saat downline level-1 membeli produk."),
        ),
        migrations.AlterField(
            model_name="rouletteticketledger",
            name="delta",
            field=models.IntegerField(help_text="Perubahan tiket (+ masuk, - keluar)."),
        ),
        migrations.AlterField(
            model_name="rouletteticketwallet",
            name="balance",
            field=models.PositiveIntegerField(default=0, help_text="Jumlah tiket roulette milik user."),
        ),
    ]

