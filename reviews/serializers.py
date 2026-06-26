import os

from PIL import Image

from django.db import transaction
from rest_framework import serializers

from .models import Review, ReviewImage, ReviewLike


class MultiImageField(serializers.ListField):
    child = serializers.ImageField()

    def get_value(self, dictionary):
        if hasattr(dictionary, "getlist"):
            return dictionary.getlist(self.field_name)
        return super().get_value(dictionary)


class ReviewImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReviewImage
        fields = ["id", "image", "created_at"]
        read_only_fields = ["id", "created_at"]


class ReviewSerializer(serializers.ModelSerializer):
    images = ReviewImageSerializer(many=True, read_only=True)
    likes_count = serializers.IntegerField(read_only=True)
    is_liked = serializers.BooleanField(read_only=True)
    user_display_name = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = [
            "id",
            "user_display_name",
            "text",
            "images",
            "likes_count",
            "is_liked",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_user_display_name(self, obj: Review) -> str:
        user = getattr(obj, "user", None)
        if not user:
            return ""
        full_name = (getattr(user, "full_name", "") or "").strip()
        username = (getattr(user, "username", "") or "").strip()
        if full_name:
            return full_name
        if username:
            return username
        return f"User {getattr(user, 'id', '')}".strip()


class ReviewCreateSerializer(serializers.ModelSerializer):
    images = MultiImageField(write_only=True, allow_empty=False, required=True)

    class Meta:
        model = Review
        fields = ["id", "text", "images", "created_at"]
        read_only_fields = ["id", "created_at"]

    def validate_text(self, value: str) -> str:
        value = (value or "").strip()
        if len(value) < 3:
            raise serializers.ValidationError("Teks ulasan minimal 3 karakter.")
        if len(value) > 2000:
            raise serializers.ValidationError("Teks ulasan maksimal 2000 karakter.")
        return value

    def validate_images(self, images):
        if not images:
            raise serializers.ValidationError("Wajib upload minimal 1 gambar/screenshot.")
        if len(images) > 5:
            raise serializers.ValidationError("Maksimal 5 gambar per ulasan.")

        allowed_formats = {
            "JPEG": {".jpg", ".jpeg"},
            "PNG": {".png"},
            "WEBP": {".webp"},
        }
        allowed_content_types = {"image/jpeg", "image/png", "image/webp"}
        max_bytes = 1 * 1024 * 1024

        for f in images:
            if getattr(f, "size", 0) > max_bytes:
                raise serializers.ValidationError("Ukuran gambar maksimal 1MB per file.")

            filename = (getattr(f, "name", "") or "").strip()
            extension = os.path.splitext(filename)[1].lower()
            if not extension or extension not in {ext for exts in allowed_formats.values() for ext in exts}:
                raise serializers.ValidationError("Ekstensi file harus JPG, JPEG, PNG, atau WEBP.")

            content_type = (getattr(f, "content_type", "") or "").lower().strip()
            if content_type and content_type not in allowed_content_types:
                raise serializers.ValidationError("Content-Type file harus image JPG/PNG/WEBP.")

            try:
                img = Image.open(f)
                img.verify()
                f.seek(0)
                img = Image.open(f)
                img.load()
                fmt = (img.format or "").upper()
            except Exception:
                raise serializers.ValidationError("File gambar tidak valid.")
            finally:
                try:
                    f.seek(0)
                except Exception:
                    pass
            if fmt not in allowed_formats:
                raise serializers.ValidationError("Format gambar harus JPG/PNG/WEBP.")
            if extension not in allowed_formats[fmt]:
                raise serializers.ValidationError("Ekstensi file tidak sesuai dengan isi gambar.")

        return images

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        images = validated_data.pop("images", [])
        review = Review.objects.create(user=request.user, **validated_data)
        ReviewImage.objects.bulk_create(
            [ReviewImage(review=review, image=f) for f in images]
        )
        return review

    def to_representation(self, instance):
        request = self.context.get("request")
        base = Review.objects.filter(pk=instance.pk).select_related("user").first()
        if not base:
            base = instance
        base.likes_count = getattr(base, "likes_count", 0)
        base.is_liked = getattr(base, "is_liked", False)
        return ReviewSerializer(base, context={"request": request}).data


class ReviewLikeStateSerializer(serializers.Serializer):
    liked = serializers.BooleanField()
    likes_count = serializers.IntegerField()
