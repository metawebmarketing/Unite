import re
from datetime import date
from urllib.parse import urlparse

from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.db.models import Q
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.ip_country import is_signup_country_valid_for_ip
from apps.accounts.models import Profile, SignupInvite, SiteSetting
from apps.accounts.runtime_config import get_runtime_config
from apps.connections.models import Connection

User = get_user_model()
URL_CANDIDATE_REGEX = re.compile(r"(https?://[^\s<>\"']+)", re.IGNORECASE)
INVITE_ONLY_SIGNUP_ERROR = (
    "We are currenlty only allowing new accounts via invites only. "
    "If you have received an invite link, please follow that url to register."
)
COUNTRY_RESTRICTED_SIGNUP_ERROR = "Signup is currently unavailable for your country."
IP_COUNTRY_MISMATCH_SIGNUP_ERROR = "Selected country does not match your current network location."


def normalize_invite_token(raw_token: str) -> str:
    token = str(raw_token or "").strip()
    token = token.replace("\n", "").replace("\r", "").replace(" ", "")
    if token.startswith("3D"):
        token = token[2:]
    token = token.replace("=", "")
    return token


class SignupSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    password = serializers.CharField(min_length=8, write_only=True)
    date_of_birth = serializers.DateField()
    gender = serializers.ChoiceField(choices=Profile.Gender.choices)
    gender_self_describe = serializers.CharField(max_length=120, required=False, allow_blank=True, default="")
    zip_code = serializers.CharField(max_length=20)
    country = serializers.CharField(max_length=120)
    invite_token = serializers.CharField(max_length=72, required=False, allow_blank=True, default="")

    def validate_date_of_birth(self, value: date) -> date:
        today = date.today()
        age_years = today.year - value.year - ((today.month, today.day) < (value.month, value.day))
        if age_years < 13:
            raise serializers.ValidationError("You must be at least 13 years old to create an account.")
        return value

    def validate_zip_code(self, value: str) -> str:
        normalized = str(value or "").strip()
        if len(normalized) < 2:
            raise serializers.ValidationError("ZIP code is required.")
        return normalized

    def validate_country(self, value: str) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise serializers.ValidationError("Country is required.")
        return normalized

    def validate(self, attrs):
        gender = str(attrs.get("gender") or "").strip()
        gender_self_describe = str(attrs.get("gender_self_describe") or "").strip()
        if gender == Profile.Gender.SELF_DESCRIBE and not gender_self_describe:
            raise serializers.ValidationError({"gender_self_describe": "Please describe your gender."})
        if gender != Profile.Gender.SELF_DESCRIBE:
            attrs["gender_self_describe"] = ""
        else:
            attrs["gender_self_describe"] = gender_self_describe

        settings_obj = SiteSetting.get_solo()
        invite_only_enabled = bool(settings_obj.register_via_invite_only)
        invite_token = normalize_invite_token(str(attrs.get("invite_token") or ""))
        if invite_only_enabled:
            invite = SignupInvite.objects.filter(token=invite_token).first()
            email = str(attrs.get("email") or "").strip().lower()
            if not invite or not invite.is_valid() or str(invite.email).strip().lower() != email:
                raise serializers.ValidationError(INVITE_ONLY_SIGNUP_ERROR)
            attrs["_resolved_invite"] = invite
        allowed_countries = {
            str(item).strip().lower()
            for item in (settings_obj.allowed_signup_countries or [])
            if str(item).strip()
        }
        if allowed_countries:
            submitted_country = str(attrs.get("country") or "").strip().lower()
            if submitted_country not in allowed_countries:
                raise serializers.ValidationError({"country": COUNTRY_RESTRICTED_SIGNUP_ERROR})
        request = self.context.get("request")
        selected_country = str(attrs.get("country") or "").strip()
        if request is not None and selected_country:
            if not is_signup_country_valid_for_ip(request, selected_country):
                raise serializers.ValidationError({"country": IP_COUNTRY_MISMATCH_SIGNUP_ERROR})
        return attrs

    def create(self, validated_data):
        invite = validated_data.pop("_resolved_invite", None)
        validated_data.pop("invite_token", None)
        profile_payload = {
            "date_of_birth": validated_data.pop("date_of_birth"),
            "gender": validated_data.pop("gender"),
            "gender_self_describe": validated_data.pop("gender_self_describe", ""),
            "zip_code": validated_data.pop("zip_code"),
            "country": validated_data.pop("country"),
        }
        user = User.objects.create_user(**validated_data)
        Profile.objects.create(user=user, display_name=user.username, **profile_payload)
        if isinstance(invite, SignupInvite):
            invite.mark_used()
            invite.save(update_fields=["used_at"])
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
        immutable_fields = {"date_of_birth", "gender", "gender_self_describe", "zip_code", "country"}
        attempted_updates = [field for field in immutable_fields if field in getattr(self, "initial_data", {})]
        if attempted_updates:
            raise serializers.ValidationError(
                {field: "This field cannot be changed after signup." for field in attempted_updates}
            )
        receive_notifications = attrs.get(
            "receive_notifications",
            getattr(self.instance, "receive_notifications", True),
        )
        if not bool(receive_notifications):
            attrs["receive_email_notifications"] = False
            attrs["receive_push_notifications"] = False
        return attrs

    def to_representation(self, instance):
        payload = super().to_representation(instance)
        request = self.context.get("request")
        is_staff = bool(getattr(getattr(request, "user", None), "is_staff", False))
        if not is_staff:
            payload.pop("date_of_birth", None)
            payload.pop("gender", None)
            payload.pop("zip_code", None)
            payload.pop("country", None)
            payload.pop("gender_self_describe", None)
        return payload

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
            "date_of_birth",
            "gender",
            "gender_self_describe",
            "zip_code",
            "country",
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
            "date_of_birth",
            "gender",
            "gender_self_describe",
            "zip_code",
            "country",
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


