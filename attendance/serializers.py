from rest_framework import serializers
from .models import AttendanceSettings, AttendanceLog


class AttendanceSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceSettings
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')


class AttendanceLogSerializer(serializers.ModelSerializer):
    user_phone = serializers.CharField(source='user.phone', read_only=True)

    class Meta:
        model = AttendanceLog
        fields = '__all__'
        read_only_fields = ('user', 'date', 'streak_count', 'amount', 'created_at', 'user_phone')