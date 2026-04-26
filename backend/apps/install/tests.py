from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import Profile
from apps.install.models import InstallState
from apps.posts.models import Post

User = get_user_model()


class InstallApiTests(APITestCase):
    def test_install_status_before_run(self):
        response = self.client.get("/api/v1/install/status")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.data["installed"])

    @override_settings(CELERY_TASK_ALWAYS_EAGER=False)
    @patch("apps.install.views.seed_demo_data_task.delay")
    def test_install_run_creates_master_admin_and_queues_seed(self, mocked_delay):
        mocked_delay.return_value.id = "task-123"
        response = self.client.post(
            "/api/v1/install/run",
            {
                "username": "master_admin",
                "email": "admin@example.com",
                "password": "Password123!",
                "display_name": "Master Admin",
                "seed_demo_data": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        created_user = User.objects.get(username="master_admin")
        self.assertTrue(created_user.is_staff)
        self.assertTrue(created_user.is_superuser)
        state = InstallState.objects.get(id=1)
        self.assertTrue(state.installed)
        self.assertTrue(state.seed_requested)
        self.assertEqual(state.seed_status, "queued")
        self.assertEqual(state.seed_task_id, "task-123")
        mocked_delay.assert_called_once()

    def test_install_run_fails_after_first_completion(self):
        first = self.client.post(
            "/api/v1/install/run",
            {
                "username": "first_admin",
                "email": "first_admin@example.com",
                "password": "Password123!",
            },
            format="json",
        )
        self.assertEqual(first.status_code, 201)
        second = self.client.post(
            "/api/v1/install/run",
            {
                "username": "second_admin",
                "email": "second_admin@example.com",
                "password": "Password123!",
            },
            format="json",
        )
        self.assertEqual(second.status_code, 409)

    @override_settings(UNITE_ALLOW_LOCAL_DEMO_RESET=True, CELERY_TASK_ALWAYS_EAGER=False)
    @patch("apps.install.views.seed_demo_data_task.delay")
    def test_demo_data_reset_regenerates_seed_for_staff(self, mocked_delay):
        admin = User.objects.create_user(
            username="staff_admin",
            email="staff@example.com",
            password="Password123!",
            is_staff=True,
        )
        Profile.objects.create(user=admin, display_name="Staff Admin")
        demo_user = User.objects.create_user(username="demo_user_0001", password="Password123!")
        Profile.objects.create(user=demo_user, display_name="Demo User")
        Post.objects.create(author=demo_user, content="demo")
        mocked_delay.return_value.id = "seed-2"
        self.client.force_authenticate(user=admin)
        response = self.client.post("/api/v1/install/demo-data/reset", {}, format="json")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["removed_users"], 1)
        self.assertEqual(response.data["removed_posts"], 1)
        self.assertFalse(User.objects.filter(username="demo_user_0001").exists())
        mocked_delay.assert_called_once()

    @override_settings(UNITE_ALLOW_LOCAL_DEMO_RESET=False)
    def test_demo_data_reset_disabled_outside_debug(self):
        admin = User.objects.create_user(
            username="staff_admin_off",
            email="staff-off@example.com",
            password="Password123!",
            is_staff=True,
        )
        Profile.objects.create(user=admin, display_name="Staff Admin Off")
        self.client.force_authenticate(user=admin)
        response = self.client.post("/api/v1/install/demo-data/reset", {}, format="json")
        self.assertEqual(response.status_code, 404)
