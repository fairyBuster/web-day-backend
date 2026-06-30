from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0040_generalsetting_rank_logic"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="generalsetting",
            name="rank_basis",
        ),
    ]

