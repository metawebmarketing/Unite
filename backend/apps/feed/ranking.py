from collections.abc import Sequence
from datetime import datetime, timezone

NEGATIVE_ENGAGEMENT_DAMPING_FACTOR = 0.25
NEGATIVE_ENGAGEMENT_TRIGGER = -0.2
VERY_NEGATIVE_SENTIMENT_TRIGGER = -0.6
AUTHOR_PROFILE_SCORE_MIN = -5.0
AUTHOR_PROFILE_SCORE_MAX = 5.0
AUTHOR_PROFILE_WEIGHT = 24
MAX_ENGAGEMENT_POINTS = 24
QUALITY_BAND_PRIORITY = {
    "non_negative_band": 1,
    "negative_band": 0,
}
FRESHNESS_DECAY_HALF_LIFE_HOURS = 48.0
MAX_FRESHNESS_BOOST = 30.0


def _normalize_tokens(values: Sequence[object] | None) -> set[str]:
    if not values:
        return set()
    normalized: set[str] = set()
    for value in values:
        token = str(value).strip().lower()
        if token:
            normalized.add(token)
    return normalized


def _sentiment_component(sentiment_score: float) -> int:
    # Keep neutral slightly preferred over hostile content, and heavily
    # down-rank strongly negative posts so engagement cannot dominate ranking.
    if sentiment_score <= VERY_NEGATIVE_SENTIMENT_TRIGGER:
        return -40
    if sentiment_score < NEGATIVE_ENGAGEMENT_TRIGGER:
        return -24
    if sentiment_score < 0.0:
        return -12
    if sentiment_score == 0.0:
        return 4
    return 8 + int(sentiment_score * 16)


def _engagement_component(like_count: int, reply_count: int, sentiment_score: float) -> int:
    raw_engagement = min(MAX_ENGAGEMENT_POINTS, like_count * 2 + reply_count)
    if sentiment_score < NEGATIVE_ENGAGEMENT_TRIGGER:
        return int(raw_engagement * NEGATIVE_ENGAGEMENT_DAMPING_FACTOR)
    return raw_engagement


def _author_profile_component(author_profile_score: float) -> int:
    bounded = max(AUTHOR_PROFILE_SCORE_MIN, min(AUTHOR_PROFILE_SCORE_MAX, author_profile_score))
    return int(bounded * AUTHOR_PROFILE_WEIGHT)


def _quality_band(sentiment_score: float) -> str:
    # Only demote truly negative sentiment. Neutral and positive posts
    # should compete by the normal rank score.
    if sentiment_score < 0.0:
        return "negative_band"
    return "non_negative_band"


def _freshness_component(created_at: object, now_ts: datetime) -> int:
    if not isinstance(created_at, str):
        return 0
    try:
        created_ts = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError:
        return 0
    if created_ts.tzinfo is None:
        created_ts = created_ts.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now_ts - created_ts).total_seconds() / 3600.0)
    decay_multiplier = 0.5 ** (age_hours / FRESHNESS_DECAY_HALF_LIFE_HOURS)
    return int(MAX_FRESHNESS_BOOST * decay_multiplier)


def score_feed_items(user_context: dict, candidate_posts: Sequence[dict]) -> list[dict]:
    """
    Swappable ranking interface.

    Input: user_context + candidate post payloads
    Output: ranked post payloads with computed `rank_score`.
    """
    preferred_tags = _normalize_tokens(user_context.get("interest_tokens"))
    if not preferred_tags:
        preferred_tags = _normalize_tokens(user_context.get("profile_interests"))
    raw_interest_weights = user_context.get("interest_weights")
    interest_weights: dict[str, float] = {}
    if isinstance(raw_interest_weights, dict):
        for key, value in raw_interest_weights.items():
            token = str(key).strip().lower()
            if not token:
                continue
            try:
                interest_weights[token] = float(value)
            except (TypeError, ValueError):
                continue
    active_interest_tag = str(user_context.get("active_interest_tag", "")).strip().lower()
    now_ts = user_context.get("now_ts")
    if not isinstance(now_ts, datetime):
        now_ts = datetime.now(timezone.utc)
    ranked: list[dict] = []
    for post in candidate_posts:
        tags = _normalize_tokens(post.get("interest_tags"))
        media_terms = _normalize_tokens(post.get("media_action_terms"))
        combined_terms = tags.union(media_terms)
        overlap = len(preferred_tags.intersection(tags))
        media_overlap = len(preferred_tags.intersection(media_terms))
        weighted_overlap = sum(max(interest_weights.get(tag, 0.0), 0.0) for tag in combined_terms)
        like_count = int(post.get("like_count", 0))
        reply_count = int(post.get("reply_count", 0))
        active_interest_boost = 15 if active_interest_tag and active_interest_tag in combined_terms else 0
        sentiment_score = float(post.get("sentiment_score", 0.0) or 0.0)
        author_profile_score = float(post.get("author_profile_score", 0.0) or 0.0)
        inherited_rank_score = int(post.get("shared_post_rank_score", 0) or 0)
        share_delta_score = int(post.get("share_delta_score", 0) or 0)
        engagement = _engagement_component(like_count, reply_count, sentiment_score)
        sentiment_boost = _sentiment_component(sentiment_score)
        author_profile_boost = _author_profile_component(author_profile_score)
        freshness_boost = _freshness_component(post.get("created_at"), now_ts)
        baseline_score = sentiment_boost + author_profile_boost
        quality_band = _quality_band(sentiment_score)
        score = (
            overlap * 10
            + media_overlap * 6
            + int(weighted_overlap * 4)
            + active_interest_boost
            + engagement
            + sentiment_boost
            + author_profile_boost
            + freshness_boost
            + inherited_rank_score
            + share_delta_score
        )
        ranked.append(
            {
                **post,
                "rank_score": score,
                "baseline_score": baseline_score,
                "quality_band": quality_band,
            }
        )
    ranked.sort(
        key=lambda item: (
            QUALITY_BAND_PRIORITY.get(str(item.get("quality_band")), 0),
            item["rank_score"],
            int(item.get("id", 0)),
        ),
        reverse=True,
    )
    return ranked
