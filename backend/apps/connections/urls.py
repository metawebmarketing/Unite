from django.urls import path

from apps.connections.views import ConnectUserView

urlpatterns = [
    path("<int:user_id>/connect", ConnectUserView.as_view(), name="connect-user"),
]
