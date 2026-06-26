from rest_framework import serializers
from .models import News


class RelativeImageField(serializers.ImageField):
    def to_representation(self, value):
        if not value:
            return None
        use_url = getattr(self, 'use_url', True)
        if use_url:
            try:
                return value.url
            except AttributeError:
                return None
        return value.name


class NewsSerializer(serializers.ModelSerializer):
    image = RelativeImageField(read_only=True)

    class Meta:
        model = News
        fields = ['id', 'title', 'slug', 'body', 'image', 'is_published', 'published_at', 'updated_at']
        read_only_fields = ['id', 'published_at', 'updated_at']