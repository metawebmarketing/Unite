from django.urls import path

from apps.feed.views import FeedConfigView, FeedListView

urlpatterns = [
    path("", FeedListView.as_view(), name="feed-list"),
    path("config", FeedConfigView.as_view(), name="feed-config"),
]
