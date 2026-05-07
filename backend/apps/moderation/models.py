from django.db import models


class ModerationFlag(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        DENIED = "denied", "Denied"

    profile_id = models.PositiveBigIntegerField(db_index=True, null=True, blank=True)
    reporter_user_id = models.PositiveBigIntegerField(db_index=True, null=True, blank=True)
    target_user_id = models.PositiveBigIntegerField(db_index=True, null=True, blank=True)
    content_type = models.CharField(max_length=32, db_index=True, blank=True)
    content_id = models.PositiveBigIntegerField(db_index=True, null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    apply_penalty = models.BooleanField(default=True)
    reviewed_by_user_id = models.PositiveBigIntegerField(db_index=True, null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=255, blank=True)
    category = models.CharField(max_length=64, db_index=True)
    reason = models.CharField(max_length=255)
    payload = models.JSONField(default=dict, blank=True)
    policy_region = models.CharField(max_length=16, db_index=True)
    policy_version = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"ModerationFlag<{self.profile_id}:{self.category}>"


class ModerationPenalty(models.Model):
    class ReasonType(models.TextChoices):
        CONTENT_VIOLATION = "content_violation", "Content Violation"
        FALSE_REPORT = "false_report", "False Report"

    user_id = models.PositiveBigIntegerField(db_index=True)
    reason_type = models.CharField(max_length=32, choices=ReasonType.choices)
    source_flag = models.ForeignKey(
        ModerationFlag,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="penalties",
    )
    points = models.PositiveSmallIntegerField(default=1)
    active = models.BooleanField(default=True, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    removed_by_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_reason = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user_id", "active", "expires_at"]),
            models.Index(fields=["reason_type", "active", "expires_at"]),
        ]

    def __str__(self) -> str:
        return f"ModerationPenalty<{self.user_id}:{self.reason_type}:{self.points}>"
