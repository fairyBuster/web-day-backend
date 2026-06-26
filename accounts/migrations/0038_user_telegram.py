from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0037_rank_team_deposit_level_1"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="telegram",
            field=models.CharField(blank=True, default="", max_length=255),
        ),
    ]
