from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0019_merge_20260216_0102"),
    ]

    operations = [
        migrations.AddField(
            model_name="generalsetting",
            name="require_withdraw_pin_on_purchase",
            field=models.BooleanField(
                default=False,
            ),
        ),
    ]

