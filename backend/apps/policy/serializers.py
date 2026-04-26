from rest_framework import serializers
from apps.policy.models import PolicyPack


class PolicyResolveRequestSerializer(serializers.Serializer):
    region_code = serializers.CharField(required=False, allow_blank=True, default="global")
    user_key = serializers.CharField(required=False, allow_blank=True, default="")
    at_time = serializers.DateTimeField(required=False)


class PolicyResolveResponseSerializer(serializers.Serializer):
    region_code = serializers.CharField()
    version = serializers.CharField()
    prohibited_categories = serializers.ListField(child=serializers.CharField())
    rollout_percentage = serializers.IntegerField()
    source = serializers.CharField()


class PolicyPackSerializer(serializers.ModelSerializer):
    class Meta:
        model = PolicyPack
        fields = [
            "id",
            "region_code",
            "version",
            "prohibited_categories",
            "enabled",
            "rollout_percentage",
            "effective_from",
            "effective_to",
            "notes",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_rollout_percentage(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError("rollout_percentage must be between 0 and 100.")
        return value

    def validate(self, attrs):
        effective_from = attrs.get("effective_from")
        effective_to = attrs.get("effective_to")
        if effective_from and effective_to and effective_to <= effective_from:
            raise serializers.ValidationError("effective_to must be after effective_from.")
        return attrs
