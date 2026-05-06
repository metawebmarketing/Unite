import re
from urllib.parse import urlparse

from django.core.cache import cache
from rest_framework import serializers

from apps.accounts.runtime_config import get_runtime_config
from apps.posts.models import MediaAttachment, Post, UploadedMediaAsset
from apps.posts.services import build_link_preview, validate_media_url
from apps.posts.storage import resolve_public_media_url
from apps.posts.tasks import repair_missing_video_thumbnail_now

URL_CANDIDATE_REGEX = re.compile(r"(https?://[^\s<>\"']+)", re.IGNORECASE)


def resolve_post_reply_share_char_cap() -> int:
    runtime = get_runtime_config()
    configured = runtime.get("post_reply_share_char_cap", 500)
    try:
        normalized = int(configured)
    except (TypeError, ValueError):
        normalized = 500
    return max(1, min(500, normalized))


def resolve_post_video_max_upload_bytes() -> int:
    runtime = get_runtime_config()
    configured = runtime.get("post_video_max_upload_bytes", 1024 * 1024 * 1024)
    try:
        normalized = int(configured)
    except (TypeError, ValueError):
        normalized = 1024 * 1024 * 1024
    return max(1, normalized)


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
        fields = [
            "media_type",
            "media_url",
            "thumbnail_url",
            "hls_manifest_url",
            "processing_status",
            "media_bytes",
        ]

    def to_representation(self, instance):
        payload = super().to_representation(instance)
        payload["media_url"] = resolve_public_media_url(payload.get("media_url", ""), self.context.get("request"))
        payload["thumbnail_url"] = resolve_public_media_url(payload.get("thumbnail_url", ""), self.context.get("request"))
        payload["hls_manifest_url"] = resolve_public_media_url(payload.get("hls_manifest_url", ""), self.context.get("request"))
        if (
            str(payload.get("media_type", "")).strip().lower() == "video"
            and not str(payload.get("thumbnail_url", "")).strip()
        ):
            media_url = str(getattr(instance, "media_url", "") or "").strip()
            if media_url:
                cache_key = f"video-thumb-repair:{media_url}"
                should_queue = False
                try:
                    should_queue = bool(cache.add(cache_key, "1", timeout=120))
                except Exception:
                    should_queue = True
                if should_queue:
                    try:
                        # Run repair inline so thumbnails self-heal even when background workers are offline.
                        repair_missing_video_thumbnail_now(media_url=media_url)
                    except Exception:
                        pass
        return payload


