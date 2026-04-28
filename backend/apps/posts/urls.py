from django.urls import path

from apps.posts.views import (
    BookmarkedPostListView,
    PinnedPostListView,
    PostDetailView,
    PostImageUploadView,
    PostListCreateView,
    PostPinView,
    PostReactView,
    PostSyncEventIngestView,
    PostSyncMetricsView,
    UserPostListView,
)

urlpatterns = [
    path("", PostListCreateView.as_view(), name="post-list-create"),
    path("upload-image", PostImageUploadView.as_view(), name="post-upload-image"),
    path("bookmarks", BookmarkedPostListView.as_view(), name="bookmarked-post-list"),
    path("pinned", PinnedPostListView.as_view(), name="pinned-post-list"),
    path("user/<int:user_id>", UserPostListView.as_view(), name="user-post-list"),
    path("<int:post_id>", PostDetailView.as_view(), name="post-detail"),
    path("<int:post_id>/react", PostReactView.as_view(), name="post-react"),
    path("<int:post_id>/pin", PostPinView.as_view(), name="post-pin"),
    path("sync/metrics", PostSyncMetricsView.as_view(), name="post-sync-metrics"),
    path("sync/events", PostSyncEventIngestView.as_view(), name="post-sync-events"),
]
