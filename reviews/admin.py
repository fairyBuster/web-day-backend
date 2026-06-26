from django.contrib import admin
from django.utils.html import format_html

from .models import Review, ReviewImage, ReviewLike


class ReviewImageInline(admin.TabularInline):
    model = ReviewImage
    extra = 0
    fields = ["image_preview", "image", "created_at"]
    readonly_fields = ["image_preview", "created_at"]

    def image_preview(self, obj):
        if not obj or not getattr(obj, "image", None):
            return "-"
        try:
            return format_html(
                '<a href="{}" target="_blank" rel="noopener noreferrer">'
                '<img src="{}" style="max-height: 120px; max-width: 120px; object-fit: cover; border-radius: 6px;" />'
                "</a>",
                obj.image.url,
                obj.image.url,
            )
        except Exception:
            return "-"

    image_preview.short_description = "Preview"


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ["id", "image_preview", "user", "is_approved", "is_hidden", "created_at", "updated_at"]
    list_filter = ["is_approved", "is_hidden", "created_at"]
    search_fields = ["id", "user__id", "user__username", "user__full_name", "text"]
    inlines = [ReviewImageInline]
    actions = ["approve_reviews"]
    readonly_fields = ["review_images_preview", "created_at", "updated_at"]
    fieldsets = (
        (None, {"fields": ("user", "text", "is_approved", "is_hidden")}),
        ("Preview Gambar", {"fields": ("review_images_preview",)}),
        ("Timestamps", {"fields": ("created_at", "updated_at")}),
    )

    def image_preview(self, obj):
        first_image = obj.images.first()
        if not first_image or not getattr(first_image, "image", None):
            return "-"
        try:
            return format_html(
                '<a href="{}" target="_blank" rel="noopener noreferrer">'
                '<img src="{}" style="max-height: 60px; max-width: 60px; object-fit: cover; border-radius: 6px;" />'
                "</a>",
                first_image.image.url,
                first_image.image.url,
            )
        except Exception:
            return "-"

    image_preview.short_description = "Gambar"

    def review_images_preview(self, obj):
        if not obj:
            return "-"
        images = list(obj.images.all())
        if not images:
            return "-"
        previews = []
        for image_obj in images:
            if not getattr(image_obj, "image", None):
                continue
            try:
                previews.append(
                    format_html(
                        '<a href="{}" target="_blank" rel="noopener noreferrer" style="display:inline-block;margin:0 8px 8px 0;">'
                        '<img src="{}" style="max-height: 120px; max-width: 120px; object-fit: cover; border-radius: 6px;" />'
                        "</a>",
                        image_obj.image.url,
                        image_obj.image.url,
                    )
                )
            except Exception:
                continue
        return format_html("".join(str(p) for p in previews)) if previews else "-"

    review_images_preview.short_description = "Semua Gambar"

    @admin.action(description="Approve selected reviews")
    def approve_reviews(self, request, queryset):
        queryset.update(is_approved=True)


@admin.register(ReviewLike)
class ReviewLikeAdmin(admin.ModelAdmin):
    list_display = ["id", "review", "user", "created_at"]
    list_filter = ["created_at"]
    search_fields = ["review__id", "user__id", "user__username", "user__full_name"]
