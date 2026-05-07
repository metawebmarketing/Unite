from django.contrib import admin

from apps.moderation.models import ModerationFlag, ModerationPenalty


@admin.register(ModerationFlag)
class ModerationFlagAdmin(admin.ModelAdmin):
    list_display = ("id", "category", "status", "content_type", "content_id", "reporter_user_id", "target_user_id", "created_at")
    list_filter = ("status", "category", "content_type", "policy_region")
    search_fields = ("reason", "category", "review_note")


@admin.register(ModerationPenalty)
class ModerationPenaltyAdmin(admin.ModelAdmin):
    list_display = ("id", "user_id", "reason_type", "points", "active", "expires_at", "created_at")
    list_filter = ("reason_type", "active")
    search_fields = ("user_id", "removed_reason")
