from django.db import models


class FeedConfig(models.Model):
    suggestion_interval = models.PositiveIntegerField(default=3)
    ad_interval = models.PositiveIntegerField(default=0)
    suggestions_enabled = models.BooleanField(default=True)
    ads_enabled = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return "FeedConfig"
