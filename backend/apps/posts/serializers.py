import re
from urllib.parse import urlparse

from rest_framework import serializers

from apps.posts.models import MediaAttachment, Post
from apps.posts.services import build_link_preview, validate_media_url

URL_CANDIDATE_REGEX = re.compile(r"(https?://[^\s<>\"']+)", re.IGNORECASE)


def normalize_first_http_url(value: str) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    for match in URL_CANDIDATE_REGEX.findall(raw_value):
        candidate = str(match).rstrip("),.;!?")
        parsed = urlparse(candidate)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            return candidate
    return ""


class MediaAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = MediaAttachment
        fields = ["media_type", "media_url"]


class PostSerializer(serializers.ModelSerializer):
    link_url = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    link_preview = serializers.SerializerMethodField(read_only=True)
    attachments = MediaAttachmentSerializer(many=True, required=False)
    interaction_counts = serializers.DictField(read_only=True)
    has_liked = serializers.BooleanField(read_only=True)

    class Meta:
        model = Post
        fields = [
            "id",
            "author_id",
            "content",
            "link_url",
            "link_preview",
            "visibility",
            "interest_tags",
            "tagged_user_ids",
            "attachments",
            "interaction_counts",
            "has_liked",
            "sentiment_label",
            "sentiment_score",
            "sentiment_needs_rescore",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "author_id",
            "created_at",
            "link_preview",
            "interaction_counts",
            "has_liked",
            "sentiment_label",
            "sentiment_score",
            "sentiment_needs_rescore",
        ]

    def validate_link_url(self, value):
        normalized = normalize_first_http_url(value)
        if not value and not normalized:
            return ""
        if not normalized:
            raise serializers.ValidationError("Link URL must be a valid http/https URL.")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise serializers.ValidationError("Link URL must be a valid http/https URL.")
        return normalized

    def validate_attachments(self, value):
        if len(value) > 1:
            raise serializers.ValidationError("Only one image attachment is allowed.")
        for attachment in value:
            media_type = str(attachment.get("media_type", "")).strip().lower()
            media_url = str(attachment.get("media_url", "")).strip()
            if media_type != "image":
                raise serializers.ValidationError("Only image attachments are supported for posts.")
            if not validate_media_url(media_url, "image"):
                raise serializers.ValidationError("Invalid image attachment URL.")
        return value

    def create(self, validated_data):
        attachments_data = validated_data.pop("attachments", [])
        link_url = validated_data.get("link_url", "")
        validated_data["link_preview"] = build_link_preview(link_url) if link_url else {}
        post = Post.objects.create(**validated_data)
        for attachment in attachments_data:
            MediaAttachment.objects.create(post=post, **attachment)
        return post

    def get_link_preview(self, obj):
        preview = obj.link_preview if isinstance(obj.link_preview, dict) else {}
        if preview.get("image_url"):
            return preview
        link_url = str(getattr(obj, "link_url", "") or "").strip()
        if not link_url:
            return preview
        return build_link_preview(link_url)


class ReactSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=["like", "reply", "repost", "quote", "bookmark", "report"],
    )
    content = serializers.CharField(required=False, allow_blank=True, max_length=500)
    link_url = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    attachments = serializers.ListField(child=serializers.DictField(), required=False, default=list)
    tagged_user_ids = serializers.ListField(
        child=serializers.IntegerField(min_value=1),
        required=False,
        default=list,
    )

    def validate_link_url(self, value: str) -> str:
        normalized = normalize_first_http_url(value)
        if not value and not normalized:
            return ""
        if not normalized:
            raise serializers.ValidationError("Link URL must be a valid http/https URL.")
        parsed = urlparse(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise serializers.ValidationError("Link URL must be a valid http/https URL.")
        return normalized

    def validate_attachments(self, value):
        if len(value) > 1:
            raise serializers.ValidationError("Only one image attachment is allowed.")
        for attachment in value:
            media_type = str(attachment.get("media_type", "")).strip().lower()
            media_url = str(attachment.get("media_url", "")).strip()
            if media_type != "image":
                raise serializers.ValidationError("Only image attachments are supported for replies/shares.")
            if not media_url:
                raise serializers.ValidationError("Attachment media_url is required.")
            if not validate_media_url(media_url, "image"):
                raise serializers.ValidationError("Invalid image attachment URL.")
        return value
