from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Connection(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        ACCEPTED = "accepted", "Accepted"
        BLOCKED = "blocked", "Blocked"

    requester = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="requested_connections",
    )
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="received_connections",
    )
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["requester", "recipient"],
                name="unique_connection_direction",
            )
        ]
        indexes = [
            models.Index(fields=["requester", "status"]),
            models.Index(fields=["recipient", "status"]),
        ]

    def __str__(self) -> str:
        return f"Connection<{self.requester_id}->{self.recipient_id}:{self.status}>"
