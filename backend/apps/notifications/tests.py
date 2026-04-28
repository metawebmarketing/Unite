from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.notifications.models import Notification
from apps.notifications.services import create_notification, push_realtime_event
from config.ws_auth import JWTAuthMiddleware

User = get_user_model()


class NotificationApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="notif_user",
            email="notif@example.com",
            password="Password123!",
        )
        self.actor = User.objects.create_user(
            username="actor_user",
            email="actor@example.com",
            password="Password123!",
        )
        self.client.force_authenticate(self.user)

    def test_list_returns_unread_count(self):
        create_notification(
            recipient_user_id=self.user.id,
            actor_user_id=self.actor.id,
            event_type="post.like",
            title="Liked",
            message="Someone liked your post.",
            payload={"post_id": 1},
        )
        response = self.client.get("/api/v1/notifications/")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["unread_count"], 1)
        self.assertEqual(len(response.data["items"]), 1)
        self.assertEqual(response.data["items"][0]["event_type"], "post.like")

    def test_mark_all_read_clears_unread(self):
        create_notification(
            recipient_user_id=self.user.id,
            actor_user_id=self.actor.id,
            event_type="post.reply",
            title="Reply",
            message="Someone replied to your post.",
            payload={"post_id": 2},
        )
        response = self.client.post("/api/v1/notifications/mark-all-read")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["unread_count"], 0)
        self.assertEqual(
            Notification.objects.filter(recipient=self.user, is_read=False).count(),
            0,
        )


class NotificationRealtimeTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="socket_user",
            email="socket@example.com",
            password="Password123!",
        )

    def test_push_realtime_event_is_safe_without_subscriber(self):
        push_realtime_event(
            user_id=self.user.id,
            event_type="notification.created",
            payload={"test": True},
        )
        self.assertTrue(True)

    def test_middleware_extracts_query_token(self):
        middleware = JWTAuthMiddleware(app=lambda scope, receive, send: None)
        token = middleware._extract_token({"query_string": b"token=abc123", "headers": []})
        self.assertEqual(token, "abc123")
