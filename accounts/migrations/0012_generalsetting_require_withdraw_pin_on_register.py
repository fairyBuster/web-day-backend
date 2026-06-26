from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0011_useraddress"),
    ]

    operations = [
        migrations.AddField(
            model_name="generalsetting",
            name="require_withdraw_pin_on_register",
            field=models.BooleanField(
                default=False,
            ),
        ),
    ]