class SiteSettingSerializer(serializers.ModelSerializer):
    allowed_signup_countries = serializers.ListField(
        child=serializers.CharField(max_length=120),
        required=False,
        allow_empty=True,
    )
    email_host_password = serializers.CharField(write_only=True, required=False, allow_blank=True, max_length=255)
    has_email_host_password = serializers.SerializerMethodField()

    def validate_allowed_signup_countries(self, value):
        normalized: list[str] = []
        seen: set[str] = set()
        for item in value or []:
            token = str(item or "").strip()
            token_key = token.lower()
            if not token or token_key in seen:
                continue
            seen.add(token_key)
            normalized.append(token)
        return normalized

    def validate(self, attrs):
        request = self.context.get("request")
        if request is None:
            return attrs
        user = getattr(request, "user", None)
        if user is None or not bool(getattr(user, "is_authenticated", False)):
            return attrs

        smtp_user = str(
            attrs.get("email_host_user", getattr(self.instance, "email_host_user", "") if self.instance else "")
        ).strip()
        smtp_password = attrs.get("email_host_password", None)
        errors = {}

        admin_username = str(getattr(user, "username", "") or "").strip().lower()
        admin_email = str(getattr(user, "email", "") or "").strip().lower()
        if smtp_user and smtp_user.lower() in {admin_username, admin_email}:
            errors["email_host_user"] = "SMTP username cannot match your admin account username/email."

        if smtp_password is not None:
            smtp_password_token = str(smtp_password or "").strip()
            if smtp_password_token and user.check_password(smtp_password_token):
                errors["email_host_password"] = "SMTP password cannot match your admin account password."

        if errors:
            raise serializers.ValidationError(errors)
        return attrs

    def get_has_email_host_password(self, obj):
        runtime_config = get_runtime_config()
        return bool(str(runtime_config.get("email_host_password", "") or "").strip())

    def update(self, instance, validated_data):
        smtp_password = validated_data.pop("email_host_password", None)
        updated = super().update(instance, validated_data)
        if smtp_password is not None:
            updated.email_host_password = str(smtp_password or "").strip()
            updated.save(update_fields=["email_host_password", "updated_at"])
        return updated

    def to_representation(self, instance):
        payload = super().to_representation(instance)
        runtime_config = get_runtime_config()
        payload["site_name"] = str(runtime_config.get("site_name", ""))
        payload["support_email"] = str(runtime_config.get("support_email", ""))
        payload["frontend_base_url"] = str(runtime_config.get("frontend_base_url", ""))
        payload["default_from_email"] = str(runtime_config.get("default_from_email", ""))
        payload["email_backend"] = str(runtime_config.get("email_backend", ""))
        payload["email_host"] = str(runtime_config.get("email_host", ""))
        payload["email_port"] = int(runtime_config.get("email_port", 25))
        payload["email_host_user"] = str(runtime_config.get("email_host_user", ""))
        payload["email_use_tls"] = bool(runtime_config.get("email_use_tls", False))
        payload["email_use_ssl"] = bool(runtime_config.get("email_use_ssl", False))
        payload["email_timeout_seconds"] = float(runtime_config.get("email_timeout_seconds", 10.0))
        payload["enforce_signup_ip_country_match"] = bool(runtime_config.get("enforce_signup_ip_country_match", True))
        payload["allow_signup_on_ip_country_lookup_failure"] = bool(
            runtime_config.get("allow_signup_on_ip_country_lookup_failure", True)
        )
        payload["ip_country_lookup_timeout_seconds"] = float(
            runtime_config.get("ip_country_lookup_timeout_seconds", 3.0)
        )
        payload["ip_country_lookup_url_template"] = str(runtime_config.get("ip_country_lookup_url_template", ""))
        payload["has_email_host_password"] = bool(str(runtime_config.get("email_host_password", "") or "").strip())
        return payload

    class Meta:
        model = SiteSetting
        fields = [
            "register_via_invite_only",
            "allowed_signup_countries",
            "site_name",
            "support_email",
            "frontend_base_url",
            "default_from_email",
            "email_backend",
            "email_host",
            "email_port",
            "email_host_user",
            "email_host_password",
            "has_email_host_password",
            "email_use_tls",
            "email_use_ssl",
            "email_timeout_seconds",
            "enforce_signup_ip_country_match",
            "allow_signup_on_ip_country_lookup_failure",
            "ip_country_lookup_timeout_seconds",
            "ip_country_lookup_url_template",
            "updated_at",
        ]
        read_only_fields = ["updated_at"]


class SendInviteSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value: str) -> str:
        return str(value or "").strip().lower()


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
