from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Profile(models.Model):
    class AlgorithmProfileStatus(models.TextChoices):
        NOT_STARTED = "not_started", "Not started"
        PROCESSING = "processing", "Processing"
        READY = "ready", "Ready"
        FAILED = "failed", "Failed"

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    display_name = models.CharField(max_length=150, blank=True)
    bio = models.CharField(max_length=280, blank=True)
    location = models.CharField(max_length=120, blank=True)
    profile_link_url = models.URLField(blank=True, default="")
    profile_image = models.ImageField(upload_to="profiles/", blank=True, null=True)
    interests = models.JSONField(default=list, blank=True)
    receive_notifications = models.BooleanField(default=True)
    receive_email_notifications = models.BooleanField(default=True)
    receive_push_notifications = models.BooleanField(default=True)
    is_private_profile = models.BooleanField(default=False)
    require_connection_approval = models.BooleanField(default=False)
    algorithm_profile_status = models.CharField(
        max_length=32,
        choices=AlgorithmProfileStatus.choices,
        default=AlgorithmProfileStatus.NOT_STARTED,
    )
    algorithm_vector = models.JSONField(default=dict, blank=True)
    rank_overall_score = models.FloatField(default=0.0)
    rank_action_scores = models.JSONField(default=dict, blank=True)
    rank_last_500_count = models.PositiveIntegerField(default=0)
    rank_provider = models.CharField(max_length=64, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Profile<{self.user_id}>"


class ProfileActionScore(models.Model):
    class ActionType(models.TextChoices):
        POST = "post", "Post"
        REPLY = "reply", "Reply"
        REPOST = "repost", "Repost"
        LIKE = "like", "Like"
        QUOTE = "quote", "Quote"
        BOOKMARK = "bookmark", "Bookmark"
        REPORT = "report", "Report"

    profile = models.ForeignKey(Profile, on_delete=models.CASCADE, related_name="action_scores")
    action_type = models.CharField(max_length=24, choices=ActionType.choices)
    post = models.ForeignKey("posts.Post", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    interaction = models.ForeignKey(
        "posts.PostInteraction",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    sentiment_label = models.CharField(max_length=16, default="neutral")
    sentiment_score = models.FloatField(default=0.0)
    contribution_score = models.FloatField(default=0.0)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["profile", "-created_at"]),
            models.Index(fields=["profile", "action_type", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"ProfileActionScore<{self.profile_id}:{self.action_type}:{self.contribution_score}>"
