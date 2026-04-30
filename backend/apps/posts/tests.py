from django.contrib.auth import get_user_model
from datetime import timedelta
from io import BytesIO
from urllib.parse import urlparse
from django.test import override_settings
from django.utils import timezone
from django.core.files.storage import default_storage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.cache import cache
from rest_framework.test import APITestCase
from unittest.mock import patch
from PIL import Image

from apps.accounts.models import Profile, ProfileActionScore
from apps.ai_accounts.models import AiAccountProfile
from apps.connections.models import Connection
from apps.feed.sentiment_providers import SentimentResult
from apps.moderation.models import ModerationFlag
from apps.posts.models import (
    IdempotencyRecord,
    LinkPreviewCache,
    MediaAttachment,
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
            REMOTE_ADDR="203.0.113.10",
        )
        self.assertEqual(response.status_code, 201)
        self.assertEqual(Post.objects.count(), 1)
        created = Post.objects.first()
        self.assertIsNotNone(created)
        self.assertEqual(created.ip_address, "203.0.113.10")
        self.assertEqual(created.author_id, user.id)
        self.assertIsNotNone(created.created_at)
        self.assertIn(created.sentiment_label, {"positive", "neutral", "negative"})
        self.assertIn("sentiment_label", response.data)
        self.assertIn("sentiment_score", response.data)
        user.profile.refresh_from_db()
        self.assertGreaterEqual(user.profile.rank_last_500_count, 1)

    def test_create_post_persists_tagged_users_and_attachments(self):
        user = User.objects.create_user(username="poster_tags", password="Password123!")
        tagged = User.objects.create_user(username="tagged_user", password="Password123!")
        Profile.objects.create(user=user, display_name="Poster")
        Profile.objects.create(user=tagged, display_name="Tagged")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {
                "content": "Hello @tagged_user",
                "tagged_user_ids": [tagged.id],
                "attachments": [{"media_type": "image", "media_url": "https://cdn.example.com/demo-image.png"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        post = Post.objects.get(id=response.data["id"])
        self.assertEqual(post.tagged_user_ids, [tagged.id])
        self.assertEqual(MediaAttachment.objects.filter(post=post).count(), 1)

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
            REMOTE_ADDR="203.0.113.11",
        )
        like_interaction = PostInteraction.objects.filter(
            post=post,
            user=user,
            action_type=PostInteraction.ActionType.LIKE,
        ).order_by("-id").first()
        self.assertIsNotNone(like_interaction)
        self.assertEqual(like_interaction.ip_address, "203.0.113.11")
        self.assertEqual(like_interaction.user_id, user.id)
        self.assertIsNotNone(like_interaction.created_at)
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
            REMOTE_ADDR="203.0.113.12",
        )
        self.assertEqual(response.status_code, 201)
        reply_interaction = PostInteraction.objects.get(id=response.data["id"])
        self.assertEqual(reply_interaction.ip_address, "203.0.113.12")
        self.assertEqual(reply_interaction.user_id, replier.id)
        self.assertIsNotNone(reply_interaction.created_at)
        reply_post = Post.objects.filter(parent_post=target_post, author=replier).order_by("-id").first()
        self.assertIsNotNone(reply_post)
        self.assertEqual(reply_post.ip_address, "203.0.113.12")
        self.assertEqual(reply_post.author_id, replier.id)
        self.assertIsNotNone(reply_post.created_at)
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

    def test_reply_reaction_accepts_tagged_users_links_and_attachments(self):
        replier = User.objects.create_user(username="reply_plus_user", password="Password123!")
        tagged = User.objects.create_user(username="reply_plus_tagged", password="Password123!")
        author = User.objects.create_user(username="reply_plus_author", password="Password123!")
        Profile.objects.create(user=replier, display_name="ReplyPlusUser")
        Profile.objects.create(user=tagged, display_name="ReplyPlusTagged")
        Profile.objects.create(user=author, display_name="ReplyPlusAuthor")
        target_post = Post.objects.create(author=author, content="Target post")
        self.client.force_authenticate(user=replier)
        response = self.client.post(
            f"/api/v1/posts/{target_post.id}/react",
            {
                "action": "reply",
                "content": "Replying to @reply_plus_tagged",
                "link_url": "https://example.com/details",
                "tagged_user_ids": [tagged.id],
                "attachments": [{"media_type": "image", "media_url": "https://cdn.example.com/reply-image.png"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        interaction = PostInteraction.objects.get(id=response.data["id"])
        self.assertEqual(interaction.tagged_user_ids, [tagged.id])
        self.assertEqual(interaction.link_url, "https://example.com/details")
        self.assertEqual(len(interaction.attachments), 1)
        reply_post = Post.objects.filter(parent_post=target_post, author=replier).order_by("-id").first()
        self.assertIsNotNone(reply_post)
        self.assertEqual(reply_post.tagged_user_ids, [tagged.id])
        self.assertEqual(reply_post.link_url, "https://example.com/details")
        self.assertEqual(MediaAttachment.objects.filter(post=reply_post).count(), 1)

    def test_create_post_link_url_keeps_first_valid_url_when_multiple_provided(self):
        author = User.objects.create_user(username="multi_link_post_author", password="Password123!")
        Profile.objects.create(user=author, display_name="Multi Link Post Author")
        self.client.force_authenticate(user=author)
        response = self.client.post(
            "/api/v1/posts/",
            {
                "content": "Post with multiple links",
                "link_url": "https://first.example.com/a and https://second.example.com/b",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        created = Post.objects.get(id=response.data["id"])
        self.assertEqual(created.link_url, "https://first.example.com/a")

    def test_reply_reaction_link_url_keeps_first_valid_url_when_multiple_provided(self):
        replier = User.objects.create_user(username="multi_link_reply_user", password="Password123!")
        author = User.objects.create_user(username="multi_link_reply_author", password="Password123!")
        Profile.objects.create(user=replier, display_name="Multi Link Reply User")
        Profile.objects.create(user=author, display_name="Multi Link Reply Author")
        target_post = Post.objects.create(author=author, content="Reply target")
        self.client.force_authenticate(user=replier)
        response = self.client.post(
            f"/api/v1/posts/{target_post.id}/react",
            {
                "action": "reply",
                "content": "Reply with multiple links",
                "link_url": "https://first.example.com/reply https://second.example.com/reply",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        interaction = PostInteraction.objects.get(id=response.data["id"])
        self.assertEqual(interaction.link_url, "https://first.example.com/reply")

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
        first = self.client.post(
            f"/api/v1/posts/{target_post.id}/react",
            {"action": "repost"},
            format="json",
            REMOTE_ADDR="203.0.113.13",
        )
        repost_interaction = PostInteraction.objects.filter(
            post=target_post,
            user=user,
            action_type=PostInteraction.ActionType.REPOST,
        ).order_by("-id").first()
        self.assertIsNotNone(repost_interaction)
        self.assertEqual(repost_interaction.ip_address, "203.0.113.13")
        self.assertEqual(repost_interaction.user_id, user.id)
        self.assertIsNotNone(repost_interaction.created_at)
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
        cache.clear()
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
        self.assertIn(third.data.get("spam_rule"), {"repeated_link_limit", None})

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

    def test_multiple_image_attachments_rejected(self):
        user = User.objects.create_user(username="multi_image_user", password="Password123!")
        Profile.objects.create(user=user, display_name="MultiImageUser")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {
                "content": "post with too many images",
                "attachments": [
                    {"media_type": "image", "media_url": "https://cdn.example.com/one.png"},
                    {"media_type": "image", "media_url": "https://cdn.example.com/two.png"},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_upload_post_image_returns_media_url(self):
        user = User.objects.create_user(username="image_upload_user", password="Password123!")
        Profile.objects.create(user=user, display_name="ImageUploadUser")
        self.client.force_authenticate(user=user)
        buffer = BytesIO()
        Image.new("RGB", (40, 40), color=(10, 20, 30)).save(buffer, format="PNG")
        upload = SimpleUploadedFile("upload.png", buffer.getvalue(), content_type="image/png")
        response = self.client.post("/api/v1/posts/upload-image", {"image": upload}, format="multipart")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data.get("media_type"), "image")
        self.assertTrue(str(response.data.get("media_url", "")).strip())

    def test_upload_post_image_rejects_non_image(self):
        user = User.objects.create_user(username="image_upload_invalid", password="Password123!")
        Profile.objects.create(user=user, display_name="ImageUploadInvalid")
        self.client.force_authenticate(user=user)
        upload = SimpleUploadedFile("payload.txt", b"not-an-image", content_type="text/plain")
        response = self.client.post("/api/v1/posts/upload-image", {"image": upload}, format="multipart")
        self.assertEqual(response.status_code, 400)

    @override_settings(UNITE_POST_IMAGE_MAX_BYTES=100)
    def test_upload_post_image_rejects_oversized_file(self):
        user = User.objects.create_user(username="image_upload_too_big", password="Password123!")
        Profile.objects.create(user=user, display_name="ImageUploadTooBig")
        self.client.force_authenticate(user=user)
        buffer = BytesIO()
        Image.new("RGB", (256, 256), color=(255, 255, 255)).save(buffer, format="PNG")
        upload = SimpleUploadedFile("large.png", buffer.getvalue(), content_type="image/png")
        response = self.client.post("/api/v1/posts/upload-image", {"image": upload}, format="multipart")
        self.assertEqual(response.status_code, 400)

    @override_settings(UNITE_POST_IMAGE_MAX_WIDTH=300, UNITE_POST_IMAGE_MAX_HEIGHT=300)
    def test_upload_post_image_resizes_for_mobile(self):
        user = User.objects.create_user(username="image_upload_resize", password="Password123!")
        Profile.objects.create(user=user, display_name="ImageUploadResize")
        self.client.force_authenticate(user=user)
        buffer = BytesIO()
        Image.new("RGB", (1600, 900), color=(120, 140, 160)).save(buffer, format="PNG")
        upload = SimpleUploadedFile("wide.png", buffer.getvalue(), content_type="image/png")
        response = self.client.post("/api/v1/posts/upload-image", {"image": upload}, format="multipart")
        self.assertEqual(response.status_code, 201)
        media_url = str(response.data.get("media_url", "")).strip()
        self.assertTrue(media_url)
        path = urlparse(media_url).path
        relative_path = path.split("/media/", 1)[-1]
        with default_storage.open(relative_path, "rb") as uploaded_file:
            uploaded_image = Image.open(uploaded_file)
            width, height = uploaded_image.size
        self.assertLessEqual(width, 300)
        self.assertLessEqual(height, 300)

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

    @override_settings(UNITE_ENABLE_REMOTE_LINK_FETCH=True)
    @patch("apps.posts.services.urlopen")
    def test_link_preview_includes_remote_og_image(self, mock_urlopen):
        class _MockResponse:
            def __init__(self, body: str):
                self.headers = {"Content-Type": "text/html; charset=utf-8"}
                self._body = body.encode("utf-8")

            def read(self, *_args, **_kwargs):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        mock_urlopen.return_value = _MockResponse(
            """
            <html>
              <head>
                <title>Remote Preview Title</title>
                <meta property="og:description" content="Remote preview description" />
                <meta property="og:image" content="/assets/preview.png" />
              </head>
            </html>
            """
        )

        user = User.objects.create_user(username="og_image_user", password="Password123!")
        Profile.objects.create(user=user, display_name="OgImageUser")
        self.client.force_authenticate(user=user)
        payload = {
            "content": "Preview with image",
            "link_url": "https://example.com/with-preview",
        }
        response = self.client.post("/api/v1/posts/", payload, format="json")
        self.assertEqual(response.status_code, 201)
        preview = Post.objects.get(id=response.data["id"]).link_preview
        self.assertEqual(preview.get("title"), "Remote Preview Title")
        self.assertEqual(preview.get("description"), "Remote preview description")
        self.assertEqual(preview.get("image_url"), "https://example.com/assets/preview.png")

    @override_settings(UNITE_ENABLE_REMOTE_LINK_FETCH=True)
    @patch("apps.posts.services.urlopen")
    def test_link_preview_supports_twitter_image_src_tag(self, mock_urlopen):
        class _MockResponse:
            def __init__(self, body: str):
                self.headers = {"Content-Type": "text/html; charset=utf-8"}
                self._body = body.encode("utf-8")

            def read(self, *_args, **_kwargs):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        mock_urlopen.return_value = _MockResponse(
            """
            <html>
              <head>
                <title>Twitter Image Tag</title>
                <meta content="https://cdn.example.com/twitter-image.jpg" name="twitter:image:src" />
              </head>
            </html>
            """
        )

        user = User.objects.create_user(username="twitter_image_user", password="Password123!")
        Profile.objects.create(user=user, display_name="TwitterImageUser")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {
                "content": "Preview via twitter image tag",
                "link_url": "https://example.com/twitter-image-tag",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        preview = Post.objects.get(id=response.data["id"]).link_preview
        self.assertEqual(preview.get("image_url"), "https://cdn.example.com/twitter-image.jpg")

    @override_settings(UNITE_ENABLE_REMOTE_LINK_FETCH=True)
    @patch("apps.posts.services.urlopen")
    def test_link_preview_supports_itemprop_image_tag(self, mock_urlopen):
        class _MockResponse:
            def __init__(self, body: str):
                self.headers = {"Content-Type": "text/html; charset=utf-8"}
                self._body = body.encode("utf-8")

            def read(self, *_args, **_kwargs):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        mock_urlopen.return_value = _MockResponse(
            """
            <html>
              <head>
                <meta itemprop="image" content="/images/preview-itemprop.png" />
              </head>
            </html>
            """
        )

        user = User.objects.create_user(username="itemprop_image_user", password="Password123!")
        Profile.objects.create(user=user, display_name="ItemPropImageUser")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {
                "content": "Preview via itemprop image",
                "link_url": "https://www.google.com",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        preview = Post.objects.get(id=response.data["id"]).link_preview
        self.assertEqual(preview.get("image_url"), "https://www.google.com/images/preview-itemprop.png")

    @override_settings(UNITE_ENABLE_REMOTE_LINK_FETCH=True)
    @patch("apps.posts.services.urlopen")
    def test_link_preview_uses_origin_page_image_when_search_page_has_no_image(self, mock_urlopen):
        class _MockResponse:
            def __init__(self, body: str):
                self.headers = {"Content-Type": "text/html; charset=utf-8"}
                self._body = body.encode("utf-8")

            def read(self, *_args, **_kwargs):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        def _urlopen_side_effect(request, timeout=3):
            target_url = str(getattr(request, "full_url", request))
            if target_url.startswith("https://www.google.com/search"):
                return _MockResponse("<html><head><title>Google Search</title></head></html>")
            if target_url == "https://www.google.com/":
                return _MockResponse(
                    """
                    <html>
                      <head>
                        <meta itemprop="image" content="/images/branding/googleg/1x/googleg_standard_color_128dp.png" />
                      </head>
                    </html>
                    """
                )
            raise Exception(f"unexpected url {target_url}")

        mock_urlopen.side_effect = _urlopen_side_effect
        user = User.objects.create_user(username="origin_image_user", password="Password123!")
        Profile.objects.create(user=user, display_name="OriginImageUser")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {
                "content": "Search page with origin image fallback",
                "link_url": "https://www.google.com/search?q=ai+new+onboarding+flow+53",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        preview = Post.objects.get(id=response.data["id"]).link_preview
        self.assertEqual(
            preview.get("image_url"),
            "https://www.google.com/images/branding/googleg/1x/googleg_standard_color_128dp.png",
        )

    @override_settings(UNITE_ENABLE_REMOTE_LINK_FETCH=True)
    @patch("apps.posts.services.urlopen")
    def test_link_preview_supports_link_rel_icon_fallback(self, mock_urlopen):
        class _MockResponse:
            def __init__(self, body: str):
                self.headers = {"Content-Type": "text/html; charset=utf-8"}
                self._body = body.encode("utf-8")

            def read(self, *_args, **_kwargs):
                return self._body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

        mock_urlopen.return_value = _MockResponse(
            """
            <html>
              <head>
                <title>Icon Rel Page</title>
                <link rel="icon" href="/favicon-test.ico" />
              </head>
            </html>
            """
        )

        user = User.objects.create_user(username="rel_icon_user", password="Password123!")
        Profile.objects.create(user=user, display_name="RelIconUser")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {
                "content": "Preview via rel icon",
                "link_url": "https://example.com/icon-rel",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        preview = Post.objects.get(id=response.data["id"]).link_preview
        self.assertEqual(preview.get("image_url"), "")

    @override_settings(UNITE_ENABLE_REMOTE_LINK_FETCH=True)
    @patch("apps.posts.services.urlopen")
    def test_link_preview_uses_default_favicon_when_remote_fetch_fails(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("blocked")
        user = User.objects.create_user(username="favicon_fallback_user", password="Password123!")
        Profile.objects.create(user=user, display_name="FaviconFallbackUser")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {
                "content": "Preview fallback icon",
                "link_url": "https://www.ecosia.org/search?q=science+incident+review+102",
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        preview = Post.objects.get(id=response.data["id"]).link_preview
        self.assertEqual(preview.get("image_url"), "")

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

    @override_settings(
        UNITE_SPAM_BURST_WINDOW_SECONDS=0,
        UNITE_SPAM_LINK_WINDOW_SECONDS=0,
        UNITE_SPAM_BURST_MAX_POSTS=1000,
        UNITE_SPAM_LINK_MAX_POSTS=1000,
    )
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
        self.assertIn(first.status_code, {201, 429})
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

    def test_user_post_list_hides_private_profile_posts_for_non_connection(self):
        viewer = User.objects.create_user(username="posts_private_viewer", password="Password123!")
        author = User.objects.create_user(username="posts_private_author", password="Password123!")
        Profile.objects.create(user=viewer, display_name="Posts Private Viewer")
        Profile.objects.create(user=author, display_name="Posts Private Author", is_private_profile=True)
        post = Post.objects.create(author=author, content="private post")
        self.client.force_authenticate(user=viewer)
        response = self.client.get(f"/api/v1/posts/user/{author.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

        Connection.objects.create(requester=viewer, recipient=author, status=Connection.Status.ACCEPTED)
        connected_response = self.client.get(f"/api/v1/posts/user/{author.id}")
        self.assertEqual(connected_response.status_code, 200)
        self.assertTrue(any(int(item["id"]) == post.id for item in connected_response.data))

    def test_post_detail_hides_replies_from_blocked_authors(self):
        viewer = User.objects.create_user(username="posts_block_viewer", password="Password123!")
        author = User.objects.create_user(username="posts_block_author", password="Password123!")
        blocked_replier = User.objects.create_user(username="posts_block_replier", password="Password123!")
        Profile.objects.create(user=viewer, display_name="Posts Block Viewer")
        Profile.objects.create(user=author, display_name="Posts Block Author")
        Profile.objects.create(user=blocked_replier, display_name="Posts Block Replier")
        root_post = Post.objects.create(author=author, content="root post")
        blocked_reply = Post.objects.create(author=blocked_replier, parent_post=root_post, content="blocked reply")
        Connection.objects.create(requester=viewer, recipient=blocked_replier, status=Connection.Status.BLOCKED)
        self.client.force_authenticate(user=viewer)
        response = self.client.get(f"/api/v1/posts/{root_post.id}")
        self.assertEqual(response.status_code, 200)
        reply_ids = {int(item["id"]) for item in response.data["replies"]}
        self.assertNotIn(blocked_reply.id, reply_ids)
