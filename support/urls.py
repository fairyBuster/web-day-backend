from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SupportLinkViewSet,
    UserChatMessagesView,
    UserChatSendView,
    AdminChatReplyView,
    UserChatStreamView,
    AdminChatStreamView,
)

router = DefaultRouter()
router.register(r'links', SupportLinkViewSet, basename='support-links')

app_name = 'support'

urlpatterns = [
    path('', include(router.urls)),
    # Chat endpoints
    path('chat/messages/', UserChatMessagesView.as_view(), name='chat-messages'),
    path('chat/send/', UserChatSendView.as_view(), name='chat-send'),
    path('chat/admin/reply/', AdminChatReplyView.as_view(), name='chat-admin-reply'),
    path('chat/stream/', UserChatStreamView.as_view(), name='chat-stream'),
    path('chat/admin/stream/', AdminChatStreamView.as_view(), name='chat-admin-stream'),
]