class PostSerializer(serializers.ModelSerializer):
    link_url = serializers.CharField(required=False, allow_blank=True, max_length=2000)
    link_preview = serializers.SerializerMethodField(read_only=True)
    attachments = MediaAttachmentSerializer(many=True, required=False)
    interaction_counts = serializers.DictField(read_only=True)
    has_liked = serializers.BooleanField(read_only=True)
    is_root_post = serializers.SerializerMethodField(read_only=True)

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
            "is_root_post",
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
            "is_root_post",
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

    def validate_content(self, value: str) -> str:
        cap = resolve_post_reply_share_char_cap()
        if len(str(value or "")) > cap:
            raise serializers.ValidationError(f"Post content cannot exceed {cap} characters.")
        return value

    def validate_attachments(self, value):
        raw_parent_post_id = self.initial_data.get("parent_post_id") if hasattr(self, "initial_data") else None
        raw_parent_post = self.initial_data.get("parent_post") if hasattr(self, "initial_data") else None
        parent_post_id: int | None = None
        for candidate in (raw_parent_post_id, raw_parent_post):
            try:
                normalized = int(candidate)
            except (TypeError, ValueError):
                normalized = 0
            if normalized > 0:
                parent_post_id = normalized
                break
        is_non_root_post = bool(parent_post_id)
        if is_non_root_post:
            if len(value) > 1:
                raise serializers.ValidationError("Non-parent posts can include only one media attachment.")
        elif len(value) > 20:
            raise serializers.ValidationError("A main post can include up to 20 media attachments.")
        request = self.context.get("request")
        owner = getattr(request, "user", None) if request else None
        cumulative_video_bytes = 0
        for attachment in value:
            media_type = str(attachment.get("media_type", "")).strip().lower()
            media_url = str(attachment.get("media_url", "")).strip()
            if media_type not in {"image", "video"}:
                raise serializers.ValidationError("Attachments must be image or video.")
            if not validate_media_url(media_url, media_type):
                raise serializers.ValidationError("Invalid attachment URL.")
            if media_type == "video":
                if not owner or not getattr(owner, "is_authenticated", False):
                    raise serializers.ValidationError("Video uploads require an authenticated user.")
                asset = (
                    UploadedMediaAsset.objects.filter(
                        user=owner,
                        media_type=MediaAttachment.MediaType.VIDEO,
                        media_url=media_url,
                    )
                    .order_by("-updated_at")
                    .first()
                )
                if not asset:
                    raise serializers.ValidationError("Video attachments must be uploaded through the video upload endpoint.")
                cumulative_video_bytes += int(asset.media_bytes or 0)
        max_upload_bytes = resolve_post_video_max_upload_bytes()
        if cumulative_video_bytes > max_upload_bytes:
            raise serializers.ValidationError(
                f"Total video upload size for a post cannot exceed {max_upload_bytes} bytes."
            )
        return value

    def create(self, validated_data):
        attachments_data = validated_data.pop("attachments", [])
        link_url = validated_data.get("link_url", "")
        validated_data["link_preview"] = build_link_preview(link_url) if link_url else {}
        post = Post.objects.create(**validated_data)
        owner = validated_data.get("author")
        for attachment in attachments_data:
            media_type = str(attachment.get("media_type", "")).strip().lower()
            media_url = str(attachment.get("media_url", "")).strip()
            attachment_payload = {
                "post": post,
                "media_type": media_type,
                "media_url": media_url,
            }
            if owner and getattr(owner, "is_authenticated", False):
                asset = (
                    UploadedMediaAsset.objects.filter(user=owner, media_type=media_type, media_url=media_url)
                    .order_by("-updated_at")
                    .first()
                )
                if asset:
                    attachment_payload["thumbnail_url"] = str(asset.thumbnail_url or "")
                    attachment_payload["hls_manifest_url"] = str(asset.hls_manifest_url or "")
                    attachment_payload["processing_status"] = str(asset.processing_status or UploadedMediaAsset.ProcessingStatus.READY)
                    attachment_payload["media_bytes"] = int(asset.media_bytes or 0)
            MediaAttachment.objects.create(**attachment_payload)
        return post

    def get_link_preview(self, obj):
        preview = obj.link_preview if isinstance(obj.link_preview, dict) else {}
        if preview.get("image_url"):
            return preview
        link_url = str(getattr(obj, "link_url", "") or "").strip()
        if not link_url:
            return preview
        return build_link_preview(link_url)

    def get_is_root_post(self, obj) -> bool:
        return not bool(getattr(obj, "parent_post_id", None))


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

    def validate_content(self, value: str) -> str:
        cap = resolve_post_reply_share_char_cap()
        if len(str(value or "")) > cap:
            raise serializers.ValidationError(f"Reply/share content cannot exceed {cap} characters.")
        return value

    def validate_attachments(self, value):
        if len(value) > 1:
            raise serializers.ValidationError("Only one media attachment is allowed.")
        for attachment in value:
            media_type = str(attachment.get("media_type", "")).strip().lower()
            media_url = str(attachment.get("media_url", "")).strip()
            if media_type not in {"image", "video"}:
                raise serializers.ValidationError("Attachments must be image or video for replies/shares.")
            if not media_url:
                raise serializers.ValidationError("Attachment media_url is required.")
            if not validate_media_url(media_url, media_type):
                raise serializers.ValidationError("Invalid attachment URL.")
        return value
