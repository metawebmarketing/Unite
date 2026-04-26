from django.urls import path

from apps.moderation.views import ModerationFlagListView

urlpatterns = [
    path("flags", ModerationFlagListView.as_view(), name="moderation-flags"),
]
