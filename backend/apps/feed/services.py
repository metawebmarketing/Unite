from dataclasses import dataclass

from django.conf import settings

from apps.ads.services import resolve_ad_config
from apps.feed.models import FeedConfig


@dataclass
class FeedInjectionConfig:
    suggestion_interval: int
    ad_interval: int
    suggestions_enabled: bool
    ads_enabled: bool
    max_injection_ratio: float
    ad_config_id: int | None
    ad_campaign_key: str
    ad_targeting_reason: str
    ad_experiment_key: str


def load_feed_config(
    region_code: str | None = None,
    user_interest_tags: list[object] | None = None,
    is_ai_account: bool = False,
    user_experiment_flags: list[object] | None = None,
) -> FeedInjectionConfig:
    ad_config = resolve_ad_config(
        region_code,
        user_interest_tags=user_interest_tags,
        is_ai_account=is_ai_account,
        user_experiment_flags=user_experiment_flags,
    )
    config = FeedConfig.objects.order_by("id").first()
    if config:
        return FeedInjectionConfig(
            suggestion_interval=config.suggestion_interval,
            ad_interval=ad_config["interval"] if ad_config["enabled"] else config.ad_interval,
            suggestions_enabled=config.suggestions_enabled,
            ads_enabled=ad_config["enabled"] or config.ads_enabled,
            max_injection_ratio=float(getattr(settings, "UNITE_MAX_INJECTION_RATIO", 0.5)),
            ad_config_id=ad_config.get("config_id"),
            ad_campaign_key=str(ad_config.get("campaign_key", "fallback")),
            ad_targeting_reason=str(ad_config.get("targeting_reason", "none")),
            ad_experiment_key=str(ad_config.get("experiment_key", "")),
        )
    return FeedInjectionConfig(
        suggestion_interval=max(1, int(getattr(settings, "UNITE_SUGGESTION_INTERVAL", 3))),
        ad_interval=ad_config["interval"]
        if ad_config["enabled"]
        else max(0, int(getattr(settings, "UNITE_AD_INTERVAL", 0))),
        suggestions_enabled=True,
        ads_enabled=ad_config["enabled"],
        max_injection_ratio=float(getattr(settings, "UNITE_MAX_INJECTION_RATIO", 0.5)),
        ad_config_id=ad_config.get("config_id"),
        ad_campaign_key=str(ad_config.get("campaign_key", "fallback")),
        ad_targeting_reason=str(ad_config.get("targeting_reason", "none")),
        ad_experiment_key=str(ad_config.get("experiment_key", "")),
    )


def inject_feed_items(
    organic_items: list[dict],
    mode: str,
    config: FeedInjectionConfig,
    organic_offset: int = 0,
    suggestion_candidates: list[dict] | None = None,
) -> list[dict]:
    include_suggestions = config.suggestions_enabled and mode in {"suggestions", "both"}
    include_ads = config.ads_enabled and config.ad_interval > 0
    max_injected = max(0, int(len(organic_items) * max(0.0, min(config.max_injection_ratio, 1.0))))
    injected_count = 0

    results: list[dict] = []
    for index, item in enumerate(organic_items, start=1):
        global_organic_index = organic_offset + index
        results.append(item)
        if (
            include_suggestions
            and injected_count < max_injected
            and global_organic_index % max(1, config.suggestion_interval) == 0
        ):
            suggestion_payload = {"title": "Suggested connection"}
            if suggestion_candidates:
                cadence_index = max(1, global_organic_index // max(1, config.suggestion_interval)) - 1
                candidate = suggestion_candidates[cadence_index % len(suggestion_candidates)]
                suggestion_payload = {
                    "title": f"Connect with {candidate['display_name']}",
                    "user_id": candidate["user_id"],
                    "display_name": candidate["display_name"],
                    "shared_interest_count": candidate["shared_interest_count"],
                    "reason": candidate["reason"],
                }
            results.append(
                {
                    "item_type": "suggestion",
                    "source_module": "suggestion_injector",
                    "injection_reason": f"cadence_{config.suggestion_interval}",
                    "data": suggestion_payload,
                }
            )
            injected_count += 1
        if include_ads and injected_count < max_injected and global_organic_index % config.ad_interval == 0:
            results.append(
                {
                    "item_type": "ad",
                    "source_module": "ad_injector",
                    "injection_reason": f"cadence_{config.ad_interval}",
                    "data": {
                        "title": "Sponsored",
                        "placement": "feed",
                        "ad_event_key": f"{config.ad_campaign_key}-feed-{global_organic_index}",
                        "campaign_key": config.ad_campaign_key,
                        "ad_config_id": config.ad_config_id,
                        "targeting_reason": config.ad_targeting_reason,
                        "experiment_key": config.ad_experiment_key,
                    },
                }
            )
            injected_count += 1
    return results
