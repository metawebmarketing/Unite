from rest_framework import serializers

from apps.notifications.models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    actor_user_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "recipient_id",
            "actor_user_id",
            "event_type",
            "title",
            "message",
            "payload",
            "is_read",
            "created_at",
        ]
        read_only_fields = fields
