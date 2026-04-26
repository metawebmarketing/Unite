from apps.ads.models import AdSlotConfig


def _normalize_interest_tokens(values: list[object] | None) -> set[str]:
    if not values:
        return set()
    tokens: set[str] = set()
    for value in values:
        token = str(value).strip().lower()
        if token:
            tokens.add(token)
    return tokens


def resolve_ad_config(
    region_code: str | None,
    user_interest_tags: list[object] | None = None,
    is_ai_account: bool = False,
    user_experiment_flags: list[object] | None = None,
) -> dict:
    resolved_region = (region_code or "global").lower()
    user_tier = AdSlotConfig.AccountTierTarget.AI if is_ai_account else AdSlotConfig.AccountTierTarget.HUMAN
    user_interests = _normalize_interest_tokens(user_interest_tags)
    experiment_flags = _normalize_interest_tokens(user_experiment_flags)
    candidates = AdSlotConfig.objects.filter(
        enabled=True,
        region_code__in=[resolved_region, "global"],
    ).order_by("-updated_at")[:200]

    best_config = None
    best_score: tuple[int, int, int] | None = None
    for config in candidates:
        if config.account_tier_target not in {AdSlotConfig.AccountTierTarget.ANY, user_tier}:
            continue
        experiment_key = str(config.experiment_key or "").strip().lower()
        if experiment_key and experiment_key not in experiment_flags:
            continue
        config_interest_tags = _normalize_interest_tokens(
            config.target_interest_tags if isinstance(config.target_interest_tags, list) else []
        )
        overlap = len(user_interests.intersection(config_interest_tags))
        if config_interest_tags and overlap == 0:
            continue
        region_match = 1 if config.region_code == resolved_region else 0
        experiment_match = 1 if experiment_key else 0
        score = (region_match, experiment_match, overlap, int(config.id))
        if best_score is None or score > best_score:
            best_score = score
            best_config = config

    if not best_config:
        return {"interval": 0, "enabled": False}
    return {
        "interval": int(best_config.interval),
        "enabled": bool(best_config.enabled),
        "config_id": int(best_config.id),
        "campaign_key": best_config.campaign_key or f"cfg-{best_config.id}",
        "targeting_reason": (
            "interest_match"
            if isinstance(best_config.target_interest_tags, list) and best_config.target_interest_tags
            else "region_tier_match"
        ),
        "experiment_key": best_config.experiment_key or "",
    }
