from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("products", "0028_product_golongan"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProfitHolidaySettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("is_active", models.BooleanField(default=False)),
                ("disable_monday", models.BooleanField(default=False)),
                ("disable_tuesday", models.BooleanField(default=False)),
                ("disable_wednesday", models.BooleanField(default=False)),
                ("disable_thursday", models.BooleanField(default=False)),
                ("disable_friday", models.BooleanField(default=False)),
                ("disable_saturday", models.BooleanField(default=False)),
                ("disable_sunday", models.BooleanField(default=False)),
                ("disabled_dates", models.JSONField(blank=True, default=list, help_text='Daftar tanggal libur format YYYY-MM-DD. Contoh: ["2026-04-10", "2026-05-01"]')),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "db_table": "profit_holiday_settings",
                "verbose_name": "Profit Holiday Settings",
                "verbose_name_plural": "Profit Holiday Settings",
            },
        ),
        migrations.AlterField(
            model_name="investment",
            name="profit_method",
            field=models.CharField(
                choices=[
                    ("manual", "Manual"),
                    ("auto", "Automatic"),
                    ("hold", "Hold Until Maturity"),
                ],
                max_length=20,
            ),
        ),
    ]

