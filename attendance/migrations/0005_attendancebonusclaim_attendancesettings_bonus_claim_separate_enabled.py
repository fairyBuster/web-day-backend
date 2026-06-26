import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("attendance", "0004_attendancesettings_daily_cycle_days_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="attendancesettings",
            name="bonus_claim_separate_enabled",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="AttendanceBonusClaim",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("bonus_type", models.CharField(choices=[("cycle", "Cycle Bonus"), ("streak_7", "Streak 7 Bonus"), ("streak_30", "Streak 30 Bonus")], max_length=20)),
                ("claimed_for_streak", models.IntegerField()),
                ("cycle_index", models.IntegerField(blank=True, null=True)),
                ("amount", models.DecimalField(decimal_places=2, default=0, max_digits=15)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "db_table": "attendance_bonus_claims",
                "ordering": ["-created_at"],
            },
        ),
        migrations.AddConstraint(
            model_name="attendancebonusclaim",
            constraint=models.UniqueConstraint(condition=models.Q(("bonus_type", "cycle")), fields=("user", "bonus_type", "cycle_index"), name="uniq_att_bonus_cycle"),
        ),
        migrations.AddConstraint(
            model_name="attendancebonusclaim",
            constraint=models.UniqueConstraint(condition=models.Q(("bonus_type__in", ["streak_7", "streak_30"])), fields=("user", "bonus_type"), name="uniq_att_bonus_streak"),
        ),
    ]
