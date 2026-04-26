from django.contrib.auth import get_user_model
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Profile
from apps.ai_accounts.models import AiAccountProfile, AiActionAudit

User = get_user_model()


class AiSignupSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField(required=False, allow_blank=True)
    password = serializers.CharField(min_length=8, write_only=True)
    provider_name = serializers.CharField(max_length=80)
    model_name = serializers.CharField(max_length=120)

    def create(self, validated_data):
        username = validated_data["username"]
        user = User.objects.create_user(
            username=f"ai_{username}",
            email=validated_data.get("email", ""),
            password=validated_data["password"],
        )
        Profile.objects.create(
            user=user,
            display_name=f"AI {username}",
            bio="AI account",
        )
        ai_profile = AiAccountProfile.objects.create(
            user=user,
            provider_name=validated_data["provider_name"],
            model_name=validated_data["model_name"],
        )
        return user, ai_profile


class AiSignupResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    username = serializers.CharField()
    ai_badge_enabled = serializers.BooleanField()


class AiActionAuditSerializer(serializers.ModelSerializer):
    class Meta:
        model = AiActionAudit
        fields = [
            "id",
            "user_id",
            "action_name",
            "endpoint",
            "method",
            "status_code",
            "payload",
            "created_at",
        ]


def build_ai_auth_payload(user, ai_profile: AiAccountProfile) -> dict:
    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "username": user.username,
        "ai_badge_enabled": ai_profile.ai_badge_enabled,
    }
