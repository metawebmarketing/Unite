from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.connections.models import Connection

User = get_user_model()


class ConnectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Connection
        fields = ["id", "requester_id", "recipient_id", "status", "created_at"]
        read_only_fields = fields


class ConnectActionSerializer(serializers.Serializer):
    user_id = serializers.IntegerField(min_value=1)

    def validate_user_id(self, value):
        if not User.objects.filter(id=value).exists():
            raise serializers.ValidationError("Target user not found.")
        return value
