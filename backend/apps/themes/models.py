from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class ThemeConfig(models.Model):
    name = models.CharField(max_length=80)
    version = models.CharField(max_length=32)
    tokens = models.JSONField(default=dict)
    is_active = models.BooleanField(default=False)
    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_themes",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["is_active", "-updated_at"])]

    def __str__(self) -> str:
        return f"ThemeConfig<{self.name}:{self.version}>"
