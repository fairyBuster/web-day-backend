from rest_framework import serializers
from .models import SupportLink, SupportChatThread, SupportChatMessage


class SupportLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportLink
        fields = ['id', 'title', 'url', 'platform', 'description', 'icon', 'is_active', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

# Add a wrapper serializer to reflect paginated response and extra info
class SupportLinkListResponseSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    next = serializers.CharField(allow_null=True, required=False)
    previous = serializers.CharField(allow_null=True, required=False)
    results = SupportLinkSerializer(many=True)
    root_parent_phone = serializers.CharField(allow_null=True, required=False)


class SupportChatMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = SupportChatMessage
        fields = ['id', 'thread', 'sender_type', 'message', 'created_at']
        read_only_fields = ['id', 'thread', 'sender_type', 'created_at']


class SupportChatMessageCreateSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=5000)

    def create(self, validated_data):
        user = self.context['request'].user
        # Dapatkan atau buat thread untuk user
        thread, _ = SupportChatThread.get_or_create_active(user)
        msg = SupportChatMessage.objects.create(
            thread=thread,
            sender_type='USER',
            sender_user=user,
            message=validated_data['message'],
        )
        return msg

    def to_representation(self, instance):
        return SupportChatMessageSerializer(instance).data


class SupportChatAdminReplySerializer(serializers.Serializer):
    user_id = serializers.IntegerField()
    message = serializers.CharField(max_length=5000)

    def validate(self, attrs):
        # pastikan admin
        request = self.context['request']
        if not request.user.is_staff:
            raise serializers.ValidationError('Hanya admin yang boleh membalas.')
        return attrs

    def create(self, validated_data):
        from django.contrib.auth import get_user_model
        User = get_user_model()
        admin = self.context['request'].user
        try:
            target_user = User.objects.get(id=validated_data['user_id'])
        except User.DoesNotExist:
            raise serializers.ValidationError('User tidak ditemukan.')

        thread, _ = SupportChatThread.get_or_create_active(target_user)
        msg = SupportChatMessage.objects.create(
            thread=thread,
            sender_type='ADMIN',
            sender_user=admin,
            message=validated_data['message'],
        )
        return msg

    def to_representation(self, instance):
        return SupportChatMessageSerializer(instance).data


class SupportChatThreadSerializer(serializers.ModelSerializer):
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = SupportChatThread
        fields = ['id', 'is_closed', 'created_at', 'updated_at', 'last_message']
        read_only_fields = ['id', 'created_at', 'updated_at', 'last_message']

    def get_last_message(self, obj):
        msg = obj.messages.order_by('-id').first()
        return SupportChatMessageSerializer(msg).data if msg else None