from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="review",
            name="is_approved",
            field=models.BooleanField(default=False),
        ),
        migrations.AddIndex(
            model_name="review",
            index=models.Index(
                fields=["is_approved", "is_hidden", "created_at"],
                name="reviews_rev_is_ap_7bb337_idx",
            ),
        ),
    ]
