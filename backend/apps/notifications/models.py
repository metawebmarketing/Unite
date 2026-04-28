from django.contrib.auth import get_user_model
from django.db import models

User = get_user_model()


class Notification(models.Model):
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="notifications")
    actor_user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        related_name="sent_notifications",
        null=True,
        blank=True,
    )
    event_type = models.CharField(max_length=64)
    title = models.CharField(max_length=140, blank=True)
    message = models.CharField(max_length=280, blank=True)
    payload = models.JSONField(default=dict, blank=True)
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(fields=["recipient", "is_read", "-created_at"]),
            models.Index(fields=["recipient", "-created_at"]),
            models.Index(fields=["event_type", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"Notification<{self.recipient_id}:{self.event_type}:{self.id}>"
