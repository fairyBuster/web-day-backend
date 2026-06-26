from django.contrib import admin
from django.utils.html import format_html
from .models import SupportLink, SupportChatThread, SupportChatMessage


@admin.register(SupportLink)
class SupportLinkAdmin(admin.ModelAdmin):
    list_display = ('title', 'platform', 'url', 'icon_preview', 'is_active', 'created_at')
    list_filter = ('platform', 'is_active')
    search_fields = ('title', 'url', 'description')
    fields = ('title', 'url', 'platform', 'description', 'icon', 'is_active')
    readonly_fields = ('icon_preview',)

    def icon_preview(self, obj):
        if obj.icon:
            return format_html('<img src="{}" style="height:32px;width:auto;" />', obj.icon.url)
        return '-'
    icon_preview.short_description = 'Icon'


class SupportChatMessageInline(admin.TabularInline):
    model = SupportChatMessage
    extra = 1
    can_delete = False
    fields = ('message', 'sender_type', 'sender_user', 'created_at')
    readonly_fields = ('sender_type', 'sender_user', 'created_at')

    def has_add_permission(self, request, obj=None):
        # Admin boleh menambah pesan (balasan)
        return request.user.is_staff

    def save_new_objects(self, request, formset, change):
        # Helper for Django<4; we'll override save_formset in ModelAdmin instead
        pass


@admin.register(SupportChatThread)
class SupportChatThreadAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_closed', 'last_message_short', 'updated_at', 'created_at')
    list_filter = ('is_closed',)
    search_fields = ('user__username', 'user__phone')
    inlines = [SupportChatMessageInline]

    actions = ['close_threads']

    def last_message_short(self, obj):
        msg = obj.messages.order_by('-id').first()
        if not msg:
            return '-'
        text = msg.message[:60] + ('...' if len(msg.message) > 60 else '')
        who = 'U' if msg.sender_type == 'USER' else 'A'
        return format_html('<span title="{}">[{}] {}</span>', msg.created_at, who, text)
    last_message_short.short_description = 'Last Msg'

    def save_formset(self, request, form, formset, change):
        # Set otomatis balasan admin saat inline membuat pesan baru
        instances = formset.save(commit=False)
        for obj in instances:
            if obj.pk:
                # existing message, don't modify
                continue
            obj.sender_type = 'ADMIN'
            obj.sender_user = request.user
            obj.save()
        formset.save_m2m()

    def close_threads(self, request, queryset):
        updated = queryset.update(is_closed=True)
        self.message_user(request, f'{updated} thread ditutup.')
    close_threads.short_description = 'Tutup thread terpilih'


@admin.register(SupportChatMessage)
class SupportChatMessageAdmin(admin.ModelAdmin):
    list_display = ('thread', 'sender_type', 'sender_user', 'short_message', 'created_at')
    list_filter = ('sender_type', 'created_at')
    search_fields = ('message', 'thread__user__username', 'thread__user__phone')
    readonly_fields = ('thread', 'sender_type', 'sender_user', 'message', 'created_at')

    def short_message(self, obj):
        return obj.message[:60] + ('...' if len(obj.message) > 60 else '')
    short_message.short_description = 'Message'