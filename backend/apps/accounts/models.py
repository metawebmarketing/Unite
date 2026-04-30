from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class Profile(models.Model):
    class Gender(models.TextChoices):
        FEMALE = "female", "Female"
        MALE = "male", "Male"
        NON_BINARY = "non_binary", "Non Binary"
        SELF_DESCRIBE = "self_describe", "Self Describe"
        PREFER_NOT_TO_SAY = "prefer_not_to_say", "Prefer not to say"

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
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=32, choices=Gender.choices, blank=True, default="")
    gender_self_describe = models.CharField(max_length=120, blank=True, default="")
    zip_code = models.CharField(max_length=20, blank=True, default="")
    country = models.CharField(max_length=120, blank=True, default="")
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


class SiteSetting(models.Model):
    register_via_invite_only = models.BooleanField(default=False)
    allowed_signup_countries = models.JSONField(default=list, blank=True)
    site_name = models.CharField(max_length=120, blank=True, default="")
    support_email = models.EmailField(blank=True, default="")
    frontend_base_url = models.URLField(blank=True, default="")
    default_from_email = models.EmailField(blank=True, default="")
    email_backend = models.CharField(max_length=255, blank=True, default="")
    email_host = models.CharField(max_length=255, blank=True, default="")
    email_port = models.PositiveIntegerField(null=True, blank=True)
    email_host_user = models.CharField(max_length=255, blank=True, default="")
    email_host_password = models.CharField(max_length=255, blank=True, default="")
    email_use_tls = models.BooleanField(null=True, blank=True)
    email_use_ssl = models.BooleanField(null=True, blank=True)
    email_timeout_seconds = models.FloatField(null=True, blank=True)
    enforce_signup_ip_country_match = models.BooleanField(null=True, blank=True)
    allow_signup_on_ip_country_lookup_failure = models.BooleanField(null=True, blank=True)
    ip_country_lookup_timeout_seconds = models.FloatField(null=True, blank=True)
    ip_country_lookup_url_template = models.CharField(max_length=500, blank=True, default="")
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return "SiteSetting"

    @classmethod
    def get_solo(cls):
        instance, _created = cls.objects.get_or_create(id=1)
        return instance


class SignupInvite(models.Model):
    email = models.EmailField()
    token = models.CharField(max_length=72, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    invited_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sent_signup_invites",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["email", "-created_at"]),
            models.Index(fields=["expires_at"]),
            models.Index(fields=["used_at"]),
        ]

    def __str__(self) -> str:
        return f"SignupInvite<{self.email}:{self.token}>"

    def is_valid(self) -> bool:
        if self.used_at is not None:
            return False
        if self.expires_at <= timezone.now():
            return False
        return True

    def mark_used(self) -> None:
        self.used_at = timezone.now()
