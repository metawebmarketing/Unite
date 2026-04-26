from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import Profile
from apps.policy.models import PolicyPack

User = get_user_model()


class PolicyApiTests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="policy_admin", password="Password123!", is_staff=True)
        Profile.objects.create(user=self.user, display_name="PolicyAdmin")
        self.client.force_authenticate(user=self.user)

    def test_create_and_list_policy_packs(self):
        create_response = self.client.post(
            "/api/v1/policy/packs",
            {
                "region_code": "us",
                "version": "v2",
                "prohibited_categories": ["harassment"],
                "enabled": True,
                "rollout_percentage": 50,
                "effective_from": timezone.now().isoformat(),
                "notes": "Canary rollout",
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)

        list_response = self.client.get("/api/v1/policy/packs?region_code=us")
        self.assertEqual(list_response.status_code, 200)
        self.assertTrue(any(item["version"] == "v2" for item in list_response.data))

    def test_resolve_policy_returns_pack_when_rollout_allows(self):
        PolicyPack.objects.create(
            region_code="us",
            version="v3",
            prohibited_categories=["illegal_promotion"],
            enabled=True,
            rollout_percentage=100,
        )
        response = self.client.post(
            "/api/v1/policy/resolve",
            {"region_code": "us", "user_key": "user-1"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["version"], "v3")
        self.assertEqual(response.data["source"], "policy_pack")

    def test_resolve_policy_falls_back_to_global_pack(self):
        PolicyPack.objects.create(
            region_code="global",
            version="v-global",
            prohibited_categories=["credible_violence"],
            enabled=True,
            rollout_percentage=100,
        )
        response = self.client.post(
            "/api/v1/policy/resolve",
            {"region_code": "ca", "user_key": "user-2"},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["version"], "v-global")
        self.assertEqual(response.data["region_code"], "global")

    def test_policy_pack_create_forbidden_for_non_staff(self):
        non_staff = User.objects.create_user(username="policy_member", password="Password123!")
        Profile.objects.create(user=non_staff, display_name="PolicyMember")
        self.client.force_authenticate(user=non_staff)
        response = self.client.post(
            "/api/v1/policy/packs",
            {
                "region_code": "us",
                "version": "v-x",
                "prohibited_categories": ["harassment"],
                "enabled": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 403)
