from unittest.mock import patch
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db.models import Q
from django.test import override_settings
from rest_framework.test import APITestCase

from apps.accounts.models import Profile
from apps.install.models import InstallState
from apps.install.demo_corpus import load_demo_post_corpus
from apps.install.tasks import seed_demo_data_task
from apps.messaging.models import DMMessage, DMThread
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
                "seed_total_users": 24,
                "seed_total_posts": 180,
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
        self.assertEqual(state.seed_total_users, 24)
        self.assertEqual(state.seed_total_posts, 180)
        self.assertEqual(state.seed_requested_by_user_id, created_user.id)
        mocked_delay.assert_called_once()
        _, kwargs = mocked_delay.call_args
        self.assertEqual(kwargs["total_users"], 24)
        self.assertEqual(kwargs["total_posts"], 180)

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
        response = self.client.post(
            "/api/v1/install/demo-data/reset",
            {"seed_total_users": 12, "seed_total_posts": 77},
            format="json",
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["removed_users"], 1)
        self.assertEqual(response.data["removed_posts"], 1)
        self.assertFalse(User.objects.filter(username="demo_user_0001").exists())
        mocked_delay.assert_called_once()
        state = InstallState.objects.get(id=1)
        self.assertEqual(state.seed_total_users, 12)
        self.assertEqual(state.seed_total_posts, 77)
        self.assertEqual(state.seed_requested_by_user_id, admin.id)
        _, kwargs = mocked_delay.call_args
        self.assertEqual(kwargs["total_users"], 12)
        self.assertEqual(kwargs["total_posts"], 77)

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

    @patch("apps.install.tasks.score_sentiment_text")
    @patch("apps.install.tasks.score_post_sentiment")
    @patch("apps.install.tasks.random.Random.random", return_value=0.0)
    def test_seed_demo_data_runs_content_through_sentiment_module(
        self,
        _mock_random,
        mock_score_post_sentiment,
        mock_score_sentiment_text,
    ):
        def fake_score_post_sentiment(post):
            Post.objects.filter(id=post.id).update(sentiment_label="neutral", sentiment_score=0.0)
            post.sentiment_label = "neutral"
            post.sentiment_score = 0.0
            return "neutral", 0.0

        mock_score_post_sentiment.side_effect = fake_score_post_sentiment
        mock_score_sentiment_text.return_value = SimpleNamespace(label="neutral", score=0.0)

        result = seed_demo_data_task(install_state_id=1, total_users=3, total_posts=6)

        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result["created_posts"], 6)
        self.assertGreater(result["created_reply_posts"], 0)
        # Every seeded post and generated reply-post should be scored via sentiment module.
        self.assertGreaterEqual(
            mock_score_post_sentiment.call_count,
            result["created_posts"] + result["created_reply_posts"],
        )
        # Quote actions should score quote text through the provider path as well.
        self.assertGreater(mock_score_sentiment_text.call_count, 0)

    def test_demo_corpus_has_expected_size(self):
        corpus = load_demo_post_corpus()
        self.assertGreaterEqual(len(corpus), 10000)

    def test_demo_corpus_contains_toxic_examples(self):
        corpus = load_demo_post_corpus()
        toxic_markers = ("idiot", "incompetent", "dumb", "garbage", "awful", "trash")
        toxic_hits = 0
        for entry in corpus:
            content = str(entry.get("content", "")).lower()
            reply_negative = str(entry.get("reply_negative", "")).lower()
            if any(marker in content or marker in reply_negative for marker in toxic_markers):
                toxic_hits += 1
        self.assertGreaterEqual(toxic_hits, 200)

    def test_seed_demo_data_creates_bidirectional_dm_messages_for_seed_requester(self):
        starter = User.objects.create_user(
            username="starter_admin",
            email="starter@example.com",
            password="Password123!",
            is_staff=True,
        )
        Profile.objects.create(user=starter, display_name="Starter Admin")
        InstallState.objects.update_or_create(
            id=1,
            defaults={
                "installed": True,
                "master_admin_user_id": starter.id,
                "seed_requested_by_user_id": starter.id,
            },
        )

        result = seed_demo_data_task(install_state_id=1, total_users=2, total_posts=2)

        self.assertEqual(result["status"], "ok")
        self.assertGreaterEqual(result.get("created_dm_messages", 0), 4)
        starter_threads = DMThread.objects.filter(
            Q(user_a=starter) | Q(user_b=starter)
        )
        self.assertGreaterEqual(starter_threads.count(), 2)
        inbound_from_demo = DMMessage.objects.filter(thread__in=starter_threads).exclude(sender=starter).count()
        outbound_from_starter = DMMessage.objects.filter(thread__in=starter_threads, sender=starter).count()
        self.assertGreaterEqual(inbound_from_demo, 2)
        self.assertGreaterEqual(outbound_from_starter, 2)
