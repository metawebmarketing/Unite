from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import Profile
from apps.connections.models import Connection
from apps.messaging.models import DMMessage, DMThread

User = get_user_model()


class MessagingApiTests(APITestCase):
    def setUp(self):
        self.user_a = User.objects.create_user(username="dm_user_a", password="Password123!")
        self.user_b = User.objects.create_user(username="dm_user_b", password="Password123!")
        self.user_c = User.objects.create_user(username="dm_user_c", password="Password123!")
        Profile.objects.create(user=self.user_a, display_name="Message Alpha", location="global")
        Profile.objects.create(user=self.user_b, display_name="Message Bravo", location="global")
        Profile.objects.create(user=self.user_c, display_name="Message Charlie", location="global")

    def _create_thread(self, actor: User, recipient_id: int) -> int:
        self.client.force_authenticate(user=actor)
        response = self.client.post("/api/v1/messages/threads", {"recipient_id": recipient_id}, format="json")
        self.assertIn(response.status_code, {200, 201})
        return int(response.data["thread_id"])

    def test_thread_create_is_unique_per_user_pair(self):
        thread_id_first = self._create_thread(self.user_a, self.user_b.id)
        thread_id_second = self._create_thread(self.user_b, self.user_a.id)
        self.assertEqual(thread_id_first, thread_id_second)
        self.assertEqual(DMThread.objects.count(), 1)

    def test_send_message_persists_sender_ip_and_created_at(self):
        thread_id = self._create_thread(self.user_a, self.user_b.id)
        self.client.force_authenticate(user=self.user_a)
        response = self.client.post(
            f"/api/v1/messages/threads/{thread_id}/messages",
            {"content": "Hello from DM"},
            format="json",
            REMOTE_ADDR="203.0.113.44",
        )
        self.assertEqual(response.status_code, 201)
        message = DMMessage.objects.get(id=response.data["id"])
        self.assertEqual(message.sender_id, self.user_a.id)
        self.assertEqual(message.ip_address, "203.0.113.44")
        self.assertIsNotNone(message.created_at)

    def test_non_participant_cannot_view_or_send_thread_messages(self):
        thread_id = self._create_thread(self.user_a, self.user_b.id)
        self.client.force_authenticate(user=self.user_c)
        list_response = self.client.get(f"/api/v1/messages/threads/{thread_id}/messages")
        create_response = self.client.post(
            f"/api/v1/messages/threads/{thread_id}/messages",
            {"content": "Should fail"},
            format="json",
        )
        self.assertEqual(list_response.status_code, 403)
        self.assertEqual(create_response.status_code, 403)

    def test_message_status_changes_to_read_after_recipient_views(self):
        thread_id = self._create_thread(self.user_a, self.user_b.id)
        self.client.force_authenticate(user=self.user_a)
        send_response = self.client.post(
            f"/api/v1/messages/threads/{thread_id}/messages",
            {"content": "Please confirm read"},
            format="json",
        )
        self.assertEqual(send_response.status_code, 201)
        sender_view_before = self.client.get(f"/api/v1/messages/threads/{thread_id}/messages")
        self.assertEqual(sender_view_before.status_code, 200)
        self.assertEqual(sender_view_before.data["items"][0]["status"], "sent")

        self.client.force_authenticate(user=self.user_b)
        recipient_view = self.client.get(f"/api/v1/messages/threads/{thread_id}/messages")
        self.assertEqual(recipient_view.status_code, 200)

        self.client.force_authenticate(user=self.user_a)
        sender_view_after = self.client.get(f"/api/v1/messages/threads/{thread_id}/messages")
        self.assertEqual(sender_view_after.status_code, 200)
        self.assertEqual(sender_view_after.data["items"][0]["status"], "read")

    def test_threads_list_supports_cursor_and_search_filters(self):
        first_thread_id = self._create_thread(self.user_a, self.user_b.id)
        second_thread_id = self._create_thread(self.user_a, self.user_c.id)

        self.client.force_authenticate(user=self.user_a)
        self.client.post(
            f"/api/v1/messages/threads/{first_thread_id}/messages",
            {"content": "Alpha conversation"},
            format="json",
        )
        self.client.post(
            f"/api/v1/messages/threads/{second_thread_id}/messages",
            {"content": "Charlie conversation"},
            format="json",
        )

        first_page = self.client.get("/api/v1/messages/threads", {"page_size": 1})
        self.assertEqual(first_page.status_code, 200)
        self.assertEqual(len(first_page.data["items"]), 1)
        self.assertTrue(first_page.data["has_more"])
        self.assertTrue(first_page.data["next_cursor"])

        search_page = self.client.get("/api/v1/messages/threads", {"search": "charlie"})
        self.assertEqual(search_page.status_code, 200)
        self.assertEqual(len(search_page.data["items"]), 1)
        self.assertEqual(search_page.data["items"][0]["other_user_id"], self.user_c.id)

    @override_settings(UNITE_DM_MAX_MESSAGE_CHARS=2000)
    def test_message_send_idempotency_replays_without_duplicate(self):
        thread_id = self._create_thread(self.user_a, self.user_b.id)
        self.client.force_authenticate(user=self.user_a)
        headers = {"HTTP_IDEMPOTENCY_KEY": "dm-send-key-1"}

        first = self.client.post(
            f"/api/v1/messages/threads/{thread_id}/messages",
            {"content": "Idempotent DM"},
            format="json",
            **headers,
        )
        second = self.client.post(
            f"/api/v1/messages/threads/{thread_id}/messages",
            {"content": "Idempotent DM"},
            format="json",
            **headers,
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(
            DMMessage.objects.filter(thread_id=thread_id, sender=self.user_a, content="Idempotent DM").count(),
            1,
        )

    def test_user_suggestions_prioritize_connections_then_rank(self):
        self.user_d = User.objects.create_user(username="dm_user_delta", password="Password123!")
        self.user_e = User.objects.create_user(username="dm_user_echo", password="Password123!")
        Profile.objects.create(user=self.user_d, display_name="Delta", location="global", rank_overall_score=99.0)
        Profile.objects.create(user=self.user_e, display_name="Echo", location="global", rank_overall_score=42.0)
        Profile.objects.filter(user=self.user_b).update(rank_overall_score=1.0)
        Connection.objects.create(
            requester=self.user_a,
            recipient=self.user_b,
            status=Connection.Status.ACCEPTED,
        )
        self.client.force_authenticate(user=self.user_a)
        response = self.client.get("/api/v1/messages/user-suggestions", {"query": "dm_user", "limit": 10})
        self.assertEqual(response.status_code, 200)
        self.assertGreaterEqual(len(response.data["items"]), 3)
        first = response.data["items"][0]
        self.assertEqual(first["user_id"], self.user_b.id)
        self.assertTrue(first["is_connected"])
        other_user_ids = [item["user_id"] for item in response.data["items"][1:]]
        self.assertIn(self.user_d.id, other_user_ids)
        self.assertIn(self.user_e.id, other_user_ids)

    def test_thread_user_suggestions_only_return_existing_dm_participants(self):
        self.user_d = User.objects.create_user(username="dm_user_delta", password="Password123!")
        Profile.objects.create(user=self.user_d, display_name="Delta", location="global")

        thread_with_b = self._create_thread(self.user_a, self.user_b.id)
        self.client.force_authenticate(user=self.user_a)
        self.client.post(
            f"/api/v1/messages/threads/{thread_with_b}/messages",
            {"content": "Thread with bravo"},
            format="json",
        )
        response = self.client.get("/api/v1/messages/thread-user-suggestions", {"query": "dm_user", "limit": 10})
        self.assertEqual(response.status_code, 200)
        item_user_ids = [int(item["user_id"]) for item in response.data["items"]]
        self.assertIn(self.user_b.id, item_user_ids)
        self.assertNotIn(self.user_c.id, item_user_ids)
        self.assertNotIn(self.user_d.id, item_user_ids)

    def test_send_message_works_without_profile_record(self):
        Profile.objects.filter(user=self.user_a).delete()
        thread_id = self._create_thread(self.user_a, self.user_b.id)
        self.client.force_authenticate(user=self.user_a)
        response = self.client.post(
            f"/api/v1/messages/threads/{thread_id}/messages",
            {"content": "Message without profile"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)

    def test_send_message_link_url_keeps_first_valid_url_when_multiple_provided(self):
        thread_id = self._create_thread(self.user_a, self.user_b.id)
        self.client.force_authenticate(user=self.user_a)
        response = self.client.post(
            f"/api/v1/messages/threads/{thread_id}/messages",
            {
                "content": "Links here",
                "link_url": "https://first.example.com/message and https://second.example.com/message",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        message = DMMessage.objects.get(id=response.data["id"])
        self.assertEqual(message.link_preview.get("url"), "https://first.example.com/message")
