from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    type_display = serializers.CharField(source="get_type_display", read_only=True)
    recipient_user = serializers.StringRelatedField()
    recipient_parent = serializers.StringRelatedField()

    class Meta:
        model = Notification
        fields = [
            "id",
            "title",
            "message",
            "type",
            "type_display",
            "is_read",
            "recipient_user",
            "recipient_parent",
            "created_at",
        ]


class MarkReadSerializer(serializers.Serializer):
    notification_id = serializers.UUIDField()
