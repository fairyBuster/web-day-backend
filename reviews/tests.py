from io import BytesIO

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from PIL import Image
from rest_framework.test import APIClient

from .models import Review


class ReviewsApiTest(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="u1", phone="9001", email="u1@example.com", password="pass"
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _make_image(self, fmt="PNG"):
        buf = BytesIO()
        img = Image.new("RGB", (32, 32), color=(120, 10, 10))
        img.save(buf, format=fmt)
        buf.seek(0)
        return SimpleUploadedFile("test.png", buf.read(), content_type="image/png")

    def test_create_review_requires_image(self):
        res = self.client.post(
            reverse("reviews:reviews-list"), {"text": "bagus"}, format="multipart"
        )
        self.assertEqual(res.status_code, 400)

    def test_create_review_rejects_non_image_disguised_as_png(self):
        fake_image = SimpleUploadedFile(
            "shell.png",
            b"<?php echo 'hacked'; ?>",
            content_type="image/png",
        )
        res = self.client.post(
            reverse("reviews:reviews-list"),
            {"text": "review aman", "images": [fake_image]},
            format="multipart",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("images", res.data)

    def test_create_review_rejects_image_larger_than_1mb(self):
        big_file = SimpleUploadedFile(
            "big.png",
            b"x" * (1024 * 1024 + 1),
            content_type="image/png",
        )
        res = self.client.post(
            reverse("reviews:reviews-list"),
            {"text": "review besar", "images": [big_file]},
            format="multipart",
        )
        self.assertEqual(res.status_code, 400)
        self.assertIn("images", res.data)

    def test_create_list_like_flow(self):
        img = self._make_image()
        res = self.client.post(
            reverse("reviews:reviews-list"),
            {"text": "bagus sekali", "images": [img]},
            format="multipart",
        )
        self.assertEqual(res.status_code, 201)
        review_id = res.data["id"]
        self.assertEqual(len(res.data["images"]), 1)
        self.assertFalse(Review.objects.get(id=review_id).is_approved)

        res_list = self.client.get(reverse("reviews:reviews-list"))
        self.assertEqual(res_list.status_code, 200)
        self.assertEqual(res_list.data["count"], 0)

        res_detail = self.client.get(reverse("reviews:reviews-detail", args=[review_id]))
        self.assertEqual(res_detail.status_code, 404)

        review = Review.objects.get(id=review_id)
        review.is_approved = True
        review.save(update_fields=["is_approved"])

        res_list = self.client.get(reverse("reviews:reviews-list"))
        self.assertEqual(res_list.status_code, 200)
        self.assertGreaterEqual(res_list.data["count"], 1)

        res_detail = self.client.get(reverse("reviews:reviews-detail", args=[review_id]))
        self.assertEqual(res_detail.status_code, 200)

        res_like = self.client.post(reverse("reviews:reviews-like", args=[review_id]))
        self.assertEqual(res_like.status_code, 200)
        self.assertEqual(res_like.data["liked"], True)
        self.assertEqual(res_like.data["likes_count"], 1)

        res_unlike = self.client.delete(reverse("reviews:reviews-like", args=[review_id]))
        self.assertEqual(res_unlike.status_code, 200)
        self.assertEqual(res_unlike.data["liked"], False)
        self.assertEqual(res_unlike.data["likes_count"], 0)

        self.assertTrue(Review.objects.filter(id=review_id).exists())
