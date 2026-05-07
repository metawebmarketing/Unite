from rest_framework import serializers

from apps.moderation.models import ModerationFlag, ModerationPenalty


class ModerationFlagSerializer(serializers.ModelSerializer):
    class Meta:
        model = ModerationFlag
        fields = [
            "id",
            "profile_id",
            "reporter_user_id",
            "target_user_id",
            "content_type",
            "content_id",
            "status",
            "apply_penalty",
            "reviewed_by_user_id",
            "reviewed_at",
            "review_note",
            "category",
            "reason",
            "payload",
            "policy_region",
            "policy_version",
            "created_at",
        ]


class ModerationDecisionSerializer(serializers.Serializer):
    decision = serializers.ChoiceField(choices=[ModerationFlag.Status.APPROVED, ModerationFlag.Status.DENIED])
    apply_penalty = serializers.BooleanField(default=True)
    report_outcome = serializers.ChoiceField(
        choices=["valid_report", "false_report"],
        required=False,
        default="valid_report",
    )
    review_note = serializers.CharField(required=False, allow_blank=True, max_length=255)


class ModerationPenaltySerializer(serializers.ModelSerializer):
    class Meta:
        model = ModerationPenalty
        fields = [
            "id",
            "user_id",
            "reason_type",
            "source_flag_id",
            "points",
            "active",
            "expires_at",
            "removed_by_user_id",
            "removed_at",
            "removed_reason",
            "created_at",
        ]


class PenaltyRemovalSerializer(serializers.Serializer):
    remove_reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class AccountBanSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)
