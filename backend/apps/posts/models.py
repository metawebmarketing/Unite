from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import MinLengthValidator

User = get_user_model()


class Post(models.Model):
    class Visibility(models.TextChoices):
        PUBLIC = "public", "Public"
        CONNECTIONS = "connections", "Connections"

    author = models.ForeignKey(User, on_delete=models.CASCADE, related_name="posts")
    parent_post = models.ForeignKey("self", on_delete=models.CASCADE, related_name="replies", null=True, blank=True)
    content = models.CharField(max_length=500)
    link_url = models.URLField(blank=True)
    link_preview = models.JSONField(default=dict, blank=True)
    visibility = models.CharField(
        max_length=24,
        choices=Visibility.choices,
        default=Visibility.PUBLIC,
    )
    interest_tags = models.JSONField(default=list, blank=True)
    tagged_user_ids = models.JSONField(default=list, blank=True)
    sentiment_label = models.CharField(max_length=16, default="neutral")
    sentiment_score = models.FloatField(default=0.0)
    sentiment_needs_rescore = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["author", "-created_at"]),
            models.Index(fields=["parent_post", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Post<{self.id}:{self.author_id}>"


class MediaAttachment(models.Model):
    class MediaType(models.TextChoices):
        IMAGE = "image", "Image"
        VIDEO = "video", "Video"

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="attachments")
    media_type = models.CharField(max_length=16, choices=MediaType.choices)
    media_url = models.URLField(validators=[MinLengthValidator(10)])
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"MediaAttachment<{self.id}:{self.media_type}>"


class PostInteraction(models.Model):
    class ActionType(models.TextChoices):
        LIKE = "like", "Like"
        REPLY = "reply", "Reply"
        REPOST = "repost", "Repost"
        QUOTE = "quote", "Quote"
        BOOKMARK = "bookmark", "Bookmark"
        REPORT = "report", "Report"

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="interactions")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="post_interactions")
    action_type = models.CharField(max_length=24, choices=ActionType.choices)
    content = models.CharField(max_length=500, blank=True)
    link_url = models.URLField(blank=True)
    attachments = models.JSONField(default=list, blank=True)
    tagged_user_ids = models.JSONField(default=list, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["post", "action_type"]),
            models.Index(fields=["user", "action_type"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["post", "user", "action_type"],
                condition=models.Q(action_type__in=["like", "bookmark", "repost", "report"]),
                name="unique_singleton_interaction_per_user_action",
            )
        ]

    def __str__(self) -> str:
        return f"PostInteraction<{self.post_id}:{self.user_id}:{self.action_type}>"


class LinkPreviewCache(models.Model):
    url = models.URLField(unique=True)
    host = models.CharField(max_length=255)
    title = models.CharField(max_length=255)
    description = models.CharField(max_length=512, blank=True)
    source = models.CharField(max_length=24, default="fallback")
    fetched_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        indexes = [models.Index(fields=["host", "expires_at"])]

    def __str__(self) -> str:
        return f"LinkPreviewCache<{self.host}>"


class IdempotencyRecord(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="idempotency_records")
    endpoint = models.CharField(max_length=120)
    key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    status_code = models.PositiveSmallIntegerField()
    response_body = models.JSONField(default=dict)
    replay_count = models.PositiveIntegerField(default=0)
    conflict_count = models.PositiveIntegerField(default=0)
    last_replayed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "endpoint", "key"],
                name="unique_idempotency_key_per_user_endpoint",
            )
        ]
        indexes = [models.Index(fields=["user", "endpoint", "expires_at"])]

    def __str__(self) -> str:
        return f"IdempotencyRecord<{self.user_id}:{self.endpoint}:{self.key}>"


class SyncReplayEvent(models.Model):
    class Source(models.TextChoices):
        CLIENT = "client", "Client"
        SERVICE_WORKER = "service_worker", "Service Worker"

    class Outcome(models.TextChoices):
        SUCCESS = "success", "Success"
        DROPPED = "dropped", "Dropped"
        RETRY = "retry", "Retry"

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="sync_replay_events")
    source = models.CharField(max_length=24, choices=Source.choices)
    kind = models.CharField(max_length=32)
    endpoint = models.CharField(max_length=255)
    outcome = models.CharField(max_length=16, choices=Outcome.choices)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    idempotency_key = models.CharField(max_length=128, blank=True)
    queued_at = models.DateTimeField(null=True, blank=True)
    replayed_at = models.DateTimeField(auto_now_add=True)
    detail = models.CharField(max_length=255, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "outcome", "-replayed_at"]),
            models.Index(fields=["source", "kind", "-replayed_at"]),
        ]

    def __str__(self) -> str:
        return f"SyncReplayEvent<{self.user_id}:{self.source}:{self.outcome}>"
