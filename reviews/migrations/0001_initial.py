import django.db.models.deletion
import reviews.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Review",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("text", models.TextField(max_length=2000)),
                ("is_hidden", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="reviews",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["-id"],
            },
        ),
        migrations.CreateModel(
            name="ReviewImage",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "image",
                    models.ImageField(upload_to=reviews.models.review_image_upload_to),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "review",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="images",
                        to="reviews.review",
                    ),
                ),
            ],
            options={
                "ordering": ["id"],
            },
        ),
        migrations.CreateModel(
            name="ReviewLike",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "review",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="likes",
                        to="reviews.review",
                    ),
                ),
                (
                    "user",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="review_likes",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
        ),
        migrations.AddIndex(
            model_name="review",
            index=models.Index(
                fields=["created_at"], name="reviews_rev_created_bdcc91_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="review",
            index=models.Index(
                fields=["user", "created_at"], name="reviews_rev_user_id_35ef9b_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="reviewimage",
            index=models.Index(
                fields=["review", "id"], name="reviews_rev_review__20f243_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="reviewlike",
            index=models.Index(
                fields=["review", "created_at"], name="reviews_rev_review__f76e1d_idx"
            ),
        ),
        migrations.AddIndex(
            model_name="reviewlike",
            index=models.Index(
                fields=["user", "created_at"], name="reviews_rev_user_id_def31a_idx"
            ),
        ),
        migrations.AddConstraint(
            model_name="reviewlike",
            constraint=models.UniqueConstraint(
                fields=("review", "user"), name="uniq_review_like_review_user"
            ),
        ),
    ]
