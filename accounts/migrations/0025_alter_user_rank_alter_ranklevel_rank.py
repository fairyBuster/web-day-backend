from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0024_generalsetting_frontend_url"),
    ]

    operations = [
        migrations.AlterField(
            model_name="user",
            name="rank",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AlterField(
            model_name="ranklevel",
            name="rank",
            field=models.PositiveSmallIntegerField(unique=True),
        ),
    ]

