from rest_framework import serializers
from .models import News, NewsCategory


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


class NewsCategorySerializer(serializers.ModelSerializer):
    news_count = serializers.IntegerField(source='news.count', read_only=True)

    class Meta:
        model = NewsCategory
        fields = ['id', 'name', 'slug', 'news_count', 'created_at']
        read_only_fields = ['id', 'news_count', 'created_at']


class NewsSerializer(serializers.ModelSerializer):
    image = RelativeImageField(read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True)

    class Meta:
        model = News
        fields = ['id', 'title', 'slug', 'category', 'category_name', 'author_name', 'body', 'image', 'is_published', 'published_at', 'updated_at']
        read_only_fields = ['id', 'category_name', 'published_at', 'updated_at']