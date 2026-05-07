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

from apps.accounts.models import Profile, ProfileActionScore, SiteSetting
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
    UploadedMediaAsset,
)
from apps.posts.tasks import cleanup_expired_post_caches, process_uploaded_video, repair_missing_video_thumbnail
from apps.posts.views import PostListCreateView
from apps.posts.serializers import PostSerializer

User = get_user_model()


class PostsApiTests(APITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_post_serializer_limits_non_parent_posts_to_single_attachment(self):
        user = User.objects.create_user(username="non_parent_limit_user", password="Password123!")
        Profile.objects.create(user=user, display_name="Non Parent Limit")
        self.client.force_authenticate(user=user)
        request = self.client.post(
            "/api/v1/posts/",
            {
                "content": "reply-like payload",
                "parent_post_id": 123,
                "attachments": [
                    {"media_type": "image", "media_url": "https://cdn.example.com/a.jpg"},
                    {"media_type": "image", "media_url": "https://cdn.example.com/b.jpg"},
                ],
            },
            format="json",
        ).wsgi_request
        request.user = user
        serializer = PostSerializer(
            data={
                "content": "reply-like payload",
                "attachments": [
                    {"media_type": "image", "media_url": "https://cdn.example.com/a.jpg"},
                    {"media_type": "image", "media_url": "https://cdn.example.com/b.jpg"},
                ],
                "parent_post_id": 123,
            },
            context={"request": request},
        )
        self.assertFalse(serializer.is_valid())
        self.assertIn("attachments", serializer.errors)
        self.assertIn("only one media attachment", str(serializer.errors["attachments"][0]).lower())

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
            {"action": "report", "content": "This appears misleading and needs moderator review."},
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

    def test_post_create_respects_runtime_character_cap(self):
        settings_obj = SiteSetting.get_solo()
        settings_obj.post_reply_share_char_cap = 10
        settings_obj.save(update_fields=["post_reply_share_char_cap", "updated_at"])
        user = User.objects.create_user(username="char_cap_user", password="Password123!")
        Profile.objects.create(user=user, display_name="CharCapUser")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {"content": "12345678901", "interest_tags": ["tech"]},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot exceed 10 characters", str(response.data.get("content", [""])[0]))

    def test_daily_post_reply_share_limit_blocks_additional_actions(self):
        settings_obj = SiteSetting.get_solo()
        settings_obj.daily_post_reply_share_limit = 1
        settings_obj.save(update_fields=["daily_post_reply_share_limit", "updated_at"])
        actor = User.objects.create_user(username="daily_limit_actor", password="Password123!")
        author = User.objects.create_user(username="daily_limit_author", password="Password123!")
        Profile.objects.create(user=actor, display_name="DailyLimitActor")
        Profile.objects.create(user=author, display_name="DailyLimitAuthor")
        target_post = Post.objects.create(author=author, content="Target for daily limit")
        self.client.force_authenticate(user=actor)

        first = self.client.post(
            "/api/v1/posts/",
            {"content": "first action", "interest_tags": ["tech"]},
            format="json",
        )
        second = self.client.post(
            f"/api/v1/posts/{target_post.id}/react",
            {"action": "reply", "content": "second action should fail"},
            format="json",
        )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 429)
        self.assertIn("Daily post/reply/share limit reached", str(second.data.get("detail", "")))

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

    def test_multiple_image_attachments_allowed_for_main_post(self):
        user = User.objects.create_user(username="multi_image_user", password="Password123!")
        Profile.objects.create(user=user, display_name="MultiImageUser")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {
                "content": "post with two images",
                "attachments": [
                    {"media_type": "image", "media_url": "https://cdn.example.com/one.png"},
                    {"media_type": "image", "media_url": "https://cdn.example.com/two.png"},
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)

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
            {"action": "report", "content": "This post may violate policy due to abusive language."},
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

    def test_report_action_requires_report_details(self):
        reporter = User.objects.create_user(username="reporter_no_detail", password="Password123!")
        Profile.objects.create(user=reporter, display_name="ReporterNoDetail", location="global")
        author = User.objects.create_user(username="author_no_detail", password="Password123!")
        Profile.objects.create(user=author, display_name="AuthorNoDetail")
        post = Post.objects.create(author=author, content="review me without details")
        self.client.force_authenticate(user=reporter)
        response = self.client.post(
            f"/api/v1/posts/{post.id}/react",
            {"action": "report", "content": "   "},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("content", response.data)

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

    def test_user_post_list_returns_full_profile_post_history(self):
        viewer = User.objects.create_user(username="full_profile_viewer", password="Password123!")
        author = User.objects.create_user(username="full_profile_author", password="Password123!")
        Profile.objects.create(user=viewer, display_name="Full Profile Viewer")
        Profile.objects.create(user=author, display_name="Full Profile Author")
        for index in range(65):
            Post.objects.create(author=author, content=f"profile post {index}")
        self.client.force_authenticate(user=viewer)
        response = self.client.get(f"/api/v1/posts/user/{author.id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), 65)

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

    @patch("apps.posts.views.process_uploaded_video.delay")
    @patch("apps.posts.views.probe_video_duration_seconds", return_value=10.0)
    def test_upload_video_queues_processing(self, _mock_duration, mock_delay):
        user = User.objects.create_user(username="video_uploader", password="Password123!")
        Profile.objects.create(user=user, display_name="Video Uploader")
        self.client.force_authenticate(user=user)
        uploaded = SimpleUploadedFile("clip.mp4", b"\x00" * 1024, content_type="video/mp4")
        response = self.client.post("/api/v1/posts/upload-video", {"video": uploaded}, format="multipart")
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.data["media_type"], "video")
        self.assertEqual(response.data["processing_status"], "processing")
        self.assertTrue(str(response.data["media_url"]).endswith(".mp4"))
        self.assertTrue(str(response.data["thumbnail_url"]).endswith(".jpg"))
        mock_delay.assert_called_once()

    @patch("apps.posts.views.probe_video_duration_seconds", return_value=10.0)
    def test_upload_video_rejects_oversized_file(self, _mock_duration):
        user = User.objects.create_user(username="video_size_limit", password="Password123!")
        Profile.objects.create(user=user, display_name="Video Size Limit")
        settings_obj = SiteSetting.get_solo()
        settings_obj.post_video_max_upload_bytes = 128
        settings_obj.save(update_fields=["post_video_max_upload_bytes", "updated_at"])
        self.client.force_authenticate(user=user)
        uploaded = SimpleUploadedFile("clip.mp4", b"\x00" * 256, content_type="video/mp4")
        response = self.client.post("/api/v1/posts/upload-video", {"video": uploaded}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("maximum upload size", str(response.data.get("detail", "")).lower())

    @patch("apps.posts.views.probe_video_duration_seconds", return_value=301.0)
    def test_upload_video_rejects_duration_over_limit(self, _mock_duration):
        user = User.objects.create_user(username="video_duration_limit", password="Password123!")
        Profile.objects.create(user=user, display_name="Video Duration Limit")
        settings_obj = SiteSetting.get_solo()
        settings_obj.post_video_max_duration_seconds = 300
        settings_obj.save(update_fields=["post_video_max_duration_seconds", "updated_at"])
        self.client.force_authenticate(user=user)
        uploaded = SimpleUploadedFile("clip.mp4", b"\x00" * 256, content_type="video/mp4")
        response = self.client.post("/api/v1/posts/upload-video", {"video": uploaded}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("maximum duration", str(response.data.get("detail", "")).lower())

    def test_create_post_accepts_video_attachment(self):
        user = User.objects.create_user(username="video_post_author", password="Password123!")
        Profile.objects.create(user=user, display_name="Video Post Author")
        media_url = "https://cdn.example.com/video.mp4"
        UploadedMediaAsset.objects.create(
            user=user,
            media_type=MediaAttachment.MediaType.VIDEO,
            media_url=media_url,
            media_bytes=128,
            processing_status=UploadedMediaAsset.ProcessingStatus.PROCESSING,
            analysis_status=UploadedMediaAsset.AnalysisStatus.APPROVED,
            thumbnail_url="https://cdn.example.com/video.jpg",
            hls_manifest_url="https://cdn.example.com/video.m3u8",
        )
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {
                "content": "Video post",
                "attachments": [{"media_type": "video", "media_url": media_url}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        post = Post.objects.get(id=response.data["id"])
        attachment = MediaAttachment.objects.filter(post=post).first()
        self.assertIsNotNone(attachment)
        self.assertEqual(attachment.media_type, "video")
        self.assertEqual(attachment.processing_status, UploadedMediaAsset.ProcessingStatus.PROCESSING)
        self.assertTrue(str(attachment.thumbnail_url).endswith(".jpg"))

    def test_create_post_rejects_video_attachment_when_analysis_not_approved(self):
        user = User.objects.create_user(username="video_pending_analysis_author", password="Password123!")
        Profile.objects.create(user=user, display_name="Video Pending Analysis Author")
        media_url = "https://cdn.example.com/video-pending.mp4"
        UploadedMediaAsset.objects.create(
            user=user,
            media_type=MediaAttachment.MediaType.VIDEO,
            media_url=media_url,
            media_bytes=128,
            processing_status=UploadedMediaAsset.ProcessingStatus.READY,
            analysis_status=UploadedMediaAsset.AnalysisStatus.PENDING,
        )
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {
                "content": "Video post pending analysis",
                "attachments": [{"media_type": "video", "media_url": media_url}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("analysis is pending", str(response.data.get("attachments", [""])[0]).lower())

    def test_upload_video_rejects_policy_precheck_filename(self):
        user = User.objects.create_user(username="video_precheck_user", password="Password123!")
        Profile.objects.create(user=user, display_name="Video Precheck User")
        self.client.force_authenticate(user=user)
        uploaded = SimpleUploadedFile("graphic-violence-gore.mp4", b"\x00" * 1024, content_type="video/mp4")
        response = self.client.post("/api/v1/posts/upload-video", {"video": uploaded}, format="multipart")
        self.assertEqual(response.status_code, 422)
        self.assertIn("blocked_categories", response.data)

    def test_create_post_rejects_more_than_twenty_attachments(self):
        user = User.objects.create_user(username="too_many_media", password="Password123!")
        Profile.objects.create(user=user, display_name="TooManyMedia")
        self.client.force_authenticate(user=user)
        attachments = [
            {"media_type": "image", "media_url": f"https://cdn.example.com/image-{index}.png"}
            for index in range(21)
        ]
        response = self.client.post(
            "/api/v1/posts/",
            {"content": "Too many", "attachments": attachments},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("up to 20", str(response.data.get("attachments", [""])[0]).lower())

    def test_create_post_rejects_cumulative_video_bytes_over_limit(self):
        user = User.objects.create_user(username="video_bytes_limit", password="Password123!")
        Profile.objects.create(user=user, display_name="VideoBytesLimit")
        settings_obj = SiteSetting.get_solo()
        settings_obj.post_video_max_upload_bytes = 100
        settings_obj.save(update_fields=["post_video_max_upload_bytes", "updated_at"])
        urls = [
            "https://cdn.example.com/video-1.mp4",
            "https://cdn.example.com/video-2.mp4",
        ]
        for url in urls:
            UploadedMediaAsset.objects.create(
                user=user,
                media_type=MediaAttachment.MediaType.VIDEO,
                media_url=url,
                media_bytes=60,
                processing_status=UploadedMediaAsset.ProcessingStatus.PROCESSING,
                analysis_status=UploadedMediaAsset.AnalysisStatus.APPROVED,
            )
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/posts/",
            {
                "content": "Two large videos",
                "attachments": [{"media_type": "video", "media_url": url} for url in urls],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("total video upload size", str(response.data.get("attachments", [""])[0]).lower())

    def test_reply_accepts_video_attachment(self):
        replier = User.objects.create_user(username="video_reply_user", password="Password123!")
        author = User.objects.create_user(username="video_reply_author", password="Password123!")
        Profile.objects.create(user=replier, display_name="Video Reply User")
        Profile.objects.create(user=author, display_name="Video Reply Author")
        target_post = Post.objects.create(author=author, content="target")
        UploadedMediaAsset.objects.create(
            user=replier,
            media_type=MediaAttachment.MediaType.VIDEO,
            media_url="https://cdn.example.com/reply-video.mp4",
            thumbnail_url="https://cdn.example.com/reply-video.jpg",
            hls_manifest_url="https://cdn.example.com/reply-video.m3u8",
            processing_status=UploadedMediaAsset.ProcessingStatus.PROCESSING,
            analysis_status=UploadedMediaAsset.AnalysisStatus.APPROVED,
            media_bytes=1234,
        )
        self.client.force_authenticate(user=replier)
        response = self.client.post(
            f"/api/v1/posts/{target_post.id}/react",
            {
                "action": "reply",
                "content": "Reply with video",
                "attachments": [{"media_type": "video", "media_url": "https://cdn.example.com/reply-video.mp4"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 201)
        reply_post = Post.objects.filter(parent_post=target_post, author=replier).order_by("-id").first()
        self.assertIsNotNone(reply_post)
        attachment = MediaAttachment.objects.filter(post=reply_post, media_type="video").first()
        self.assertIsNotNone(attachment)
        self.assertEqual(attachment.thumbnail_url, "https://cdn.example.com/reply-video.jpg")
        self.assertEqual(attachment.hls_manifest_url, "https://cdn.example.com/reply-video.m3u8")
        self.assertEqual(attachment.processing_status, UploadedMediaAsset.ProcessingStatus.PROCESSING)
        self.assertEqual(attachment.media_bytes, 1234)

    def test_daily_limit_blocks_video_quote_action(self):
        user = User.objects.create_user(username="video_quote_limit", password="Password123!")
        author = User.objects.create_user(username="video_quote_author", password="Password123!")
        Profile.objects.create(user=user, display_name="Video Quote Limit")
        Profile.objects.create(user=author, display_name="Video Quote Author")
        target = Post.objects.create(author=author, content="Target")
        settings_obj = SiteSetting.get_solo()
        settings_obj.daily_post_reply_share_limit = 1
        settings_obj.save(update_fields=["daily_post_reply_share_limit", "updated_at"])
        Post.objects.create(author=user, content="Consumes daily limit")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            f"/api/v1/posts/{target.id}/react",
            {
                "action": "quote",
                "content": "quote with video",
                "attachments": [{"media_type": "video", "media_url": "https://cdn.example.com/clip.mp4"}],
            },
            format="json",
        )
        self.assertEqual(response.status_code, 429)
        self.assertEqual(response.data.get("limit_scope"), "daily_post_reply_share")


class PostVideoTaskTests(APITestCase):
    def test_process_uploaded_video_returns_error_when_transcode_fails(self):
        saved_name = default_storage.save("posts/test-video.mp4", SimpleUploadedFile("test.mp4", b"raw"))
        with patch("apps.posts.tasks.transcode_video_to_mp4", side_effect=RuntimeError("ffmpeg failed")):
            payload = process_uploaded_video(
                saved_name,
                "posts/test-video.jpg",
                "posts/test-video.m3u8",
                storage_mode="local",
            )
        self.assertEqual(payload.get("status"), "error")

    def test_process_uploaded_video_persists_optimized_video_and_thumbnail(self):
        saved_name = default_storage.save("posts/test-video-ok.mp4", SimpleUploadedFile("test.mp4", b"raw-input"))
        thumbnail_name = "posts/test-video-ok.jpg"
        manifest_name = "posts/test-video-ok.m3u8"

        def fake_transcode(_input_path: str, output_path: str):
            with open(output_path, "wb") as handle:
                handle.write(b"optimized-output")

        def fake_thumbnail(_input_path: str, output_path: str):
            with open(output_path, "wb") as handle:
                handle.write(b"thumb")

        def fake_hls(_input_path: str, output_manifest_path: str, output_segments_dir: str):
            import os

            os.makedirs(output_segments_dir, exist_ok=True)
            with open(output_manifest_path, "wb") as handle:
                handle.write(b"#EXTM3U\n")
            with open(f"{output_segments_dir}/segment-000.ts", "wb") as handle:
                handle.write(b"segment")

        with patch("apps.posts.tasks.transcode_video_to_mp4", side_effect=fake_transcode):
            with patch("apps.posts.tasks.generate_video_thumbnail", side_effect=fake_thumbnail):
                with patch("apps.posts.tasks.transcode_video_to_hls", side_effect=fake_hls):
                    payload = process_uploaded_video(saved_name, thumbnail_name, manifest_name, storage_mode="local")

        self.assertEqual(payload.get("status"), "ok")
        self.assertTrue(default_storage.exists(saved_name))
        self.assertTrue(default_storage.exists(thumbnail_name))
        self.assertTrue(default_storage.exists(manifest_name))

    def test_repair_missing_video_thumbnail_generates_and_persists_thumbnail(self):
        saved_name = default_storage.save("posts/repair-source.mp4", SimpleUploadedFile("repair.mp4", b"video-bytes"))
        media_url = default_storage.url(saved_name)
        asset = UploadedMediaAsset.objects.create(
            user=User.objects.create_user(username="repair_thumb_user", password="Password123!"),
            media_type=MediaAttachment.MediaType.VIDEO,
            media_url=media_url,
            storage_mode="local",
            storage_saved_name=saved_name,
            processing_status=UploadedMediaAsset.ProcessingStatus.READY,
        )
        post = Post.objects.create(author=asset.user, content="Repair thumb post")
        attachment = MediaAttachment.objects.create(post=post, media_type="video", media_url=media_url)

        def fake_thumbnail(_input_path: str, output_path: str):
            with open(output_path, "wb") as handle:
                handle.write(b"thumb-bytes")

        with patch("apps.posts.tasks.generate_video_thumbnail", side_effect=fake_thumbnail):
            payload = repair_missing_video_thumbnail(media_url=media_url, uploaded_asset_id=asset.id)

        self.assertEqual(payload.get("status"), "ok")
        asset.refresh_from_db()
        attachment.refresh_from_db()
        self.assertTrue(str(asset.thumbnail_saved_name).endswith(".jpg"))
        self.assertTrue(default_storage.exists(asset.thumbnail_saved_name))
        self.assertTrue(str(asset.thumbnail_url).endswith(".jpg"))
        self.assertEqual(attachment.thumbnail_url, asset.thumbnail_url)
