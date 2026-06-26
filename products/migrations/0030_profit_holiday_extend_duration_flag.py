from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0029_profit_holiday_settings_and_alter_investment_profit_method"),
    ]

    operations = [
        migrations.AddField(
            model_name="profitholidaysettings",
            name="extend_duration_on_holidays",
            field=models.BooleanField(
                default=False,
                help_text="Jika ON, hari libur tidak mengurangi durasi investasi (siklus bergeser, tidak hangus)",
            ),
        ),
    ]
