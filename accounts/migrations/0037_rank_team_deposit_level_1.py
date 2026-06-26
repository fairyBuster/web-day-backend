from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0036_delete_currencyrate_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="generalsetting",
            name="rank_use_team_deposit_level_1_total",
            field=models.BooleanField(
                default=False,
                help_text="Jika ON, total deposit tim level 1 saja (downline langsung, status COMPLETED) digunakan untuk rank",
            ),
        ),
        migrations.AddField(
            model_name="ranklevel",
            name="team_deposit_level_1_total_required",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=15),
        ),
        migrations.AlterField(
            model_name="generalsetting",
            name="rank_basis",
            field=models.CharField(
                choices=[
                    ("missions", "Berdasarkan misi selesai"),
                    ("downlines_total", "Jumlah anggota downline"),
                    ("downlines_active", "Jumlah downline aktif"),
                    ("deposit_self_total", "Jumlah deposit sendiri"),
                    ("team_deposit_level_1_total", "Jumlah deposit tim level 1"),
                ],
                default="missions",
                help_text="Basis perhitungan rank: misi selesai, jumlah downline, atau downline aktif",
                max_length=30,
            ),
        ),
    ]
