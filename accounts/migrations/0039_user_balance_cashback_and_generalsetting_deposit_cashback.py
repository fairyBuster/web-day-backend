from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0038_user_telegram"),
    ]

    operations = [
        migrations.AddField(
            model_name="generalsetting",
            name="deposit_cashback_enabled",
            field=models.BooleanField(
                default=True,
                help_text="Jika ON, user mendapat cashback dari deposit sendiri yang berstatus COMPLETED.",
            ),
        ),
        migrations.AddField(
            model_name="generalsetting",
            name="deposit_cashback_percent",
            field=models.DecimalField(
                decimal_places=2,
                default=1,
                help_text="Persentase cashback dari deposit sendiri. Contoh: 1 = 1%.",
                max_digits=5,
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="balance_cashback",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=15),
        ),
    ]

