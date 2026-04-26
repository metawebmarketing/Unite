from rest_framework import serializers


class FeedItemSerializer(serializers.Serializer):
    item_type = serializers.ChoiceField(choices=["post", "suggestion", "ad"])
    source_module = serializers.CharField()
    injection_reason = serializers.CharField(allow_blank=True)
    data = serializers.DictField()


class FeedConfigSerializer(serializers.Serializer):
    suggestion_interval = serializers.IntegerField()
    ad_interval = serializers.IntegerField()
    suggestions_enabled = serializers.BooleanField()
    ads_enabled = serializers.BooleanField()
    max_injection_ratio = serializers.FloatField()
    ad_config_id = serializers.IntegerField(allow_null=True, required=False)
    ad_campaign_key = serializers.CharField(required=False, allow_blank=True)
    ad_targeting_reason = serializers.CharField(required=False, allow_blank=True)
    ad_experiment_key = serializers.CharField(required=False, allow_blank=True)


class FeedPageSerializer(serializers.Serializer):
    items = FeedItemSerializer(many=True)
    next_cursor = serializers.CharField(allow_null=True)
    has_more = serializers.BooleanField()
    organic_count = serializers.IntegerField()
