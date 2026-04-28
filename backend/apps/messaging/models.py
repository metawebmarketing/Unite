from django.contrib.auth import get_user_model
from django.db import models
from django.db.models import F, Q

User = get_user_model()


class DMThread(models.Model):
    user_a = models.ForeignKey(User, on_delete=models.CASCADE, related_name="dm_threads_as_a")
    user_b = models.ForeignKey(User, on_delete=models.CASCADE, related_name="dm_threads_as_b")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_message_at = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user_a", "user_b"], name="unique_dm_thread_pair"),
            models.CheckConstraint(condition=Q(user_a__lt=F("user_b")), name="dm_thread_canonical_user_order"),
        ]
        indexes = [
            models.Index(fields=["user_a", "-last_message_at"]),
            models.Index(fields=["user_b", "-last_message_at"]),
        ]

    def __str__(self) -> str:
        return f"DMThread<{self.user_a_id}:{self.user_b_id}>"

    def other_user_id_for(self, user_id: int) -> int:
        return self.user_b_id if self.user_a_id == user_id else self.user_a_id


class DMMessage(models.Model):
    class DeliveryStatus(models.TextChoices):
        SENT = "sent", "Sent"
        READ = "read", "Read"

    thread = models.ForeignKey(DMThread, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name="dm_messages")
    content = models.CharField(max_length=4000, blank=True)
    attachments = models.JSONField(default=list, blank=True)
    link_preview = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["thread", "-created_at"]),
            models.Index(fields=["sender", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"DMMessage<{self.id}:{self.thread_id}:{self.sender_id}>"


class DMThreadParticipant(models.Model):
    thread = models.ForeignKey(DMThread, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="dm_participations")
    last_read_at = models.DateTimeField(null=True, blank=True)
    last_read_message = models.ForeignKey(
        DMMessage,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="read_by_participants",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["thread", "user"], name="unique_dm_thread_participant"),
        ]
        indexes = [
            models.Index(fields=["user", "-updated_at"]),
            models.Index(fields=["thread", "user"]),
        ]

    def __str__(self) -> str:
        return f"DMThreadParticipant<{self.thread_id}:{self.user_id}>"
