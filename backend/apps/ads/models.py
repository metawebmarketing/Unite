from django.db import models


class AdSlotConfig(models.Model):
    class AccountTierTarget(models.TextChoices):
        ANY = "any", "Any"
        HUMAN = "human", "Human only"
        AI = "ai", "AI only"

    region_code = models.CharField(max_length=16, default="global")
    campaign_key = models.CharField(max_length=64, blank=True, default="")
    experiment_key = models.CharField(max_length=64, blank=True, default="")
    interval = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=False)
    account_tier_target = models.CharField(
        max_length=16,
        choices=AccountTierTarget.choices,
        default=AccountTierTarget.ANY,
    )
    target_interest_tags = models.JSONField(default=list, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["region_code", "enabled"])]

    def __str__(self) -> str:
        return f"AdSlotConfig<{self.region_code}:{self.interval}>"


class AdDeliveryEvent(models.Model):
    class EventType(models.TextChoices):
        IMPRESSION = "impression", "Impression"
        CLICK = "click", "Click"

    user_id = models.PositiveBigIntegerField(null=True, blank=True)
    region_code = models.CharField(max_length=16, default="global")
    event_type = models.CharField(max_length=16, choices=EventType.choices)
    ad_event_key = models.CharField(max_length=120)
    campaign_key = models.CharField(max_length=64, blank=True, default="")
    placement = models.CharField(max_length=64, default="feed")
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=["event_type", "created_at"]),
            models.Index(fields=["ad_event_key", "created_at"]),
            models.Index(fields=["region_code", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"AdDeliveryEvent<{self.event_type}:{self.ad_event_key}>"
