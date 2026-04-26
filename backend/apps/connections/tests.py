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
