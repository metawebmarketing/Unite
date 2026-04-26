from rest_framework import serializers

from apps.ads.models import AdSlotConfig


class AdDeliveryEventIngestSerializer(serializers.Serializer):
    event_type = serializers.ChoiceField(choices=["impression", "click"])
    ad_event_key = serializers.CharField(max_length=120)
    campaign_key = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    placement = serializers.CharField(max_length=64, required=False, allow_blank=True, default="feed")
    region_code = serializers.CharField(max_length=16, required=False, allow_blank=True, default="global")
    metadata = serializers.JSONField(required=False)


class AdMetricsSerializer(serializers.Serializer):
    impressions = serializers.IntegerField()
    clicks = serializers.IntegerField()
    ctr = serializers.FloatField()
    by_region = serializers.DictField(child=serializers.DictField(child=serializers.IntegerField()))
    by_campaign = serializers.DictField(child=serializers.DictField(child=serializers.IntegerField()))


class AdSlotConfigSerializer(serializers.ModelSerializer):
    def validate_target_interest_tags(self, value):
        if value in (None, ""):
            return []
        if not isinstance(value, list):
            raise serializers.ValidationError("target_interest_tags must be a list.")
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in value:
            token = str(raw).strip().lower()
            if not token or token in seen:
                continue
            seen.add(token)
            normalized.append(token)
        return normalized[:50]

    def validate_campaign_key(self, value: str) -> str:
        return value.strip().lower()

    def validate_experiment_key(self, value: str) -> str:
        return value.strip().lower()

    def validate_region_code(self, value: str) -> str:
        return value.strip().lower()

    class Meta:
        model = AdSlotConfig
        fields = [
            "id",
            "region_code",
            "campaign_key",
            "experiment_key",
            "interval",
            "enabled",
            "account_tier_target",
            "target_interest_tags",
            "updated_at",
        ]
        read_only_fields = ["id", "updated_at"]
