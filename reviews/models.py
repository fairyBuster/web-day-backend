import os
import uuid

from django.conf import settings
from django.db import models


def review_image_upload_to(instance, filename: str) -> str:
    _, ext = os.path.splitext(filename or "")
    ext = (ext or "").lower()
    if ext not in {".jpg", ".jpeg", ".png", ".webp"}:
        ext = ".jpg"
    review_id = getattr(instance.review, "id", None) or "new"
    return f"reviews/{review_id}/{uuid.uuid4().hex}{ext}"


class Review(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews"
    )
    text = models.TextField(max_length=2000)
    is_approved = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-id"]
        indexes = [
            models.Index(fields=["created_at"]),
            models.Index(fields=["user", "created_at"]),
            models.Index(
                fields=["is_approved", "is_hidden", "created_at"],
                name="reviews_rev_is_ap_7bb337_idx",
            ),
        ]

    def __str__(self) -> str:
        return f"Review#{self.id} by {self.user_id}"


class ReviewImage(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to=review_image_upload_to)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["review", "id"])]

    def __str__(self) -> str:
        return f"ReviewImage#{self.id} review={self.review_id}"


class ReviewLike(models.Model):
    review = models.ForeignKey(Review, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="review_likes"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["review", "user"], name="uniq_review_like_review_user"
            )
        ]
        indexes = [
            models.Index(fields=["review", "created_at"]),
            models.Index(fields=["user", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"ReviewLike review={self.review_id} user={self.user_id}"
