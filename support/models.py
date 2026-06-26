from django.db import models
from django.conf import settings


class SupportLink(models.Model):
    PLATFORM_CHOICES = [
        ('whatsapp', 'WhatsApp'),
        ('telegram', 'Telegram'),
        ('website', 'Website'),
        ('other', 'Other'),
    ]

    title = models.CharField(max_length=100)
    url = models.URLField(max_length=300)
    platform = models.CharField(max_length=20, choices=PLATFORM_CHOICES, default='other')
    description = models.TextField(blank=True)
    # Optional icon image for display in admin/API
    icon = models.ImageField(upload_to='support/icons/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.platform})"


class SupportChatThread(models.Model):
    """Satu thread chat per user untuk komunikasi dengan admin."""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='support_chat_threads')
    is_closed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"ChatThread(user={self.user_id}, closed={self.is_closed})"

    @classmethod
    def get_or_create_active(cls, user):
        """Dapatkan thread aktif user secara aman (menangani MultipleObjectsReturned)."""
        threads = cls.objects.filter(user=user, is_closed=False).order_by('-id')
        if threads.exists():
            thread = threads[0]
            # Jika ada lebih dari satu, tutup yang lama (opsional tapi disarankan)
            if threads.count() > 1:
                threads.exclude(id=thread.id).update(is_closed=True)
            return thread, False
        return cls.objects.create(user=user, is_closed=False), True


class SupportChatMessage(models.Model):
    """Pesan dalam thread chat antara user dan admin."""
    SENDER_CHOICES = [
        ('USER', 'User'),
        ('ADMIN', 'Admin'),
    ]

    thread = models.ForeignKey(SupportChatThread, on_delete=models.CASCADE, related_name='messages')
    sender_type = models.CharField(max_length=10, choices=SENDER_CHOICES)
    sender_user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='support_chat_messages')
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']

    def __str__(self):
        return f"Msg(thread={self.thread_id}, sender={self.sender_type}, at={self.created_at})"