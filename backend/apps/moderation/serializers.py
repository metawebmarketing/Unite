from rest_framework import serializers

from apps.moderation.models import ModerationFlag


class ModerationFlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModerationFlag
        fields = [
            "id",
            "profile_id",
            "content_type",
            "content_id",
            "category",
            "reason",
            "payload",
            "policy_region",
            "policy_version",
            "created_at",
        ]
