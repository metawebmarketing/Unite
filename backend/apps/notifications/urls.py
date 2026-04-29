from django.urls import path

from apps.notifications.views import NotificationListView, NotificationMarkAllReadView

urlpatterns = [
    path("", NotificationListView.as_view(), name="notification-list"),
    path("mark-all-read", NotificationMarkAllReadView.as_view(), name="notification-mark-all-read"),
    path("mark-all-read/", NotificationMarkAllReadView.as_view(), name="notification-mark-all-read-slash"),
]
