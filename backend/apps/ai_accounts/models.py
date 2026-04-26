from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class AiAccountProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="ai_account")
    provider_name = models.CharField(max_length=80)
    model_name = models.CharField(max_length=120)
    ai_badge_enabled = models.BooleanField(default=True)
    is_verified_ai = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"AiAccountProfile<{self.user_id}:{self.model_name}>"


class AiActionAudit(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="ai_action_audits")
    action_name = models.CharField(max_length=80)
    endpoint = models.CharField(max_length=160)
    method = models.CharField(max_length=16)
    status_code = models.PositiveSmallIntegerField(null=True, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["action_name"]),
        ]

    def __str__(self) -> str:
        return f"AiActionAudit<{self.user_id}:{self.action_name}:{self.status_code}>"
