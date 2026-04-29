from django.urls import path

from apps.notifications.consumers import NotificationConsumer

websocket_urlpatterns = [
    path("ws/notifications", NotificationConsumer.as_asgi()),
    path("ws/notifications/", NotificationConsumer.as_asgi()),
]
