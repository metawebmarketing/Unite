from urllib.parse import urlparse

from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import serializers

from apps.posts.services import validate_media_url

User = get_user_model()


class DMThreadCreateSerializer(serializers.Serializer):
    recipient_id = serializers.IntegerField(min_value=1)

    def validate_recipient_id(self, value: int) -> int:
        request = self.context.get("request")
        request_user = getattr(request, "user", None)
        if request_user and request_user.id == value:
            raise serializers.ValidationError("Cannot message yourself.")
        if not User.objects.filter(id=value).exists():
            raise serializers.ValidationError("Recipient not found.")
        return value


class DMMessageCreateSerializer(serializers.Serializer):
    content = serializers.CharField(required=False, allow_blank=True)
    link_url = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    attachments = serializers.ListField(
        child=serializers.DictField(),
        required=False,
        default=list,
    )

    def validate_content(self, value: str) -> str:
        max_chars = int(getattr(settings, "UNITE_DM_MAX_MESSAGE_CHARS", 2000))
        if len(value) > max_chars:
            raise serializers.ValidationError(f"Message exceeds max length of {max_chars} characters.")
        return value

    def validate_link_url(self, value: str) -> str:
        if not value:
            return value
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise serializers.ValidationError("Link URL must be a valid http/https URL.")
        return value

    def validate_attachments(self, value: list[dict]) -> list[dict]:
        normalized: list[dict] = []
        for attachment in value:
            media_type = str(attachment.get("media_type", "")).strip().lower()
            media_url = str(attachment.get("media_url", "")).strip()
            if media_type not in {"image", "video"}:
                raise serializers.ValidationError("Attachment media_type must be 'image' or 'video'.")
            if not media_url:
                raise serializers.ValidationError("Attachment media_url is required.")
            if not validate_media_url(media_url, media_type):
                raise serializers.ValidationError(f"Invalid media URL/extension for type '{media_type}'.")
            normalized.append({"media_type": media_type, "media_url": media_url})
        return normalized

    def validate(self, attrs: dict) -> dict:
        content = str(attrs.get("content", "")).strip()
        attachments = attrs.get("attachments", [])
        link_url = str(attrs.get("link_url", "")).strip()
        if not content and not attachments and not link_url:
            raise serializers.ValidationError("Message must include content, attachments, or a link URL.")
        attrs["content"] = content
        attrs["link_url"] = link_url
        return attrs
