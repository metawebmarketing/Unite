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
    profile_image = models.ImageField(upload_to="profiles/", blank=True, null=True)
    interests = models.JSONField(default=list, blank=True)
    algorithm_profile_status = models.CharField(
        max_length=32,
        choices=AlgorithmProfileStatus.choices,
        default=AlgorithmProfileStatus.NOT_STARTED,
    )
    algorithm_vector = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Profile<{self.user_id}>"
