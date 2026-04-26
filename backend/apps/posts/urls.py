from django.urls import path

from apps.posts.views import (
    PostListCreateView,
    PostReactView,
    PostSyncEventIngestView,
    PostSyncMetricsView,
)

urlpatterns = [
    path("", PostListCreateView.as_view(), name="post-list-create"),
    path("<int:post_id>/react", PostReactView.as_view(), name="post-react"),
    path("sync/metrics", PostSyncMetricsView.as_view(), name="post-sync-metrics"),
    path("sync/events", PostSyncEventIngestView.as_view(), name="post-sync-events"),
]
