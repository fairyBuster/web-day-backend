from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0041_remove_generalsetting_rank_basis"),
    ]

    operations = [
        migrations.AddField(
            model_name="generalsetting",
            name="active_member_logic",
            field=models.CharField(
                choices=[
                    ("OR", "Aktif jika salah satu kondisi terpenuhi"),
                    ("AND", "Aktif jika semua kondisi terpenuhi"),
                ],
                default="OR",
                help_text="Logika penentuan member aktif berdasarkan kondisi yang diaktifkan di bawah.",
                max_length=10,
            ),
        ),
        migrations.AddField(
            model_name="generalsetting",
            name="active_member_use_deposit_completed",
            field=models.BooleanField(
                default=True,
                help_text="Jika ON, member dianggap aktif jika punya deposit status COMPLETED.",
            ),
        ),
        migrations.AddField(
            model_name="generalsetting",
            name="active_member_use_active_investment",
            field=models.BooleanField(
                default=False,
                help_text="Jika ON, member dianggap aktif jika punya investasi status ACTIVE dari product yang qualify_as_active_investment=ON.",
            ),
        ),
    ]

