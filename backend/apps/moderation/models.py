from django.db import models


class ModerationFlag(models.Model):
    profile_id = models.PositiveBigIntegerField(db_index=True, null=True, blank=True)
    content_type = models.CharField(max_length=32, db_index=True, blank=True)
    content_id = models.PositiveBigIntegerField(db_index=True, null=True, blank=True)
    category = models.CharField(max_length=64, db_index=True)
    reason = models.CharField(max_length=255)
    payload = models.JSONField(default=dict, blank=True)
    policy_region = models.CharField(max_length=16, db_index=True)
    policy_version = models.CharField(max_length=32)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"ModerationFlag<{self.profile_id}:{self.category}>"
