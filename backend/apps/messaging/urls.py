from django.urls import path

from apps.messaging.views import (
    DMThreadListCreateView,
    DMThreadMessageListCreateView,
    DMThreadUserSuggestionView,
    DMUserSuggestionView,
)

urlpatterns = [
    path("user-suggestions", DMUserSuggestionView.as_view(), name="dm-user-suggestions"),
    path("thread-user-suggestions", DMThreadUserSuggestionView.as_view(), name="dm-thread-user-suggestions"),
    path("threads", DMThreadListCreateView.as_view(), name="dm-thread-list-create"),
    path("threads/<int:thread_id>/messages", DMThreadMessageListCreateView.as_view(), name="dm-thread-messages"),
]
