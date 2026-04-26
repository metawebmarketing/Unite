from celery import shared_task
from django.conf import settings
from django.db.models import Count
from django.utils import timezone
from datetime import timedelta

from apps.accounts.models import Profile
from apps.moderation.services import evaluate_profile_content
from apps.posts.models import Post
from apps.posts.models import PostInteraction


@shared_task
def generate_algorithm_profile(profile_id: int, region_code: str = "global") -> dict:
    profile = Profile.objects.filter(id=profile_id).first()
    if not profile:
        return {"status": "missing_profile"}

    profile.algorithm_profile_status = Profile.AlgorithmProfileStatus.PROCESSING
    profile.save(update_fields=["algorithm_profile_status", "updated_at"])

    try:
        vector = _build_profile_vector(profile)
        profile.algorithm_vector = vector
        evaluate_profile_content(profile=profile, region_code=region_code)
        profile.algorithm_profile_status = Profile.AlgorithmProfileStatus.READY
        profile.save(update_fields=["algorithm_vector", "algorithm_profile_status", "updated_at"])
        return {"status": "ok", "profile_id": profile_id}
    except Exception as exc:
        profile.algorithm_profile_status = Profile.AlgorithmProfileStatus.FAILED
        profile.save(update_fields=["algorithm_profile_status", "updated_at"])
        return {"status": "failed", "profile_id": profile_id, "error": str(exc)}


@shared_task
def refresh_active_profile_scores(limit: int = 200) -> dict:
    cooldown_seconds = max(0, int(getattr(settings, "UNITE_PROFILE_REFRESH_COOLDOWN_SECONDS", 900)))
    min_posts = max(0, int(getattr(settings, "UNITE_PROFILE_REFRESH_MIN_POSTS", 1)))
    min_interactions = max(0, int(getattr(settings, "UNITE_PROFILE_REFRESH_MIN_INTERACTIONS", 2)))
    stale_before = timezone.now() - timedelta(seconds=cooldown_seconds)
    profiles = (
        Profile.objects.annotate(
            authored_posts=Count("user__posts", distinct=True),
            interaction_events=Count("user__post_interactions", distinct=True),
        )
        .filter(updated_at__lte=stale_before)
        .filter(authored_posts__gte=min_posts)
        .filter(interaction_events__gte=min_interactions)
        .order_by("-interaction_events", "-authored_posts", "-updated_at")[:limit]
    )
    refreshed = 0
    for profile in profiles:
        generate_algorithm_profile.delay(profile.id, profile.location or "global")
        refreshed += 1
    return {
        "status": "scheduled",
        "count": refreshed,
        "cooldown_seconds": cooldown_seconds,
        "min_posts": min_posts,
        "min_interactions": min_interactions,
    }


def _normalize_tokens(values: list[object], limit: int | None = None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = str(value).strip().lower()
        if not token or token in seen:
            continue
        seen.add(token)
        normalized.append(token)
        if limit and len(normalized) >= limit:
            break
    return normalized


def _bump_weight(weights: dict[str, float], token: str, amount: float) -> None:
    if not token:
        return
    weights[token] = round(weights.get(token, 0.0) + amount, 4)


def _extract_post_tags(post: Post | None) -> list[str]:
    if not post or not isinstance(post.interest_tags, list):
        return []
    return _normalize_tokens(post.interest_tags)


def _build_profile_vector(profile: Profile) -> dict:
    raw_interests = profile.interests if isinstance(profile.interests, list) else []
    interests = _normalize_tokens(raw_interests)
    interest_weights: dict[str, float] = {}
    for token in interests:
        _bump_weight(interest_weights, token, 3.0)

    recent_posts = list(Post.objects.filter(author=profile.user).only("interest_tags").order_by("-created_at")[:120])
    for post in recent_posts:
        for token in _extract_post_tags(post):
            _bump_weight(interest_weights, token, 1.5)

    interaction_weight_map = {
        PostInteraction.ActionType.LIKE: 1.0,
        PostInteraction.ActionType.BOOKMARK: 1.2,
        PostInteraction.ActionType.REPOST: 1.6,
        PostInteraction.ActionType.REPLY: 2.0,
        PostInteraction.ActionType.QUOTE: 2.0,
        PostInteraction.ActionType.REPORT: -3.0,
    }
    recent_interactions = list(
        PostInteraction.objects.filter(user=profile.user)
        .select_related("post")
        .only("action_type", "post__interest_tags")
        .order_by("-created_at")[:240]
    )
    for interaction in recent_interactions:
        weight = interaction_weight_map.get(str(interaction.action_type), 0.5)
        for token in _extract_post_tags(interaction.post):
            _bump_weight(interest_weights, token, weight)

    sorted_weights = sorted(interest_weights.items(), key=lambda item: (item[1], item[0]), reverse=True)
    ordered_tokens = [token for token, _weight in sorted_weights]
    top_weights = {token: weight for token, weight in sorted_weights[:100]}

    constructive_actions = sum(
        1
        for interaction in recent_interactions
        if interaction.action_type in {PostInteraction.ActionType.REPLY, PostInteraction.ActionType.QUOTE}
    )
    interaction_count = len(recent_interactions)
    constructive_ratio = (constructive_actions / interaction_count) if interaction_count else 0.0
    positive_dialogue_bias = min(0.95, round(0.55 + constructive_ratio * 0.4, 2))
    recency_weight = min(0.75, round(0.3 + min(interaction_count, 240) / 800, 2))

    return {
        "interest_count": len(interests),
        "interest_tokens": ordered_tokens[:50],
        "interest_weights": top_weights,
        "positive_dialogue_bias": positive_dialogue_bias,
        "recency_weight": recency_weight,
        "signal_totals": {
            "authored_posts": len(recent_posts),
            "interaction_events": interaction_count,
        },
    }
