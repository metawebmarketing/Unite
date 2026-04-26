from rest_framework import serializers

from apps.posts.models import SyncReplayEvent


class SyncReplayEventIngestSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=SyncReplayEvent.Source.choices)
    kind = serializers.CharField(max_length=32)
    endpoint = serializers.CharField(max_length=255)
    outcome = serializers.ChoiceField(choices=SyncReplayEvent.Outcome.choices)
    status_code = serializers.IntegerField(required=False, min_value=100, max_value=599)
    idempotency_key = serializers.CharField(required=False, allow_blank=True, max_length=128)
    queued_at = serializers.DateTimeField(required=False)
    detail = serializers.CharField(required=False, allow_blank=True, max_length=255)
