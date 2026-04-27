from django.contrib.auth import get_user_model
from datetime import timedelta
from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APITestCase
from unittest.mock import patch

from apps.accounts.models import Profile, ProfileActionScore
from apps.ai_accounts.models import AiAccountProfile
from apps.feed.sentiment_providers import SentimentResult
from apps.moderation.models import ModerationFlag
from apps.posts.models import (
    IdempotencyRecord,
    LinkPreviewCache,
    Post,
    PostInteraction,
    SyncReplayEvent,
)
from apps.posts.tasks import cleanup_expired_post_caches
from apps.posts.views import PostListCreateView

User = get_user_model()


class PostsApiTests(APITestCase):
    @patch("apps.accounts.ranking.score_sentiment_text")
    def test_create_post_marks_rescore_when_sentiment_provider_unavailable(self, mock_score_sentiment_text):
        mock_score_sentiment_text.return_value = SentimentResult(
            label="neutral",
            score=0.0,
            confidence=0.0,
            needs_rescore=True,
        )
        user = User.objects.create_user(username="poster_rescore", password="Password123!")
        Profile.objects.create(user=user, display_name="Poster Rescore")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {"content": "Content pending sentiment retry", "interest_tags": ["tech"]},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        created = Post.objects.get(id=response.data["id"])
        self.assertTrue(created.sentiment_needs_rescore)

    def test_create_post(self):
        user = User.objects.create_user(username="poster", password="Password123!")
        Profile.objects.create(user=user, display_name="Poster")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {"content": "Hello Unite", "interest_tags": ["tech"]},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Post.objects.count(), 1)
        created = Post.objects.first()
        self.assertIsNotNone(created)
        self.assertIn(created.sentiment_label, {"positive", "neutral", "negative"})
        self.assertIn("sentiment_label", response.data)
        self.assertIn("sentiment_score", response.data)
        user.profile.refresh_from_db()
        self.assertGreaterEqual(user.profile.rank_last_500_count, 1)

    @patch("apps.accounts.ranking.score_sentiment_text")
    def test_loading_flagged_post_attempts_rescore_and_clears_flag(self, mock_score_sentiment_text):
        mock_score_sentiment_text.return_value = SentimentResult(
            label="positive",
            score=0.72,
            confidence=0.84,
            needs_rescore=False,
        )
        author = User.objects.create_user(username="flagged_author", password="Password123!")
        Profile.objects.create(user=author, display_name="Flagged Author")
        viewer = User.objects.create_user(username="flagged_viewer", password="Password123!")
        Profile.objects.create(user=viewer, display_name="Flagged Viewer")
        post = Post.objects.create(
            author=author,
            content="Rescore this item on next read.",
            sentiment_label="neutral",
            sentiment_score=0.0,
            sentiment_needs_rescore=True,
        )
        self.client.force_authenticate(user=viewer)
        response = self.client.get(f"/api/v1/posts/{post.id}")
        self.assertEqual(response.status_code, 200)
        post.refresh_from_db()
        self.assertFalse(post.sentiment_needs_rescore)
        self.assertEqual(post.sentiment_label, "positive")

    def test_react_like_toggle(self):
        user = User.objects.create_user(username="reactor", password="Password123!")
        Profile.objects.create(user=user, display_name="Reactor")
        post_author = User.objects.create_user(username="author", password="Password123!")
        Profile.objects.create(user=post_author, display_name="Author")
        post = Post.objects.create(author=post_author, content="test")
        self.client.force_authenticate(user=user)

        first_response = self.client.post(
            f"/api/v1/posts/{post.id}/react",
            {"action": "like"},
            format="json",
        )
        second_response = self.client.post(
            f"/api/v1/posts/{post.id}/react",
            {"action": "like"},
            format="json",
        )
        self.assertEqual(first_response.status_code, 201)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(
            PostInteraction.objects.filter(
                post=post,
                user=user,
                action_type=PostInteraction.ActionType.LIKE,
            ).count(),
            0,
        )
        reactor_profile = user.profile
        reactor_profile.refresh_from_db()
        self.assertGreaterEqual(reactor_profile.rank_last_500_count, 1)
        self.assertTrue(
            ProfileActionScore.objects.filter(
                profile=reactor_profile,
                action_type=ProfileActionScore.ActionType.LIKE,
            ).exists()
        )

    def test_false_report_penalizes_profile_score(self):
        reporter = User.objects.create_user(username="false_reporter", password="Password123!")
        Profile.objects.create(user=reporter, display_name="False Reporter", location="global")
        author = User.objects.create_user(username="safe_author", password="Password123!")
        Profile.objects.create(user=author, display_name="Safe Author")
        safe_post = Post.objects.create(
            author=author,
            content="This is a constructive and helpful update.",
            sentiment_label="positive",
            sentiment_score=0.8,
        )
        self.client.force_authenticate(user=reporter)
        response = self.client.post(
            f"/api/v1/posts/{safe_post.id}/react",
            {"action": "report"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        reporter.profile.refresh_from_db()
        self.assertLess(reporter.profile.rank_overall_score, 0)

    def test_reply_to_negative_post_caps_contribution_at_neutral(self):
        replier = User.objects.create_user(username="negative_reply_user", password="Password123!")
        Profile.objects.create(user=replier, display_name="NegativeReply")
        author = User.objects.create_user(username="negative_post_author", password="Password123!")
        Profile.objects.create(user=author, display_name="NegativeAuthor")
        target_post = Post.objects.create(
            author=author,
            content="This rollout failed and introduced major reliability issues.",
            sentiment_label="negative",
            sentiment_score=-0.85,
        )
        self.client.force_authenticate(user=replier)
        response = self.client.post(
            f"/api/v1/posts/{target_post.id}/react",
            {"action": "reply", "content": "Great breakdown. This gave me a clear and constructive plan."},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        reply_event = (
            ProfileActionScore.objects.filter(
                profile=replier.profile,
                action_type=ProfileActionScore.ActionType.REPLY,
            )
            .order_by("-created_at", "-id")
            .first()
        )
        self.assertIsNotNone(reply_event)
        self.assertLessEqual(float(reply_event.contribution_score), 0.0)

    def test_repost_toggle_off_for_negative_post_does_not_create_positive_contribution(self):
        user = User.objects.create_user(username="negative_repost_user", password="Password123!")
        Profile.objects.create(user=user, display_name="NegativeRepost")
        author = User.objects.create_user(username="negative_repost_author", password="Password123!")
        Profile.objects.create(user=author, display_name="NegativeRepostAuthor")
        target_post = Post.objects.create(
            author=author,
            content="The process is unstable and failing under load.",
            sentiment_label="negative",
            sentiment_score=-0.8,
        )
        self.client.force_authenticate(user=user)
        first = self.client.post(f"/api/v1/posts/{target_post.id}/react", {"action": "repost"}, format="json")
        second = self.client.post(f"/api/v1/posts/{target_post.id}/react", {"action": "repost"}, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        latest_repost_event = (
            ProfileActionScore.objects.filter(
                profile=user.profile,
                action_type=ProfileActionScore.ActionType.REPOST,
            )
            .order_by("-created_at", "-id")
            .first()
        )
        self.assertIsNotNone(latest_repost_event)
        self.assertLessEqual(float(latest_repost_event.contribution_score), 0.0)

    def test_duplicate_post_blocked_in_short_window(self):
        user = User.objects.create_user(username="dupe_user", password="Password123!")
        Profile.objects.create(user=user, display_name="DupeUser")
        self.client.force_authenticate(user=user)
        payload = {"content": "same content", "interest_tags": ["tech"]}
        first = self.client.post("/api/v1/posts/", payload, format="json")
        second = self.client.post("/api/v1/posts/", payload, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)

    @override_settings(UNITE_SPAM_BURST_WINDOW_SECONDS=300, UNITE_SPAM_BURST_MAX_POSTS=2)
    def test_burst_posting_limit_blocks_after_threshold(self):
        user = User.objects.create_user(username="burst_user", password="Password123!")
        Profile.objects.create(user=user, display_name="BurstUser")
        self.client.force_authenticate(user=user)
        first = self.client.post("/api/v1/posts/", {"content": "burst one"}, format="json")
        second = self.client.post("/api/v1/posts/", {"content": "burst two"}, format="json")
        third = self.client.post("/api/v1/posts/", {"content": "burst three"}, format="json")
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(third.status_code, 429)
        self.assertEqual(third.data.get("spam_rule"), "burst_post_limit")

    @override_settings(UNITE_SPAM_LINK_WINDOW_SECONDS=300, UNITE_SPAM_LINK_MAX_POSTS=2)
    def test_repeated_link_limit_blocks_after_threshold(self):
        user = User.objects.create_user(username="link_spam_user", password="Password123!")
        Profile.objects.create(user=user, display_name="LinkSpamUser")
        self.client.force_authenticate(user=user)
        link = "https://example.com/repeat-link"
        first = self.client.post(
            "/api/v1/posts/",
            {"content": "link one", "link_url": link},
            format="json",
        )
        second = self.client.post(
            "/api/v1/posts/",
            {"content": "link two", "link_url": link},
            format="json",
        )
        third = self.client.post(
            "/api/v1/posts/",
            {"content": "link three", "link_url": link},
            format="json",
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(third.status_code, 429)
        self.assertEqual(third.data.get("spam_rule"), "repeated_link_limit")

    def test_post_rejected_by_moderation_policy(self):
        user = User.objects.create_user(username="policy_user", password="Password123!")
        Profile.objects.create(user=user, display_name="PolicyUser", location="global")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {"content": "You should go die", "interest_tags": ["tech"]},
            format="json",
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("blocked_categories", response.data)

    def test_invalid_media_extension_rejected(self):
        user = User.objects.create_user(username="media_user", password="Password123!")
        Profile.objects.create(user=user, display_name="MediaUser")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {
                "content": "post",
                "attachments": [{"media_type": "image", "media_url": "https://cdn/site/file.exe"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_link_preview_generated(self):
        user = User.objects.create_user(username="link_user", password="Password123!")
        Profile.objects.create(user=user, display_name="LinkUser")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {
                "content": "Interesting article",
                "link_url": "https://example.com/news/breaking-update",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Post.objects.get(id=response.data["id"]).link_preview["host"], "example.com")
        self.assertEqual(LinkPreviewCache.objects.filter(url="https://example.com/news/breaking-update").count(), 1)

    def test_link_preview_cache_reused(self):
        user = User.objects.create_user(username="cache_user", password="Password123!")
        Profile.objects.create(user=user, display_name="CacheUser")
        self.client.force_authenticate(user=user)
        payload = {
            "content": "A",
            "link_url": "https://example.com/path/cacheable-item",
        }
        first = self.client.post("/api/v1/posts/", payload, format="json")
        self.assertEqual(first.status_code, 201)
        second = self.client.post(
            "/api/v1/posts/",
            {
                "content": "B",
                "link_url": "https://example.com/path/cacheable-item",
            },
            format="json",
        )
        self.assertEqual(second.status_code, 201)
        self.assertEqual(LinkPreviewCache.objects.filter(url=payload["link_url"]).count(), 1)

    def test_report_action_creates_moderation_flag(self):
        reporter = User.objects.create_user(username="reporter", password="Password123!")
        Profile.objects.create(user=reporter, display_name="Reporter", location="global")
        author = User.objects.create_user(username="author2", password="Password123!")
        Profile.objects.create(user=author, display_name="Author2")
        post = Post.objects.create(author=author, content="review me")
        self.client.force_authenticate(user=reporter)
        response = self.client.post(
            f"/api/v1/posts/{post.id}/react",
            {"action": "report"},
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            ModerationFlag.objects.filter(
                content_type="post",
                content_id=post.id,
                category="user_report",
            ).exists()
        )

    def test_idempotency_key_replays_create_post_without_duplication(self):
        user = User.objects.create_user(username="idem_user", password="Password123!")
        Profile.objects.create(user=user, display_name="IdemUser")
        self.client.force_authenticate(user=user)
        payload = {"content": "idempotent post", "interest_tags": ["tech"]}
        headers = {"HTTP_IDEMPOTENCY_KEY": "create-post-key-1"}

        first = self.client.post("/api/v1/posts/", payload, format="json", **headers)
        second = self.client.post("/api/v1/posts/", payload, format="json", **headers)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(Post.objects.filter(author=user).count(), 1)
        self.assertEqual(IdempotencyRecord.objects.filter(user=user, endpoint="posts.create").count(), 1)

    def test_idempotency_key_rejects_payload_mismatch(self):
        user = User.objects.create_user(username="idem_mismatch", password="Password123!")
        Profile.objects.create(user=user, display_name="IdemMismatch")
        self.client.force_authenticate(user=user)
        headers = {"HTTP_IDEMPOTENCY_KEY": "create-post-key-2"}

        first = self.client.post(
            "/api/v1/posts/",
            {"content": "first payload", "interest_tags": ["tech"]},
            format="json",
            **headers,
        )
        second = self.client.post(
            "/api/v1/posts/",
            {"content": "different payload", "interest_tags": ["tech"]},
            format="json",
            **headers,
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 409)

    def test_idempotency_key_replays_react_without_toggle_flip(self):
        user = User.objects.create_user(username="idem_react_user", password="Password123!")
        Profile.objects.create(user=user, display_name="IdemReactUser")
        author = User.objects.create_user(username="idem_react_author", password="Password123!")
        Profile.objects.create(user=author, display_name="IdemReactAuthor")
        post = Post.objects.create(author=author, content="idempotent reaction")
        self.client.force_authenticate(user=user)
        headers = {"HTTP_IDEMPOTENCY_KEY": "react-key-1"}

        first = self.client.post(
            f"/api/v1/posts/{post.id}/react",
            {"action": "like"},
            format="json",
            **headers,
        )
        second = self.client.post(
            f"/api/v1/posts/{post.id}/react",
            {"action": "like"},
            format="json",
            **headers,
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(
            PostInteraction.objects.filter(
                post=post,
                user=user,
                action_type=PostInteraction.ActionType.LIKE,
            ).count(),
            1,
        )

    @override_settings(UNITE_SPAM_BURST_MAX_POSTS=1000, UNITE_SPAM_LINK_MAX_POSTS=1000)
    def test_sync_metrics_reports_replay_and_conflict_counts(self):
        user = User.objects.create_user(username="metrics_user", password="Password123!")
        Profile.objects.create(user=user, display_name="MetricsUser")
        self.client.force_authenticate(user=user)
        headers = {"HTTP_IDEMPOTENCY_KEY": "metrics-key-1"}

        first = self.client.post(
            "/api/v1/posts/",
            {"content": "metrics payload", "interest_tags": ["tech"]},
            format="json",
            **headers,
        )
        second = self.client.post(
            "/api/v1/posts/",
            {"content": "metrics payload", "interest_tags": ["tech"]},
            format="json",
            **headers,
        )
        third = self.client.post(
            "/api/v1/posts/",
            {"content": "metrics payload mismatch", "interest_tags": ["tech"]},
            format="json",
            **headers,
        )
        self.assertEqual(first.status_code, 201)
        self.assertIn(second.status_code, {201, 429})
        self.assertIn(third.status_code, {409, 429})

        metrics_response = self.client.get("/api/v1/posts/sync/metrics")
        self.assertEqual(metrics_response.status_code, 200)
        self.assertGreaterEqual(metrics_response.data["replay_total"], 0)
        self.assertGreaterEqual(metrics_response.data["conflict_total"], 0)
        self.assertIn("sync_events", metrics_response.data)

    def test_sync_event_ingest_endpoint(self):
        user = User.objects.create_user(username="sync_event_user", password="Password123!")
        Profile.objects.create(user=user, display_name="SyncEventUser")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/sync/events",
            {
                "source": "client",
                "kind": "react_post",
                "endpoint": "/api/v1/posts/1/react",
                "outcome": "retry",
                "status_code": 503,
                "idempotency_key": "abc",
                "detail": "service_unavailable",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(SyncReplayEvent.objects.filter(user=user).count(), 1)

    def test_cleanup_task_deletes_expired_records(self):
        user = User.objects.create_user(username="cleanup_user", password="Password123!")
        Profile.objects.create(user=user, display_name="CleanupUser")
        IdempotencyRecord.objects.create(
            user=user,
            endpoint="posts.create",
            key="expired-key",
            request_hash="x" * 64,
            status_code=201,
            response_body={"ok": True},
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        LinkPreviewCache.objects.create(
            url="https://expired.example.com/item",
            host="expired.example.com",
            title="Expired",
            description="Expired cache",
            source="fallback",
            expires_at=timezone.now() - timedelta(seconds=1),
        )
        result = cleanup_expired_post_caches()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(IdempotencyRecord.objects.filter(key="expired-key").count(), 0)
        self.assertEqual(LinkPreviewCache.objects.filter(host="expired.example.com").count(), 0)

    def test_ai_post_write_uses_ai_throttle_scope(self):
        human = User.objects.create_user(username="human_throttle", password="Password123!")
        Profile.objects.create(user=human, display_name="HumanThrottle")
        ai_user = User.objects.create_user(username="ai_throttle", password="Password123!")
        Profile.objects.create(user=ai_user, display_name="AiThrottle")
        AiAccountProfile.objects.create(user=ai_user, provider_name="local", model_name="gemma-2b")
        view = PostListCreateView()
        self.assertEqual(view.resolve_throttle_scope(human), "post_write")
        self.assertEqual(view.resolve_throttle_scope(ai_user), "post_write_ai")
