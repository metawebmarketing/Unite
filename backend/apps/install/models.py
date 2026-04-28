from django.db import models


class InstallState(models.Model):
    installed = models.BooleanField(default=False)
    installed_at = models.DateTimeField(null=True, blank=True)
    master_admin_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    seed_requested = models.BooleanField(default=False)
    seed_task_id = models.CharField(max_length=120, blank=True)
    seed_status = models.CharField(max_length=24, default="not_requested")
    seed_total_users = models.PositiveIntegerField(default=0)
    seed_total_posts = models.PositiveIntegerField(default=0)
    seed_created_users = models.PositiveIntegerField(default=0)
    seed_created_posts = models.PositiveIntegerField(default=0)
    seed_requested_by_user_id = models.PositiveBigIntegerField(null=True, blank=True)
    seed_last_message = models.CharField(max_length=255, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"InstallState<{self.installed}:{self.seed_status}>"
