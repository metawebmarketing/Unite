from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.accounts.models import Profile
from apps.ai_accounts.models import AiAccountProfile
from apps.connections.models import Connection
from apps.connections.views import ConnectUserView

User = get_user_model()


class ConnectionsApiTests(APITestCase):
    def test_connect_endpoint_creates_connection(self):
        requester = User.objects.create_user(username="a", password="Password123!")
        recipient = User.objects.create_user(username="b", password="Password123!")
        Profile.objects.create(user=requester, display_name="A")
        Profile.objects.create(user=recipient, display_name="B")
        self.client.force_authenticate(user=requester)

        response = self.client.post(f"/api/v1/connections/{recipient.id}/connect", format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Connection.objects.count(), 1)

    def test_ai_connect_uses_ai_throttle_scope(self):
        human = User.objects.create_user(username="human_connect", password="Password123!")
        Profile.objects.create(user=human, display_name="HumanConnect")

        ai_user = User.objects.create_user(username="ai_connect", password="Password123!")
        Profile.objects.create(user=ai_user, display_name="AiConnect")
        AiAccountProfile.objects.create(user=ai_user, provider_name="local", model_name="gemma-2b")
        view = ConnectUserView()
        self.assertEqual(view.resolve_throttle_scope(human), "connect_action")
        self.assertEqual(view.resolve_throttle_scope(ai_user), "connect_action_ai")

    def test_connect_creates_pending_when_approval_required(self):
        requester = User.objects.create_user(username="pending_req", password="Password123!")
        recipient = User.objects.create_user(username="pending_rec", password="Password123!")
        Profile.objects.create(user=requester, display_name="Pending Requester")
        Profile.objects.create(user=recipient, display_name="Pending Recipient", require_connection_approval=True)
        self.client.force_authenticate(user=requester)

        response = self.client.post(f"/api/v1/connections/{recipient.id}/connect", format="json")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["status"], Connection.Status.PENDING)

        status_response = self.client.get(f"/api/v1/connections/{recipient.id}/status")
        self.assertEqual(status_response.status_code, 200)
        self.assertEqual(status_response.data["relationship_status"], "pending_outgoing")

    def test_pending_request_can_be_approved_and_denied(self):
        requester = User.objects.create_user(username="approval_req", password="Password123!")
        recipient = User.objects.create_user(username="approval_rec", password="Password123!")
        Profile.objects.create(user=requester, display_name="Approval Requester")
        Profile.objects.create(user=recipient, display_name="Approval Recipient", require_connection_approval=True)

        self.client.force_authenticate(user=requester)
        self.client.post(f"/api/v1/connections/{recipient.id}/connect", format="json")
        self.client.force_authenticate(user=recipient)
        pending_response = self.client.get("/api/v1/connections/pending")
        self.assertEqual(pending_response.status_code, 200)
        self.assertEqual(len(pending_response.data["items"]), 1)
        approve_response = self.client.post(f"/api/v1/connections/{requester.id}/approve", format="json")
        self.assertEqual(approve_response.status_code, 200)
        self.assertTrue(
            Connection.objects.filter(
                requester=requester,
                recipient=recipient,
                status=Connection.Status.ACCEPTED,
            ).exists()
        )

        another = User.objects.create_user(username="deny_req", password="Password123!")
        Profile.objects.create(user=another, display_name="Deny Requester")
        self.client.force_authenticate(user=another)
        self.client.post(f"/api/v1/connections/{recipient.id}/connect", format="json")
        self.client.force_authenticate(user=recipient)
        deny_response = self.client.post(f"/api/v1/connections/{another.id}/deny", format="json")
        self.assertEqual(deny_response.status_code, 200)
        self.assertFalse(
            Connection.objects.filter(
                requester=another,
                recipient=recipient,
                status=Connection.Status.PENDING,
            ).exists()
        )

    def test_block_prevents_connect_and_marks_status(self):
        first = User.objects.create_user(username="block_a", password="Password123!")
        second = User.objects.create_user(username="block_b", password="Password123!")
        Profile.objects.create(user=first, display_name="Block A")
        Profile.objects.create(user=second, display_name="Block B")

        self.client.force_authenticate(user=first)
        block_response = self.client.post(f"/api/v1/connections/{second.id}/block", format="json")
        self.assertEqual(block_response.status_code, 200)
        self.client.force_authenticate(user=second)
        connect_response = self.client.post(f"/api/v1/connections/{first.id}/connect", format="json")
        self.assertEqual(connect_response.status_code, 403)
        status_response = self.client.get(f"/api/v1/connections/{first.id}/status")
        self.assertEqual(status_response.status_code, 200)
        self.assertTrue(status_response.data["is_blocked"])
