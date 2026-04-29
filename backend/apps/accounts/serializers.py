import re
from urllib.parse import urlparse

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.db.models import Q
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.models import Profile
from apps.connections.models import Connection

User = get_user_model()
URL_CANDIDATE_REGEX = re.compile(r"(https?://[^\s<>\"']+)", re.IGNORECASE)


class SignupSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, write_only=True)

    def create(self, validated_data):
        user = User.objects.create_user(**validated_data)
        Profile.objects.create(user=user, display_name=user.username)
        return user


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        user = authenticate(username=attrs["username"], password=attrs["password"])
        if not user:
            raise serializers.ValidationError("Invalid username/password.")
        attrs["user"] = user
        return attrs


class ProfileSerializer(serializers.ModelSerializer):
    profile_link_url = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    is_ai_account = serializers.SerializerMethodField()
    ai_badge_enabled = serializers.SerializerMethodField()
    is_staff = serializers.SerializerMethodField()
    profile_image_url = serializers.SerializerMethodField()
    username = serializers.SerializerMethodField()
    user_id = serializers.SerializerMethodField()
    connection_count = serializers.SerializerMethodField()

    def get_is_ai_account(self, obj):
        return hasattr(obj.user, "ai_account")

    def get_ai_badge_enabled(self, obj):
        if hasattr(obj.user, "ai_account"):
            return bool(obj.user.ai_account.ai_badge_enabled)
        return False

    def get_is_staff(self, obj):
        return bool(obj.user.is_staff)

    def get_profile_image_url(self, obj):
        if not obj.profile_image:
            return ""
        request = self.context.get("request")
        if request is not None:
            return request.build_absolute_uri(obj.profile_image.url)
        return obj.profile_image.url

    def get_username(self, obj):
        return obj.user.username

    def get_user_id(self, obj):
        return obj.user_id

    def get_connection_count(self, obj):
        outgoing = Connection.objects.filter(
            status=Connection.Status.ACCEPTED,
            requester_id=obj.user_id,
        ).count()
        incoming = Connection.objects.filter(
            status=Connection.Status.ACCEPTED,
            recipient_id=obj.user_id,
        ).count()
        return int(outgoing + incoming)

    def validate_profile_link_url(self, value):
        raw_value = str(value or "").strip()
        if not raw_value:
            return ""
        for match in URL_CANDIDATE_REGEX.findall(raw_value):
            candidate = str(match).rstrip("),.;!?")
            parsed = urlparse(candidate)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                return candidate
        raise serializers.ValidationError("Profile link must include a valid http/https URL.")

    def validate(self, attrs):
        receive_notifications = attrs.get(
            "receive_notifications",
            getattr(self.instance, "receive_notifications", True),
        )
        if not bool(receive_notifications):
            attrs["receive_email_notifications"] = False
            attrs["receive_push_notifications"] = False
        return attrs

    class Meta:
        model = Profile
        fields = [
            "display_name",
            "bio",
            "location",
            "profile_link_url",
            "interests",
            "receive_notifications",
            "receive_email_notifications",
            "receive_push_notifications",
            "is_private_profile",
            "require_connection_approval",
            "is_ai_account",
            "ai_badge_enabled",
            "is_staff",
            "profile_image_url",
            "username",
            "user_id",
            "connection_count",
            "algorithm_profile_status",
            "algorithm_vector",
            "rank_overall_score",
            "rank_action_scores",
            "rank_last_500_count",
            "rank_provider",
            "updated_at",
        ]
        read_only_fields = [
            "is_ai_account",
            "ai_badge_enabled",
            "is_staff",
            "profile_image_url",
            "username",
            "user_id",
            "connection_count",
            "algorithm_profile_status",
            "algorithm_vector",
            "rank_overall_score",
            "rank_action_scores",
            "rank_last_500_count",
            "rank_provider",
            "updated_at",
        ]


class OnboardingInterestsSerializer(serializers.Serializer):
    interests = serializers.ListField(child=serializers.CharField(max_length=64), min_length=5)
    location = serializers.CharField(max_length=120, required=False, allow_blank=True)

    def validate_interests(self, value):
        normalized = []
        seen = set()
        for interest in value:
            item = interest.strip().lower()
            if item and item not in seen:
                seen.add(item)
                normalized.append(item)
        if len(normalized) < 5:
            raise serializers.ValidationError("At least 5 unique interests are required.")
        return normalized


class AuthResponseSerializer(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    username = serializers.CharField()
    email = serializers.EmailField()


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(min_length=8, write_only=True)

    def validate(self, attrs):
        try:
            user_id = force_str(urlsafe_base64_decode(attrs["uid"]))
            user = User.objects.get(pk=user_id)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError("Invalid password reset token.")

        if not default_token_generator.check_token(user, attrs["token"]):
            raise serializers.ValidationError("Invalid password reset token.")

        validate_password(attrs["new_password"], user=user)
        attrs["user"] = user
        return attrs


def build_auth_payload(user):
    refresh = RefreshToken.for_user(user)
    return {
        "access": str(refresh.access_token),
        "refresh": str(refresh),
        "username": user.username,
        "email": user.email,
    }


class ProfileImageUploadSerializer(serializers.Serializer):
    image = serializers.ImageField()
    crop_x = serializers.IntegerField(required=False, min_value=0)
    crop_y = serializers.IntegerField(required=False, min_value=0)
    crop_size = serializers.IntegerField(required=False, min_value=1)
