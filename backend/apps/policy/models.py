from django.db import models
from django.utils import timezone


class PolicyPack(models.Model):
    region_code = models.CharField(max_length=16)
    version = models.CharField(max_length=32)
    prohibited_categories = models.JSONField(default=list)
    enabled = models.BooleanField(default=True)
    rollout_percentage = models.PositiveSmallIntegerField(default=100)
    effective_from = models.DateTimeField(default=timezone.now)
    effective_to = models.DateTimeField(null=True, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["region_code", "version"],
                name="unique_region_policy_version",
            )
        ]
        indexes = [
            models.Index(fields=["region_code", "enabled"]),
            models.Index(fields=["effective_from", "effective_to"]),
        ]

    def __str__(self) -> str:
        return f"PolicyPack<{self.region_code}:{self.version}>"
