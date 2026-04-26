from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from apps.accounts.models import Profile
from apps.ads.models import AdDeliveryEvent, AdSlotConfig
from apps.feed.services import FeedInjectionConfig, inject_feed_items, load_feed_config

User = get_user_model()


class AdsApiTests(APITestCase):
    def test_ingest_ad_event_and_read_metrics(self):
        user = User.objects.create_user(username="ads_user", password="Password123!")
        Profile.objects.create(user=user, display_name="AdsUser")
        self.client.force_authenticate(user=user)

        ingest_response = self.client.post(
            "/api/v1/ads/events",
            {
                "event_type": "impression",
                "ad_event_key": "feed-3",
                "campaign_key": "spring",
                "placement": "feed",
                "region_code": "us",
            },
            format="json",
        )
        self.assertEqual(ingest_response.status_code, 201)
        self.assertTrue(AdDeliveryEvent.objects.filter(ad_event_key="feed-3").exists())

        self.client.post(
            "/api/v1/ads/events",
            {
                "event_type": "click",
                "ad_event_key": "feed-3",
                "campaign_key": "spring",
                "placement": "feed",
                "region_code": "us",
            },
            format="json",
        )
        metrics_response = self.client.get("/api/v1/ads/metrics")
        self.assertEqual(metrics_response.status_code, 200)
        self.assertEqual(metrics_response.data["impressions"], 1)
        self.assertEqual(metrics_response.data["clicks"], 1)
        self.assertEqual(metrics_response.data["ctr"], 1.0)
        self.assertEqual(metrics_response.data["by_region"]["us"]["impressions"], 1)
        self.assertEqual(metrics_response.data["by_campaign"]["spring"]["impressions"], 1)

    def test_feed_ad_payload_contains_reporting_keys(self):
        config = FeedInjectionConfig(
            suggestion_interval=3,
            ad_interval=2,
            suggestions_enabled=False,
            ads_enabled=True,
            max_injection_ratio=1.0,
            ad_config_id=99,
            ad_campaign_key="spring-launch",
            ad_targeting_reason="interest_match",
            ad_experiment_key="ads_exp_a",
        )
        organic_items = [
            {"item_type": "post", "source_module": "organic", "injection_reason": "", "data": {"id": 1}},
            {"item_type": "post", "source_module": "organic", "injection_reason": "", "data": {"id": 2}},
        ]
        injected = inject_feed_items(organic_items=organic_items, mode="both", config=config)
        ad_items = [item for item in injected if item["item_type"] == "ad"]
        self.assertEqual(len(ad_items), 1)
        self.assertIn("ad_event_key", ad_items[0]["data"])
        self.assertEqual(ad_items[0]["data"]["placement"], "feed")
        self.assertEqual(ad_items[0]["data"]["campaign_key"], "spring-launch")
        self.assertEqual(ad_items[0]["data"]["ad_config_id"], 99)
        self.assertEqual(ad_items[0]["data"]["targeting_reason"], "interest_match")

    def test_resolve_ad_metrics_region_filter(self):
        user = User.objects.create_user(username="ads_region_user", password="Password123!")
        Profile.objects.create(user=user, display_name="AdsRegionUser")
        self.client.force_authenticate(user=user)
        AdDeliveryEvent.objects.create(
            user_id=user.id,
            event_type=AdDeliveryEvent.EventType.IMPRESSION,
            ad_event_key="feed-5",
            region_code="us",
            placement="feed",
        )
        AdDeliveryEvent.objects.create(
            user_id=user.id,
            event_type=AdDeliveryEvent.EventType.IMPRESSION,
            ad_event_key="feed-6",
            region_code="ca",
            placement="feed",
        )
        response = self.client.get("/api/v1/ads/metrics?region=us")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["impressions"], 1)
        self.assertEqual(response.data["by_region"]["us"]["impressions"], 1)

    def test_ad_slot_config_override_applies_to_feed_loader(self):
        AdSlotConfig.objects.create(region_code="us", interval=4, enabled=True, campaign_key="us-default")
        config = load_feed_config(region_code="us")
        self.assertTrue(config.ads_enabled)
        self.assertEqual(config.ad_interval, 4)
        self.assertEqual(config.ad_campaign_key, "us-default")

    def test_create_list_and_update_ad_slot_configs(self):
        user = User.objects.create_user(username="ads_admin_user", password="Password123!", is_staff=True)
        Profile.objects.create(user=user, display_name="AdsAdminUser")
        self.client.force_authenticate(user=user)
        create_response = self.client.post(
            "/api/v1/ads/configs",
            {
                "region_code": "US",
                "campaign_key": "Spring_US",
                "experiment_key": "ad_exp_1",
                "interval": 5,
                "enabled": True,
                "account_tier_target": "human",
                "target_interest_tags": ["Tech", "AI"],
            },
            format="json",
        )
        self.assertEqual(create_response.status_code, 201)
        self.assertEqual(create_response.data["region_code"], "us")
        self.assertEqual(create_response.data["campaign_key"], "spring_us")
        self.assertEqual(create_response.data["experiment_key"], "ad_exp_1")
        self.assertEqual(create_response.data["account_tier_target"], "human")
        self.assertEqual(create_response.data["target_interest_tags"], ["tech", "ai"])

        list_response = self.client.get("/api/v1/ads/configs?region=us")
        self.assertEqual(list_response.status_code, 200)
        self.assertEqual(len(list_response.data), 1)
        self.assertEqual(list_response.data[0]["interval"], 5)

        update_response = self.client.patch(
            f"/api/v1/ads/configs/{create_response.data['id']}",
            {"interval": 3, "account_tier_target": "ai"},
            format="json",
        )
        self.assertEqual(update_response.status_code, 200)
        self.assertEqual(update_response.data["interval"], 3)
        self.assertEqual(update_response.data["account_tier_target"], "ai")

    def test_targeted_ad_slot_selection_prefers_interest_and_tier_match(self):
        AdSlotConfig.objects.create(
            region_code="us",
            campaign_key="human-tech",
            interval=4,
            enabled=True,
            account_tier_target="human",
            target_interest_tags=["tech"],
        )
        AdSlotConfig.objects.create(
            region_code="us",
            campaign_key="ai-tech",
            interval=2,
            enabled=True,
            account_tier_target="ai",
            target_interest_tags=["tech"],
        )
        config = load_feed_config(region_code="us", user_interest_tags=["tech"], is_ai_account=False)
        self.assertTrue(config.ads_enabled)
        self.assertEqual(config.ad_interval, 4)
        self.assertEqual(config.ad_campaign_key, "human-tech")

    def test_targeted_ad_slot_selection_respects_experiment_flags(self):
        AdSlotConfig.objects.create(
            region_code="us",
            campaign_key="exp-campaign",
            experiment_key="ads_exp_a",
            interval=7,
            enabled=True,
            account_tier_target="any",
        )
        fallback = AdSlotConfig.objects.create(
            region_code="us",
            campaign_key="fallback-campaign",
            interval=5,
            enabled=True,
            account_tier_target="any",
        )
        without_flag = load_feed_config(region_code="us", user_interest_tags=["tech"], is_ai_account=False)
        self.assertEqual(without_flag.ad_campaign_key, "fallback-campaign")
        with_flag = load_feed_config(
            region_code="us",
            user_interest_tags=["tech"],
            is_ai_account=False,
            user_experiment_flags=["ads_exp_a"],
        )
        self.assertEqual(with_flag.ad_campaign_key, "exp-campaign")
        self.assertNotEqual(with_flag.ad_config_id, fallback.id)

    def test_targeted_ad_slot_falls_back_to_global_when_region_misses(self):
        AdSlotConfig.objects.create(
            region_code="global",
            campaign_key="global-fallback",
            interval=6,
            enabled=True,
            account_tier_target="any",
        )
        config = load_feed_config(region_code="de", user_interest_tags=["travel"], is_ai_account=False)
        self.assertTrue(config.ads_enabled)
        self.assertEqual(config.ad_interval, 6)
        self.assertEqual(config.ad_campaign_key, "global-fallback")

    def test_metrics_campaign_filter(self):
        user = User.objects.create_user(username="ads_campaign_user", password="Password123!")
        Profile.objects.create(user=user, display_name="AdsCampaignUser")
        self.client.force_authenticate(user=user)
        AdDeliveryEvent.objects.create(
            user_id=user.id,
            event_type=AdDeliveryEvent.EventType.IMPRESSION,
            ad_event_key="spring-feed-3",
            campaign_key="spring",
            region_code="us",
            placement="feed",
        )
        AdDeliveryEvent.objects.create(
            user_id=user.id,
            event_type=AdDeliveryEvent.EventType.IMPRESSION,
            ad_event_key="summer-feed-3",
            campaign_key="summer",
            region_code="us",
            placement="feed",
        )
        response = self.client.get("/api/v1/ads/metrics?campaign=spring")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["impressions"], 1)
        self.assertIn("spring", response.data["by_campaign"])

    def test_update_unknown_ad_slot_config_returns_404(self):
        user = User.objects.create_user(username="ads_missing_user", password="Password123!", is_staff=True)
        Profile.objects.create(user=user, display_name="AdsMissingUser")
        self.client.force_authenticate(user=user)
        response = self.client.patch("/api/v1/ads/configs/999999", {"interval": 2}, format="json")
        self.assertEqual(response.status_code, 404)

    def test_ad_slot_config_create_forbidden_for_non_staff(self):
        user = User.objects.create_user(username="ads_member_user", password="Password123!")
        Profile.objects.create(user=user, display_name="AdsMemberUser")
        self.client.force_authenticate(user=user)
        response = self.client.post(
            "/api/v1/ads/configs",
            {"region_code": "us", "interval": 3, "enabled": True},
            format="json",
        )
        self.assertEqual(response.status_code, 403)
