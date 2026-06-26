from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("accounts", "0025_alter_user_rank_alter_ranklevel_rank"),
    ]

    operations = [
        migrations.AddField(
            model_name="ranklevel",
            name="downlines_total_required",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="ranklevel",
            name="downlines_active_required",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="ranklevel",
            name="deposit_self_total_required",
            field=models.DecimalField(decimal_places=2, default=0, max_digits=15),
        ),
    ]

