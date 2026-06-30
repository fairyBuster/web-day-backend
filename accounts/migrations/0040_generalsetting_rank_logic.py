from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0039_user_balance_cashback_and_generalsetting_deposit_cashback"),
    ]

    operations = [
        migrations.AddField(
            model_name="generalsetting",
            name="rank_logic",
            field=models.CharField(
                choices=[
                    ("OR", "Salah satu syarat aktif terpenuhi"),
                    ("AND", "Semua syarat aktif harus terpenuhi"),
                ],
                default="OR",
                help_text="Tentukan apakah evaluasi rank memakai logika OR atau AND untuk basis yang aktif.",
                max_length=10,
            ),
        ),
    ]

