from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APITestCase

from apps.accounts.models import Profile
from apps.moderation.models import ModerationFlag, ModerationPenalty
from apps.moderation.services import get_active_penalty_count
from apps.posts.models import Post

User = get_user_model()


class ModerationApiTests(APITestCase):
    def setUp(self):
        super().setUp()
        self.admin_user = User.objects.create_user(
            username="admin_mod",
            password="Password123!",
            email="admin@unite.local",
            is_staff=True,
        )
        self.reporter_user = User.objects.create_user(
            username="reporter_mod",
            password="Password123!",
            email="reporter@unite.local",
        )
        self.target_user = User.objects.create_user(
            username="target_mod",
            password="Password123!",
            email="target@unite.local",
        )
        self.poster_user = User.objects.create_user(
            username="poster_mod",
            password="Password123!",
            email="poster@unite.local",
        )
        self.banned_user = User.objects.create_user(
            username="banned_mod",
            password="Password123!",
            email="banned@unite.local",
        )
        self.admin_profile = Profile.objects.create(user=self.admin_user, display_name="Admin")
        self.reporter_profile = Profile.objects.create(user=self.reporter_user, display_name="Reporter")
        self.target_profile = Profile.objects.create(user=self.target_user, display_name="Target")
        self.poster_profile = Profile.objects.create(user=self.poster_user, display_name="Poster")
        self.banned_profile = Profile.objects.create(user=self.banned_user, display_name="Banned")

    def test_moderation_flags_endpoint_requires_admin(self):
        self.client.force_authenticate(user=self.target_user)
        response = self.client.get("/api/v1/moderation/flags")
        self.assertEqual(response.status_code, 403)

    def test_admin_can_approve_flag_with_penalty(self):
        flagged_post = Post.objects.create(author=self.target_user, content="Flagged content")
        flag = ModerationFlag.objects.create(
            target_user_id=self.target_user.id,
            content_type="post",
            content_id=flagged_post.id,
            category="harassment",
            reason="Detected harassment",
            payload={"target_user_id": self.target_user.id},
            policy_region="global",
            policy_version="v1",
        )
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(
            f"/api/v1/moderation/flags/{flag.id}/decision",
            {"decision": "approved", "apply_penalty": True},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        flag.refresh_from_db()
        self.assertEqual(flag.status, ModerationFlag.Status.APPROVED)
        self.assertTrue(ModerationPenalty.objects.filter(source_flag=flag, user_id=self.target_user.id, active=True).exists())

    def test_false_report_decision_penalizes_reporter(self):
        flagged_post = Post.objects.create(author=self.target_user, content="Reported post")
        flag = ModerationFlag.objects.create(
            reporter_user_id=self.reporter_user.id,
            target_user_id=self.target_user.id,
            content_type="post",
            content_id=flagged_post.id,
            category="user_report",
            reason="User report",
            payload={
                "reported_by_user_id": self.reporter_user.id,
                "target_user_id": self.target_user.id,
            },
            policy_region="global",
            policy_version="user-action",
        )
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(
            f"/api/v1/moderation/flags/{flag.id}/decision",
            {
                "decision": "approved",
                "apply_penalty": True,
                "report_outcome": "false_report",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        penalty = ModerationPenalty.objects.filter(source_flag=flag).first()
        self.assertIsNotNone(penalty)
        self.assertEqual(penalty.user_id, self.reporter_user.id)
        self.assertEqual(penalty.reason_type, ModerationPenalty.ReasonType.FALSE_REPORT)

    def test_post_create_blocked_when_three_active_penalties_exist(self):
        now = timezone.now()
        for _ in range(3):
            ModerationPenalty.objects.create(
                user_id=self.poster_user.id,
                reason_type=ModerationPenalty.ReasonType.CONTENT_VIOLATION,
                points=1,
                active=True,
                expires_at=now + timedelta(days=90),
            )
        self.client.force_authenticate(user=self.poster_user)
        response = self.client.post(
            "/api/v1/posts/",
            {"content": "This should be blocked"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("restricted", str(response.data.get("detail", "")).lower())

    def test_banned_user_cannot_login(self):
        self.banned_profile.is_banned = True
        self.banned_profile.banned_at = timezone.now()
        self.banned_profile.banned_reason = "Banned by moderation"
        self.banned_profile.save(update_fields=["is_banned", "banned_at", "banned_reason", "updated_at"])
        response = self.client.post(
            "/api/v1/auth/login",
            {"username": self.banned_user.username, "password": "Password123!"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("banned", str(response.data).lower())

    def test_expired_penalties_are_marked_inactive(self):
        penalty = ModerationPenalty.objects.create(
            user_id=self.target_user.id,
            reason_type=ModerationPenalty.ReasonType.CONTENT_VIOLATION,
            points=1,
            active=True,
            expires_at=timezone.now() - timedelta(minutes=5),
        )
        active_count = get_active_penalty_count(user_id=self.target_user.id)
        self.assertEqual(active_count, 0)
        penalty.refresh_from_db()
        self.assertFalse(penalty.active)
