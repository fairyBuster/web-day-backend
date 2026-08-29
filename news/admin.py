from django.contrib import admin
from .models import News, NewsCategory


@admin.register(NewsCategory)
class NewsCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'created_at')
    search_fields = ('name', 'slug')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'author_name', 'slug', 'is_published', 'published_at', 'updated_at')
    list_filter = ('is_published', 'category')
    search_fields = ('title', 'author_name', 'slug', 'body')
    prepopulated_fields = {'slug': ('title',)}
    fields = ('title', 'slug', 'category', 'author_name', 'body', 'image', 'is_published', 'published_at', 'updated_at')
    readonly_fields = ('published_at', 'updated_at')