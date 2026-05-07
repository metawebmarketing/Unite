from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from datetime import timedelta
from rest_framework.test import APITestCase
from unittest.mock import patch

from apps.accounts.models import Profile
from apps.ads.models import AdSlotConfig
from apps.ai_accounts.models import AiAccountProfile
from apps.connections.models import Connection
from apps.feed.sentiment_providers import CardiffLocalSentimentProvider
from apps.moderation.models import ModerationFlag
from apps.posts.models import Post
from apps.feed.ranking import score_feed_items

User = get_user_model()


class FeedApiTests(APITestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_suggestions_are_injected_every_three_items(self):
        user = User.objects.create_user(username="feed_user", password="Password123!")
        Profile.objects.create(user=user, display_name="FeedUser")
        author = User.objects.create_user(username="feed_author", password="Password123!")
        Profile.objects.create(user=author, display_name="FeedAuthor")
        self.client.force_authenticate(user=user)
        for index in range(6):
            Post.objects.create(author=author, content=f"post {index}")

        response = self.client.get("/api/v1/feed/?mode=both")
        self.assertEqual(response.status_code, 200)
        suggestion_count = sum(1 for item in response.data["items"] if item["item_type"] == "suggestion")
        self.assertEqual(suggestion_count, 2)

    def test_cursor_pagination_keeps_deterministic_cadence(self):
        user = User.objects.create_user(username="feed_cursor", password="Password123!")
        Profile.objects.create(user=user, display_name="FeedCursor")
        author = User.objects.create_user(username="feed_cursor_author", password="Password123!")
        Profile.objects.create(user=author, display_name="FeedCursorAuthor")
        self.client.force_authenticate(user=user)
        for index in range(7):
            Post.objects.create(author=author, content=f"cursor post {index}")

        first_response = self.client.get("/api/v1/feed/?mode=both&page_size=4")
        self.assertEqual(first_response.status_code, 200)
        self.assertTrue(first_response.data["has_more"])
        self.assertEqual(
            sum(1 for item in first_response.data["items"] if item["item_type"] == "suggestion"),
            1,
        )

        second_response = self.client.get(
            f"/api/v1/feed/?mode=both&page_size=4&cursor={first_response.data['next_cursor']}"
        )
        self.assertEqual(second_response.status_code, 200)
        self.assertFalse(second_response.data["has_more"])
        self.assertEqual(
            sum(1 for item in second_response.data["items"] if item["item_type"] == "suggestion"),
            1,
        )

    def test_feed_endpoint_returns_cache_headers(self):
        user = User.objects.create_user(username="cache_feed_user", password="Password123!")
        Profile.objects.create(user=user, display_name="CacheFeedUser")
        author = User.objects.create_user(username="cache_feed_author", password="Password123!")
        Profile.objects.create(user=author, display_name="CacheFeedAuthor")
        self.client.force_authenticate(user=user)
        for index in range(3):
            Post.objects.create(author=author, content=f"cache post {index}")

        first_response = self.client.get("/api/v1/feed/?mode=both&page_size=3")
        second_response = self.client.get("/api/v1/feed/?mode=both&page_size=3")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response["X-Feed-Cache"], "MISS")
        self.assertEqual(second_response["X-Feed-Cache"], "HIT")

    def test_feed_fields_query_param_limits_post_payload(self):
        user = User.objects.create_user(username="feed_fields_user", password="Password123!")
        Profile.objects.create(user=user, display_name="FeedFieldsUser")
        author = User.objects.create_user(username="feed_fields_author", password="Password123!")
        Profile.objects.create(user=author, display_name="FeedFieldsAuthor")
        self.client.force_authenticate(user=user)
        Post.objects.create(author=author, content="field filtered post", interest_tags=["tech"])

        response = self.client.get("/api/v1/feed/?mode=both&page_size=1&fields=id,content")
        self.assertEqual(response.status_code, 200)
        post_items = [item for item in response.data["items"] if item["item_type"] == "post"]
        self.assertEqual(len(post_items), 1)
        self.assertEqual(set(post_items[0]["data"].keys()), {"id", "content"})

    def test_feed_cache_key_varies_by_requested_fields(self):
        user = User.objects.create_user(username="cache_fields_user", password="Password123!")
        Profile.objects.create(user=user, display_name="CacheFieldsUser")
        self.client.force_authenticate(user=user)
        Post.objects.create(author=user, content="cache key field post")

        first_response = self.client.get("/api/v1/feed/?mode=both&page_size=1&fields=id")
        second_response = self.client.get("/api/v1/feed/?mode=both&page_size=1&fields=content")

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertEqual(first_response["X-Feed-Cache"], "MISS")
        self.assertEqual(second_response["X-Feed-Cache"], "MISS")

    def test_interest_mode_requires_tag(self):
        user = User.objects.create_user(username="interest_mode_user", password="Password123!")
        Profile.objects.create(user=user, display_name="InterestModeUser")
        self.client.force_authenticate(user=user)
        response = self.client.get("/api/v1/feed/?mode=interest")
        self.assertEqual(response.status_code, 400)

    def test_interest_mode_filters_feed_items(self):
        user = User.objects.create_user(username="interest_filter_user", password="Password123!")
        Profile.objects.create(user=user, display_name="InterestFilterUser")
        author = User.objects.create_user(username="interest_filter_author", password="Password123!")
        Profile.objects.create(user=author, display_name="InterestFilterAuthor")
        self.client.force_authenticate(user=user)
        Post.objects.create(author=author, content="tech post", interest_tags=["tech"])
        Post.objects.create(author=author, content="design post", interest_tags=["design"])

        response = self.client.get("/api/v1/feed/?mode=interest&interest_tag=tech")
        self.assertEqual(response.status_code, 200)
        post_items = [item for item in response.data["items"] if item["item_type"] == "post"]
        self.assertTrue(post_items)
        self.assertTrue(all("tech" in [tag.lower() for tag in item["data"]["interest_tags"]] for item in post_items))

    def test_interest_tag_boost_reorders_posts_in_both_mode(self):
        user = User.objects.create_user(username="interest_rank_user", password="Password123!")
        Profile.objects.create(
            user=user,
            display_name="InterestRankUser",
            algorithm_vector={"interest_tokens": []},
        )
        author = User.objects.create_user(username="interest_rank_author", password="Password123!")
        Profile.objects.create(user=author, display_name="InterestRankAuthor")
        self.client.force_authenticate(user=user)
        Post.objects.create(author=author, content="tech older", interest_tags=["tech"])
        Post.objects.create(author=author, content="design newer", interest_tags=["design"])

        response = self.client.get("/api/v1/feed/?mode=both&page_size=2&interest_tag=tech")
        self.assertEqual(response.status_code, 200)
        post_items = [item for item in response.data["items"] if item["item_type"] == "post"]
        self.assertEqual(post_items[0]["data"]["content"], "tech older")

    def test_feed_payload_includes_sentiment_fields(self):
        user = User.objects.create_user(username="sentiment_feed_user", password="Password123!")
        Profile.objects.create(user=user, display_name="SentimentFeedUser")
        author = User.objects.create_user(username="sentiment_feed_author", password="Password123!")
        Profile.objects.create(user=author, display_name="SentimentFeedAuthor")
        self.client.force_authenticate(user=user)
        Post.objects.create(
            author=author,
            content="A positive and constructive update.",
            interest_tags=["tech"],
            sentiment_label="positive",
            sentiment_score=0.75,
        )

        response = self.client.get("/api/v1/feed/?mode=both&page_size=1")
        self.assertEqual(response.status_code, 200)
        post_items = [item for item in response.data["items"] if item["item_type"] == "post"]
        self.assertEqual(len(post_items), 1)
        self.assertIn("sentiment_label", post_items[0]["data"])
        self.assertIn("sentiment_score", post_items[0]["data"])
        self.assertIn("author_profile_rank_score", post_items[0]["data"])

    def test_cardiff_negative_non_hostile_maps_to_neutral(self):
        provider = CardiffLocalSentimentProvider(
            model_name="cardiffnlp/twitter-xlm-roberta-base-sentiment",
            model_path="cardiffnlp/twitter-xlm-roberta-base-sentiment",
            local_files_only=True,
        )

        with patch.object(provider, "_get_pipeline", return_value=lambda *_args, **_kwargs: [{"label": "negative", "score": 0.91}]):
            result = provider.analyze_text(
                "I disagree with this approach for fitness; the missing fallback is risky in high-traffic windows."
            )

        self.assertEqual(result.label, "neutral")
        self.assertEqual(result.score, 0.0)

    def test_cardiff_negative_hostile_stays_negative(self):
        provider = CardiffLocalSentimentProvider(
            model_name="cardiffnlp/twitter-xlm-roberta-base-sentiment",
            model_path="cardiffnlp/twitter-xlm-roberta-base-sentiment",
            local_files_only=True,
        )

        with patch.object(provider, "_get_pipeline", return_value=lambda *_args, **_kwargs: [{"label": "negative", "score": 0.88}]):
            result = provider.analyze_text("You are an idiot and your argument is worthless.")

        self.assertEqual(result.label, "negative")
        self.assertLess(result.score, 0.0)

    def test_profile_interest_tokens_influence_ranking(self):
        user = User.objects.create_user(username="profile_interest_rank_user", password="Password123!")
        Profile.objects.create(
            user=user,
            display_name="ProfileInterestRankUser",
            interests=["tech", "science", "music", "travel", "ai"],
            algorithm_vector={},
        )
        author = User.objects.create_user(username="profile_interest_author", password="Password123!")
        Profile.objects.create(user=author, display_name="ProfileInterestAuthor")
        self.client.force_authenticate(user=user)
        Post.objects.create(author=author, content="tech older", interest_tags=["tech"])
        Post.objects.create(author=author, content="design newer", interest_tags=["design"])

        response = self.client.get("/api/v1/feed/?mode=both&page_size=2")
        self.assertEqual(response.status_code, 200)
        post_items = [item for item in response.data["items"] if item["item_type"] == "post"]
        self.assertEqual(post_items[0]["data"]["content"], "tech older")

    def test_negative_sentiment_is_downranked_despite_engagement(self):
        ranked = score_feed_items(
            user_context={"interest_tokens": []},
            candidate_posts=[
                {
                    "id": 1,
                    "interest_tags": [],
                    "like_count": 14,
                    "reply_count": 6,
                    "sentiment_score": -0.9,
                },
                {
                    "id": 2,
                    "interest_tags": [],
                    "like_count": 2,
                    "reply_count": 1,
                    "sentiment_score": 0.45,
                },
                {
                    "id": 3,
                    "interest_tags": [],
                    "like_count": 2,
                    "reply_count": 1,
                    "sentiment_score": 0.0,
                },
            ],
        )

        ordered_ids = [int(item["id"]) for item in ranked]
        self.assertEqual(ordered_ids[0], 2)
        self.assertEqual(ordered_ids[1], 3)
        self.assertEqual(ordered_ids[2], 1)

    def test_author_profile_score_influences_ranking(self):
        ranked = score_feed_items(
            user_context={"interest_tokens": []},
            candidate_posts=[
                {
                    "id": 11,
                    "interest_tags": [],
                    "like_count": 3,
                    "reply_count": 2,
                    "sentiment_score": 0.0,
                    "author_profile_score": -4.5,
                },
                {
                    "id": 12,
                    "interest_tags": [],
                    "like_count": 3,
                    "reply_count": 2,
                    "sentiment_score": 0.0,
                    "author_profile_score": 2.8,
                },
            ],
        )

        ordered_ids = [int(item["id"]) for item in ranked]
        self.assertEqual(ordered_ids[0], 12)
        self.assertEqual(ordered_ids[1], 11)

    def test_author_profile_score_outweighs_high_engagement(self):
        ranked = score_feed_items(
            user_context={"interest_tokens": []},
            candidate_posts=[
                {
                    "id": 21,
                    "interest_tags": [],
                    "like_count": 250,
                    "reply_count": 120,
                    "sentiment_score": 0.0,
                    "author_profile_score": -4.2,
                },
                {
                    "id": 22,
                    "interest_tags": [],
                    "like_count": 0,
                    "reply_count": 0,
                    "sentiment_score": 0.0,
                    "author_profile_score": 3.5,
                },
            ],
        )

        ordered_ids = [int(item["id"]) for item in ranked]
        self.assertEqual(ordered_ids[0], 22)
        self.assertEqual(ordered_ids[1], 21)

    def test_negative_baseline_never_outranks_positive_baseline_even_when_viral(self):
        ranked = score_feed_items(
            user_context={
                "interest_tokens": ["viral"],
                "interest_weights": {"viral": 10_000},
                "active_interest_tag": "viral",
            },
            candidate_posts=[
                {
                    "id": 31,
                    "interest_tags": ["viral"],
                    "like_count": 100_000,
                    "reply_count": 100_000,
                    "sentiment_score": -0.1,
                    "author_profile_score": 0.0,
                },
                {
                    "id": 32,
                    "interest_tags": [],
                    "like_count": 100,
                    "reply_count": 100,
                    "sentiment_score": 0.3,
                    "author_profile_score": 1.0,
                },
            ],
        )

        ordered_ids = [int(item["id"]) for item in ranked]
        self.assertEqual(ordered_ids[0], 32)
        self.assertEqual(ordered_ids[1], 31)
        self.assertEqual(ranked[0]["quality_band"], "non_negative_band")
        self.assertEqual(ranked[1]["quality_band"], "negative_band")

    def test_quality_band_priority_orders_positive_then_neutral_then_negative(self):
        ranked = score_feed_items(
            user_context={"interest_tokens": []},
            candidate_posts=[
                {
                    "id": 41,
                    "interest_tags": [],
                    "like_count": 0,
                    "reply_count": 0,
                    "sentiment_score": 0.2,
                    "author_profile_score": 0.0,
                },
                {
                    "id": 42,
                    "interest_tags": [],
                    "like_count": 0,
                    "reply_count": 0,
                    "sentiment_score": 0.0,
                    "author_profile_score": -0.2,
                },
                {
                    "id": 43,
                    "interest_tags": [],
                    "like_count": 100_000,
                    "reply_count": 100_000,
                    "sentiment_score": -0.1,
                    "author_profile_score": 0.0,
                },
            ],
        )

        ordered_ids = [int(item["id"]) for item in ranked]
        self.assertEqual(ordered_ids, [41, 42, 43])
        self.assertEqual(
            [item["quality_band"] for item in ranked],
            ["non_negative_band", "non_negative_band", "negative_band"],
        )

    def test_negative_sentiment_remains_in_negative_band_despite_author_boost(self):
        ranked = score_feed_items(
            user_context={"interest_tokens": []},
            candidate_posts=[
                {
                    "id": 51,
                    "interest_tags": [],
                    "like_count": 0,
                    "reply_count": 0,
                    "sentiment_score": -0.95,
                    "author_profile_score": 5.0,
                },
                {
                    "id": 52,
                    "interest_tags": [],
                    "like_count": 0,
                    "reply_count": 0,
                    "sentiment_score": 0.0,
                    "author_profile_score": 0.0,
                },
            ],
        )

        ordered_ids = [int(item["id"]) for item in ranked]
        self.assertEqual(ordered_ids[0], 52)
        negative_item = next(item for item in ranked if int(item["id"]) == 51)
        self.assertEqual(negative_item["quality_band"], "negative_band")

    def test_negative_posts_are_not_truncated_from_paginated_feed(self):
        viewer = User.objects.create_user(username="negative_page_viewer", password="Password123!")
        author = User.objects.create_user(username="negative_page_author", password="Password123!")
        Profile.objects.create(user=viewer, display_name="NegativePageViewer")
        Profile.objects.create(user=author, display_name="NegativePageAuthor")
        self.client.force_authenticate(user=viewer)

        negative_ids: list[int] = []
        for index in range(2):
            negative_post = Post.objects.create(
                author=author,
                content=f"negative post {index}",
                sentiment_label="negative",
                sentiment_score=-0.9,
                analysis_status=Post.AnalysisStatus.APPROVED,
                needs_analysis_refresh=False,
            )
            negative_ids.append(int(negative_post.id))
        Post.objects.filter(id__in=negative_ids).update(created_at=timezone.now() - timedelta(days=30))

        for index in range(22):
            Post.objects.create(
                author=author,
                content=f"non-negative post {index}",
                sentiment_label="neutral",
                sentiment_score=0.0,
                analysis_status=Post.AnalysisStatus.APPROVED,
                needs_analysis_refresh=False,
            )

        first_response = self.client.get("/api/v1/feed/?mode=both&page_size=20")
        self.assertEqual(first_response.status_code, 200)
        cursor = first_response.data.get("next_cursor")
        self.assertTrue(cursor)

        second_response = self.client.get(f"/api/v1/feed/?mode=both&page_size=20&cursor={cursor}")
        self.assertEqual(second_response.status_code, 200)

        seen_ids = [
            int(item["data"]["id"])
            for item in [*first_response.data["items"], *second_response.data["items"]]
            if item["item_type"] == "post"
        ]
        self.assertEqual(len(seen_ids), len(set(seen_ids)))
        for negative_id in negative_ids:
            self.assertIn(negative_id, seen_ids)

    def test_profile_interest_weights_influence_ranking(self):
        user = User.objects.create_user(username="profile_weight_rank_user", password="Password123!")
        Profile.objects.create(
            user=user,
            display_name="ProfileWeightRankUser",
            interests=[],
            algorithm_vector={"interest_weights": {"tech": 6.5, "design": 0.1}},
        )
        author = User.objects.create_user(username="profile_weight_author", password="Password123!")
        Profile.objects.create(user=author, display_name="ProfileWeightAuthor")
        self.client.force_authenticate(user=user)
        Post.objects.create(author=author, content="tech older", interest_tags=["tech"])
        Post.objects.create(author=author, content="design newer", interest_tags=["design"])

        response = self.client.get("/api/v1/feed/?mode=both&page_size=2")
        self.assertEqual(response.status_code, 200)
        post_items = [item for item in response.data["items"] if item["item_type"] == "post"]
        self.assertEqual(post_items[0]["data"]["content"], "tech older")

    @patch("apps.feed.views.ensure_post_analysis")
    def test_media_action_terms_influence_ranking(self, ensure_post_analysis_mock):
        ensure_post_analysis_mock.return_value = None
        user = User.objects.create_user(username="media_terms_rank_user", password="Password123!")
        Profile.objects.create(
            user=user,
            display_name="MediaTermsRankUser",
            interests=["gaming"],
            algorithm_vector={"interest_tokens": ["gaming"]},
        )
        author = User.objects.create_user(username="media_terms_author", password="Password123!")
        Profile.objects.create(user=author, display_name="MediaTermsAuthor")
        self.client.force_authenticate(user=user)
        plain_post = Post.objects.create(
            author=author,
            content="plain",
            interest_tags=["news"],
            analysis_status=Post.AnalysisStatus.APPROVED,
            needs_analysis_refresh=False,
        )
        media_post = Post.objects.create(
            author=author,
            content="media enriched",
            interest_tags=["news"],
            analysis_terms=["gaming", "controller", "gameplay"],
            analysis_status=Post.AnalysisStatus.APPROVED,
            needs_analysis_refresh=False,
        )
        response = self.client.get("/api/v1/feed/?mode=both&page_size=2")
        self.assertEqual(response.status_code, 200)
        post_items = [item for item in response.data["items"] if item["item_type"] == "post"]
        self.assertEqual(post_items[0]["data"]["id"], media_post.id)
        self.assertIn(plain_post.id, [item["data"]["id"] for item in post_items])

    def test_feed_read_repair_runs_sentiment_once_per_post_version(self):
        user = User.objects.create_user(username="repair_once_user", password="Password123!")
        Profile.objects.create(user=user, display_name="RepairOnceUser")
        author = User.objects.create_user(username="repair_once_author", password="Password123!")
        Profile.objects.create(user=author, display_name="RepairOnceAuthor")
        self.client.force_authenticate(user=user)
        Post.objects.create(author=author, content="Needs first-time analysis")
        with patch("apps.posts.media_intelligence.ensure_post_sentiment") as ensure_sentiment_mock:
            ensure_sentiment_mock.return_value = ("neutral", 0.0)
            first = self.client.get("/api/v1/feed/?mode=both&page_size=1&fields=id,content")
            second = self.client.get("/api/v1/feed/?mode=both&page_size=1&fields=id")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(ensure_sentiment_mock.call_count, 1)

    def test_cursor_pagination_stays_stable_when_rank_order_changes(self):
        user = User.objects.create_user(username="rank_cursor_user", password="Password123!")
        Profile.objects.create(
            user=user,
            display_name="RankCursorUser",
            algorithm_vector={"interest_tokens": []},
        )
        author = User.objects.create_user(username="rank_cursor_author", password="Password123!")
        Profile.objects.create(user=author, display_name="RankCursorAuthor")
        self.client.force_authenticate(user=user)
        Post.objects.create(author=author, content="post 1 tech", interest_tags=["tech"])
        Post.objects.create(author=author, content="post 2 design", interest_tags=["design"])
        Post.objects.create(author=author, content="post 3 tech", interest_tags=["tech"])
        Post.objects.create(author=author, content="post 4 design", interest_tags=["design"])
        Post.objects.create(author=author, content="post 5 tech", interest_tags=["tech"])

        first_response = self.client.get("/api/v1/feed/?mode=both&page_size=2&interest_tag=tech")
        self.assertEqual(first_response.status_code, 200)
        self.assertTrue(first_response.data["has_more"])
        first_ids = [
            int(item["data"]["id"])
            for item in first_response.data["items"]
            if item["item_type"] == "post" and item["data"].get("id") is not None
        ]

        second_response = self.client.get(
            f"/api/v1/feed/?mode=both&page_size=2&interest_tag=tech&cursor={first_response.data['next_cursor']}"
        )
        self.assertEqual(second_response.status_code, 200)
        second_ids = [
            int(item["data"]["id"])
            for item in second_response.data["items"]
            if item["item_type"] == "post" and item["data"].get("id") is not None
        ]

        self.assertEqual(len(set(first_ids).intersection(second_ids)), 0)

    def test_feed_includes_ai_author_label_fields(self):
        user = User.objects.create_user(username="feed_human", password="Password123!")
        Profile.objects.create(user=user, display_name="FeedHuman")
        ai_user = User.objects.create_user(username="ai_feed_author", password="Password123!")
        Profile.objects.create(user=ai_user, display_name="AI Feed Author")
        AiAccountProfile.objects.create(user=ai_user, provider_name="local", model_name="gemma-2b")
        self.client.force_authenticate(user=user)
        Post.objects.create(author=ai_user, content="ai authored post", interest_tags=["tech"])

        response = self.client.get("/api/v1/feed/?mode=both&page_size=5")
        self.assertEqual(response.status_code, 200)
        post_items = [item for item in response.data["items"] if item["item_type"] == "post"]
        self.assertTrue(post_items)
        self.assertTrue(post_items[0]["data"]["author_is_ai"])
        self.assertTrue(post_items[0]["data"]["author_ai_badge_enabled"])

    @override_settings(UNITE_MAX_INJECTION_RATIO=0.5)
    def test_injection_guardrail_caps_total_injected_density(self):
        user = User.objects.create_user(username="density_guard_user", password="Password123!")
        Profile.objects.create(user=user, display_name="DensityGuardUser")
        author = User.objects.create_user(username="density_guard_author", password="Password123!")
        Profile.objects.create(user=author, display_name="DensityGuardAuthor")
        self.client.force_authenticate(user=user)
        AdSlotConfig.objects.create(region_code="global", interval=1, enabled=True)
        for index in range(4):
            Post.objects.create(author=author, content=f"density post {index}")

        response = self.client.get("/api/v1/feed/?mode=both&page_size=4")
        self.assertEqual(response.status_code, 200)
        injected_count = sum(1 for item in response.data["items"] if item["item_type"] in {"suggestion", "ad"})
        self.assertLessEqual(injected_count, 2)

    def test_suggestions_include_interest_based_candidate_data(self):
        user = User.objects.create_user(username="suggest_user", password="Password123!")
        Profile.objects.create(user=user, display_name="SuggestUser", interests=["tech", "design"])
        suggested = User.objects.create_user(username="candidate_user", password="Password123!")
        Profile.objects.create(user=suggested, display_name="CandidateUser", interests=["tech"])
        author = User.objects.create_user(username="suggest_posts_author", password="Password123!")
        Profile.objects.create(user=author, display_name="SuggestPostsAuthor")
        self.client.force_authenticate(user=user)
        for index in range(3):
            Post.objects.create(author=author, content=f"post {index}")

        response = self.client.get("/api/v1/feed/?mode=both&page_size=3")
        self.assertEqual(response.status_code, 200)
        suggestions = [item for item in response.data["items"] if item["item_type"] == "suggestion"]
        self.assertTrue(suggestions)
        self.assertEqual(suggestions[0]["data"]["display_name"], "CandidateUser")
        self.assertGreaterEqual(suggestions[0]["data"]["shared_interest_count"], 1)

    def test_suggestions_exclude_already_connected_users(self):
        user = User.objects.create_user(username="suggest_connected_user", password="Password123!")
        Profile.objects.create(user=user, display_name="SuggestConnected", interests=["tech"])
        connected = User.objects.create_user(username="already_connected", password="Password123!")
        Profile.objects.create(user=connected, display_name="AlreadyConnected", interests=["tech"])
        fallback = User.objects.create_user(username="fallback_candidate", password="Password123!")
        Profile.objects.create(user=fallback, display_name="FallbackCandidate", interests=["tech"])
        author = User.objects.create_user(username="suggest_connected_author", password="Password123!")
        Profile.objects.create(user=author, display_name="SuggestConnectedAuthor")
        Connection.objects.create(requester=user, recipient=connected, status=Connection.Status.ACCEPTED)
        self.client.force_authenticate(user=user)
        for index in range(3):
            Post.objects.create(author=author, content=f"connected post {index}")

        response = self.client.get("/api/v1/feed/?mode=both&page_size=3")
        self.assertEqual(response.status_code, 200)
        suggestions = [item for item in response.data["items"] if item["item_type"] == "suggestion"]
        self.assertTrue(suggestions)
        self.assertNotEqual(suggestions[0]["data"].get("display_name"), "AlreadyConnected")

    def test_feed_excludes_posts_with_safety_flags(self):
        viewer = User.objects.create_user(username="safe_feed_viewer", password="Password123!")
        author = User.objects.create_user(username="safe_feed_author", password="Password123!")
        Profile.objects.create(user=viewer, display_name="SafeFeedViewer")
        Profile.objects.create(user=author, display_name="SafeFeedAuthor")
        self.client.force_authenticate(user=viewer)
        safe_post = Post.objects.create(author=author, content="safe content", interest_tags=["tech"])
        blocked_post = Post.objects.create(author=author, content="blocked content", interest_tags=["tech"])
        ModerationFlag.objects.create(
            profile_id=viewer.profile.id,
            content_type="post",
            content_id=blocked_post.id,
            category="credible_violence",
            reason="matched prohibited category",
            payload={},
            policy_region="global",
            policy_version="v1",
        )

        response = self.client.get("/api/v1/feed/?mode=both&page_size=5")
        self.assertEqual(response.status_code, 200)
        post_ids = {item["data"]["id"] for item in response.data["items"] if item["item_type"] == "post"}
        self.assertIn(safe_post.id, post_ids)
        self.assertNotIn(blocked_post.id, post_ids)

    def test_negative_post_is_still_shown_when_no_higher_ranked_posts_exist(self):
        viewer = User.objects.create_user(username="negative_feed_viewer", password="Password123!")
        author = User.objects.create_user(username="negative_feed_author", password="Password123!")
        Profile.objects.create(user=viewer, display_name="Negative Feed Viewer")
        Profile.objects.create(user=author, display_name="Negative Feed Author")
        negative_post = Post.objects.create(
            author=author,
            content="Negative sentiment post",
            sentiment_label="negative",
            sentiment_score=-0.95,
            interest_tags=["tech"],
        )
        self.client.force_authenticate(user=viewer)
        response = self.client.get("/api/v1/feed/?mode=both&page_size=10")
        self.assertEqual(response.status_code, 200)
        post_ids = [item["data"]["id"] for item in response.data["items"] if item["item_type"] == "post"]
        self.assertIn(negative_post.id, post_ids)

    @patch("apps.feed.views.ensure_post_analysis")
    def test_unflagged_analysis_blocked_post_remains_visible(self, ensure_post_analysis_mock):
        ensure_post_analysis_mock.return_value = None
        viewer = User.objects.create_user(username="analysis_block_viewer", password="Password123!")
        author = User.objects.create_user(username="analysis_block_author", password="Password123!")
        Profile.objects.create(user=viewer, display_name="Analysis Block Viewer")
        Profile.objects.create(user=author, display_name="Analysis Block Author")
        blocked_status_post = Post.objects.create(
            author=author,
            content="Analysis blocked but not moderation-flagged",
            analysis_status=Post.AnalysisStatus.BLOCKED,
            needs_analysis_refresh=False,
            interest_tags=["tech"],
        )
        self.client.force_authenticate(user=viewer)
        response = self.client.get("/api/v1/feed/?mode=both&page_size=10")
        self.assertEqual(response.status_code, 200)
        post_ids = [item["data"]["id"] for item in response.data["items"] if item["item_type"] == "post"]
        self.assertIn(blocked_status_post.id, post_ids)

    def test_suggestions_exclude_profiles_with_safety_flags(self):
        user = User.objects.create_user(username="suggest_safety_user", password="Password123!")
        Profile.objects.create(user=user, display_name="SuggestSafetyUser", interests=["tech"])
        flagged = User.objects.create_user(username="flagged_candidate", password="Password123!")
        flagged_profile = Profile.objects.create(
            user=flagged,
            display_name="FlaggedCandidate",
            interests=["tech"],
        )
        fallback = User.objects.create_user(username="safe_candidate", password="Password123!")
        Profile.objects.create(user=fallback, display_name="SafeCandidate", interests=["tech"])
        author = User.objects.create_user(username="suggest_safety_author", password="Password123!")
        Profile.objects.create(user=author, display_name="SuggestSafetyAuthor")
        ModerationFlag.objects.create(
            profile_id=flagged_profile.id,
            content_type="profile",
            content_id=flagged_profile.id,
            category="credible_violence",
            reason="policy violation",
            payload={},
            policy_region="global",
            policy_version="v1",
        )
        self.client.force_authenticate(user=user)
        for index in range(3):
            Post.objects.create(author=author, content=f"safety suggestion post {index}")

        response = self.client.get("/api/v1/feed/?mode=both&page_size=3")
        self.assertEqual(response.status_code, 200)
        suggestions = [item for item in response.data["items"] if item["item_type"] == "suggestion"]
        self.assertTrue(suggestions)
        self.assertNotEqual(suggestions[0]["data"].get("display_name"), "FlaggedCandidate")

    def test_feed_excludes_blocked_authors(self):
        viewer = User.objects.create_user(username="blocked_viewer", password="Password123!")
        blocked_author = User.objects.create_user(username="blocked_author", password="Password123!")
        Profile.objects.create(user=viewer, display_name="Blocked Viewer")
        Profile.objects.create(user=blocked_author, display_name="Blocked Author")
        Post.objects.create(author=blocked_author, content="should be hidden")
        Connection.objects.create(
            requester=viewer,
            recipient=blocked_author,
            status=Connection.Status.BLOCKED,
        )
        self.client.force_authenticate(user=viewer)
        response = self.client.get("/api/v1/feed/?mode=both&page_size=5")
        self.assertEqual(response.status_code, 200)
        post_items = [item for item in response.data["items"] if item["item_type"] == "post"]
        self.assertEqual(len(post_items), 0)

    def test_feed_excludes_private_profiles_until_connected(self):
        viewer = User.objects.create_user(username="private_viewer", password="Password123!")
        private_author = User.objects.create_user(username="private_author", password="Password123!")
        Profile.objects.create(user=viewer, display_name="Private Viewer")
        Profile.objects.create(user=private_author, display_name="Private Author", is_private_profile=True)
        Post.objects.create(author=private_author, content="private content")
        self.client.force_authenticate(user=viewer)

        hidden_response = self.client.get("/api/v1/feed/?mode=both&page_size=5")
        self.assertEqual(hidden_response.status_code, 200)
        hidden_posts = [item for item in hidden_response.data["items"] if item["item_type"] == "post"]
        self.assertEqual(len(hidden_posts), 0)

        Connection.objects.create(
            requester=viewer,
            recipient=private_author,
            status=Connection.Status.ACCEPTED,
        )
        cache.clear()
        visible_response = self.client.get("/api/v1/feed/?mode=both&page_size=5")
        self.assertEqual(visible_response.status_code, 200)
        visible_posts = [item for item in visible_response.data["items"] if item["item_type"] == "post"]
        self.assertEqual(len(visible_posts), 1)

    def test_feed_excludes_viewer_own_posts(self):
        viewer = User.objects.create_user(username="self_feed_viewer", password="Password123!")
        other_author = User.objects.create_user(username="self_feed_other", password="Password123!")
        Profile.objects.create(user=viewer, display_name="Self Feed Viewer")
        Profile.objects.create(user=other_author, display_name="Self Feed Other")
        viewer_post = Post.objects.create(author=viewer, content="viewer post")
        other_post = Post.objects.create(author=other_author, content="other post")
        self.client.force_authenticate(user=viewer)

        response = self.client.get("/api/v1/feed/?mode=both&page_size=10")
        self.assertEqual(response.status_code, 200)
        post_ids = [item["data"]["id"] for item in response.data["items"] if item["item_type"] == "post"]
        self.assertIn(other_post.id, post_ids)
        self.assertNotIn(viewer_post.id, post_ids)

    @override_settings(
        UNITE_FEED_FRESHNESS_WINDOW_HOURS=1,
        UNITE_FEED_FALLBACK_LOOKBACK_HOURS=240,
        UNITE_FEED_FALLBACK_POST_COUNT=100,
    )
    def test_feed_uses_fallback_lookback_when_recent_pool_is_under_cap(self):
        viewer = User.objects.create_user(username="feed_fallback_viewer", password="Password123!")
        other_author = User.objects.create_user(username="feed_fallback_other", password="Password123!")
        Profile.objects.create(user=viewer, display_name="FeedFallbackViewer")
        Profile.objects.create(user=other_author, display_name="FeedFallbackOther")
        stale_post = Post.objects.create(author=other_author, content="stale but within fallback")
        Post.objects.filter(id=stale_post.id).update(created_at=timezone.now() - timedelta(hours=48))
        self.client.force_authenticate(user=viewer)

        response = self.client.get("/api/v1/feed/?mode=both&page_size=10")
        self.assertEqual(response.status_code, 200)
        post_ids = [item["data"]["id"] for item in response.data["items"] if item["item_type"] == "post"]
        self.assertIn(stale_post.id, post_ids)

    @override_settings(
        UNITE_FEED_FRESHNESS_WINDOW_HOURS=1,
        UNITE_FEED_FALLBACK_LOOKBACK_HOURS=24,
        UNITE_FEED_FALLBACK_POST_COUNT=100,
    )
    def test_feed_uses_unbounded_fallback_when_fallback_window_is_under_cap(self):
        viewer = User.objects.create_user(username="feed_unbounded_viewer", password="Password123!")
        other_author = User.objects.create_user(username="feed_unbounded_other", password="Password123!")
        Profile.objects.create(user=viewer, display_name="FeedUnboundedViewer")
        Profile.objects.create(user=other_author, display_name="FeedUnboundedOther")
        old_negative_post = Post.objects.create(
            author=other_author,
            content="older negative post still eligible when pool is sparse",
            sentiment_label="negative",
            sentiment_score=-0.92,
        )
        Post.objects.filter(id=old_negative_post.id).update(created_at=timezone.now() - timedelta(hours=72))
        self.client.force_authenticate(user=viewer)

        response = self.client.get("/api/v1/feed/?mode=both&page_size=10")
        self.assertEqual(response.status_code, 200)
        post_ids = [item["data"]["id"] for item in response.data["items"] if item["item_type"] == "post"]
        self.assertIn(old_negative_post.id, post_ids)

    @override_settings(
        UNITE_FEED_FRESHNESS_WINDOW_HOURS=1,
        UNITE_FEED_FALLBACK_LOOKBACK_HOURS=1,
        UNITE_FEED_FALLBACK_POST_COUNT=100,
    )
    def test_feed_excludes_posts_older_than_freshness_window(self):
        user = User.objects.create_user(username="freshness_window_user", password="Password123!")
        author = User.objects.create_user(username="freshness_window_author", password="Password123!")
        Profile.objects.create(user=user, display_name="FreshnessWindowUser")
        Profile.objects.create(user=author, display_name="FreshnessWindowAuthor")
        self.client.force_authenticate(user=user)
        old_post = Post.objects.create(author=author, content="stale post")
        new_post = Post.objects.create(author=author, content="fresh post")
        Post.objects.filter(id=old_post.id).update(created_at=timezone.now() - timedelta(hours=3))

        response = self.client.get("/api/v1/feed/?mode=both&page_size=5")
        self.assertEqual(response.status_code, 200)
        post_ids = [item["data"]["id"] for item in response.data["items"] if item["item_type"] == "post"]
        self.assertIn(new_post.id, post_ids)
        self.assertNotIn(old_post.id, post_ids)

    def test_feed_query_count_stays_within_budget(self):
        user = User.objects.create_user(username="query_budget_user", password="Password123!")
        Profile.objects.create(user=user, display_name="QueryBudgetUser")
        author = User.objects.create_user(username="query_budget_author", password="Password123!")
        Profile.objects.create(user=author, display_name="QueryBudgetAuthor")
        self.client.force_authenticate(user=user)
        for index in range(8):
            Post.objects.create(author=author, content=f"budget post {index}")

        with CaptureQueriesContext(connection) as query_context:
            response = self.client.get("/api/v1/feed/?mode=both&page_size=6")

        self.assertEqual(response.status_code, 200)
        self.assertLessEqual(len(query_context), 55)
