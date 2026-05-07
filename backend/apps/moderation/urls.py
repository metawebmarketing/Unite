from django.urls import path

from apps.moderation.views import (
    ModerationAccountSearchView,
    ModerationBanAccountView,
    ModerationFlagDecisionView,
    ModerationFlagListView,
    ModerationPenaltyClearView,
    ModerationPenaltyListView,
    ModerationPenaltyRemoveView,
    ModerationUnbanAccountView,
)

urlpatterns = [
    path("flags", ModerationFlagListView.as_view(), name="moderation-flags"),
    path("flags/<int:flag_id>/decision", ModerationFlagDecisionView.as_view(), name="moderation-flag-decision"),
    path("accounts", ModerationAccountSearchView.as_view(), name="moderation-account-search"),
    path("accounts/<int:user_id>/penalties", ModerationPenaltyListView.as_view(), name="moderation-penalty-list"),
    path("penalties/<int:penalty_id>/remove", ModerationPenaltyRemoveView.as_view(), name="moderation-penalty-remove"),
    path("accounts/<int:user_id>/penalties/clear", ModerationPenaltyClearView.as_view(), name="moderation-penalty-clear"),
    path("accounts/<int:user_id>/ban", ModerationBanAccountView.as_view(), name="moderation-account-ban"),
    path("accounts/<int:user_id>/unban", ModerationUnbanAccountView.as_view(), name="moderation-account-unban"),
]
