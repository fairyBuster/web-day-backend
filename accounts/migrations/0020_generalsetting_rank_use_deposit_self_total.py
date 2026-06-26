from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0019_merge_20260216_0102"),
    ]

    operations = [
        migrations.AddField(
            model_name="generalsetting",
            name="rank_use_deposit_self_total",
            field=models.BooleanField(default=False, help_text="Jika ON, total deposit sendiri (COMPLETED) digunakan untuk rank"),
        ),
    ]
