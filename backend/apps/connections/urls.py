from django.urls import path

from apps.connections.views import (
    ConnectUserView,
    ConnectionListView,
    ConnectionStatusView,
    DisconnectUserView,
    UserSearchView,
)

urlpatterns = [
    path("", ConnectionListView.as_view(), name="connection-list-self"),
    path("search", UserSearchView.as_view(), name="connection-user-search"),
    path("users/<int:user_id>", ConnectionListView.as_view(), name="connection-list-user"),
    path("<int:user_id>/status", ConnectionStatusView.as_view(), name="connection-status"),
    path("<int:user_id>/connect", ConnectUserView.as_view(), name="connect-user"),
    path("<int:user_id>/disconnect", DisconnectUserView.as_view(), name="disconnect-user"),
]
