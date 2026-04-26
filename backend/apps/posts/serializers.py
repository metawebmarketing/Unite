from urllib.parse import urlparse

from rest_framework import serializers

from apps.posts.models import MediaAttachment, Post
from apps.posts.services import build_link_preview, validate_media_url


class MediaAttachmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = MediaAttachment
        fields = ["media_type", "media_url"]


class PostSerializer(serializers.ModelSerializer):
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
            "attachments",
            "interaction_counts",
            "has_liked",
            "created_at",
        ]
        read_only_fields = ["id", "author_id", "created_at", "link_preview", "interaction_counts", "has_liked"]

    def validate_link_url(self, value):
        if not value:
            return value
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise serializers.ValidationError("Link URL must be a valid http/https URL.")
        return value

    def validate_attachments(self, value):
        for attachment in value:
            if not validate_media_url(attachment["media_url"], attachment["media_type"]):
                raise serializers.ValidationError(
                    f"Invalid media URL/extension for type '{attachment['media_type']}'."
                )
        return value

    def create(self, validated_data):
        attachments_data = validated_data.pop("attachments", [])
        link_url = validated_data.get("link_url", "")
        validated_data["link_preview"] = build_link_preview(link_url) if link_url else {}
        post = Post.objects.create(**validated_data)
        for attachment in attachments_data:
            MediaAttachment.objects.create(post=post, **attachment)
        return post


class ReactSerializer(serializers.Serializer):
    action = serializers.ChoiceField(
        choices=["like", "reply", "repost", "quote", "bookmark", "report"],
    )
    content = serializers.CharField(required=False, allow_blank=True, max_length=500)
