from django.urls import path

from apps.connections.views import (
    ApproveConnectionView,
    BlockUserView,
    ConnectUserView,
    ConnectionListView,
    ConnectionStatusView,
    DenyConnectionView,
    DisconnectUserView,
    PendingConnectionListView,
    UnblockUserView,
    UserSearchView,
)

urlpatterns = [
    path("", ConnectionListView.as_view(), name="connection-list-self"),
    path("search", UserSearchView.as_view(), name="connection-user-search"),
    path("users/<int:user_id>", ConnectionListView.as_view(), name="connection-list-user"),
    path("pending", PendingConnectionListView.as_view(), name="connection-pending-list"),
    path("<int:user_id>/status", ConnectionStatusView.as_view(), name="connection-status"),
    path("<int:user_id>/connect", ConnectUserView.as_view(), name="connect-user"),
    path("<int:user_id>/disconnect", DisconnectUserView.as_view(), name="disconnect-user"),
    path("<int:user_id>/approve", ApproveConnectionView.as_view(), name="approve-connection"),
    path("<int:user_id>/deny", DenyConnectionView.as_view(), name="deny-connection"),
    path("<int:user_id>/block", BlockUserView.as_view(), name="block-user"),
    path("<int:user_id>/unblock", UnblockUserView.as_view(), name="unblock-user"),
]
