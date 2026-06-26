from django.contrib import admin
from .models import News


@admin.register(News)
class NewsAdmin(admin.ModelAdmin):
    list_display = ('title', 'slug', 'is_published', 'published_at', 'updated_at')
    list_filter = ('is_published',)
    search_fields = ('title', 'slug', 'body')
    prepopulated_fields = {'slug': ('title',)}
    fields = ('title', 'slug', 'body', 'image', 'is_published', 'published_at', 'updated_at')
    readonly_fields = ('published_at', 'updated_at')