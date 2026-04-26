from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.accounts.models import Profile
from apps.ai_accounts.models import AiAccountProfile, AiActionAudit

User = get_user_model()


class AiAccountsApiTests(APITestCase):
    def test_ai_signup_endpoint(self):
        response = self.client.post(
            "/api/v1/ai/signup",
            {
                "username": "agent_1",
                "email": "agent@example.com",
                "password": "Password123!",
                "provider_name": "local",
                "model_name": "gemma-2b",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data["ai_badge_enabled"], True)
        self.assertTrue(response.data["username"].startswith("ai_"))

    def test_ai_signup_creates_audit_entry_and_list_endpoint(self):
        signup_response = self.client.post(
            "/api/v1/ai/signup",
            {
                "username": "agent_2",
                "email": "agent2@example.com",
                "password": "Password123!",
                "provider_name": "local",
                "model_name": "gemma-2b",
            },
            format="json",
        )
        self.assertEqual(signup_response.status_code, 201)
        user = User.objects.get(username=signup_response.data["username"])
        self.assertTrue(AiActionAudit.objects.filter(user=user, action_name="ai_signup").exists())

        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {signup_response.data['access']}")
        audit_response = self.client.get("/api/v1/ai/audit")
        self.assertEqual(audit_response.status_code, 200)
        self.assertTrue(any(item["action_name"] == "ai_signup" for item in audit_response.data))

    def test_ai_post_create_writes_audit_log(self):
        signup_response = self.client.post(
            "/api/v1/ai/signup",
            {
                "username": "agent_3",
                "email": "agent3@example.com",
                "password": "Password123!",
                "provider_name": "local",
                "model_name": "gemma-2b",
            },
            format="json",
        )
        self.assertEqual(signup_response.status_code, 201)
        user = User.objects.get(username=signup_response.data["username"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {signup_response.data['access']}")

        post_response = self.client.post("/api/v1/posts/", {"content": "AI generated post"}, format="json")
        self.assertEqual(post_response.status_code, 201)
        self.assertTrue(AiActionAudit.objects.filter(user=user, action_name="post_create").exists())

    def test_non_ai_user_cannot_read_ai_audit_endpoint(self):
        user = User.objects.create_user(
            username="human_user",
            email="human@example.com",
            password="Password123!",
        )
        Profile.objects.create(user=user, display_name="Human User")
        self.client.force_authenticate(user=user)
        response = self.client.get("/api/v1/ai/audit")
        self.assertEqual(response.status_code, 403)

    def test_ai_middleware_logs_authenticated_write_actions(self):
        signup_response = self.client.post(
            "/api/v1/ai/signup",
            {
                "username": "agent_4",
                "email": "agent4@example.com",
                "password": "Password123!",
                "provider_name": "local",
                "model_name": "gemma-2b",
            },
            format="json",
        )
        self.assertEqual(signup_response.status_code, 201)
        user = User.objects.get(username=signup_response.data["username"])
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {signup_response.data['access']}")
        response = self.client.post(
            "/api/v1/onboarding/interests",
            {"interests": ["tech", "ai", "science", "design", "music"], "location": "us"},
            format="json",
        )
        self.assertEqual(response.status_code, 202)
        self.assertTrue(
            AiActionAudit.objects.filter(
                user=user,
                action_name="post_onboarding_interests",
            ).exists()
        )

    def test_staff_can_query_all_ai_audits_with_filters(self):
        first_signup = self.client.post(
            "/api/v1/ai/signup",
            {
                "username": "agent_5",
                "email": "agent5@example.com",
                "password": "Password123!",
                "provider_name": "local",
                "model_name": "gemma-2b",
            },
            format="json",
        )
        self.assertEqual(first_signup.status_code, 201)
        first_user = User.objects.get(username=first_signup.data["username"])
        second_user = User.objects.create_user(
            username="ai_agent_6",
            email="agent6@example.com",
            password="Password123!",
        )
        Profile.objects.create(user=second_user, display_name="AI 6")
        AiAccountProfile.objects.create(user=second_user, provider_name="local", model_name="gemma-2b")
        AiActionAudit.objects.create(
            user=second_user,
            action_name="post_posts",
            endpoint="/api/v1/posts/",
            method="POST",
            status_code=201,
            payload={},
        )

        staff = User.objects.create_user(
            username="ai_audit_admin",
            email="audit-admin@example.com",
            password="Password123!",
            is_staff=True,
        )
        Profile.objects.create(user=staff, display_name="Audit Admin")
        self.client.force_authenticate(user=staff)

        all_response = self.client.get("/api/v1/ai/audit")
        self.assertEqual(all_response.status_code, 200)
        self.assertTrue(any(item["user_id"] == first_user.id for item in all_response.data))
        self.assertTrue(any(item["user_id"] == second_user.id for item in all_response.data))

        filtered_response = self.client.get(f"/api/v1/ai/audit?user_id={first_user.id}&action_name=ai_signup")
        self.assertEqual(filtered_response.status_code, 200)
        self.assertTrue(filtered_response.data)
        self.assertTrue(all(item["user_id"] == first_user.id for item in filtered_response.data))
