from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0021_merge_20260306_1412"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="balance_hold",
            field=models.DecimalField(max_digits=15, decimal_places=2, default=0),
        ),
    ]
