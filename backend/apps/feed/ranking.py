from collections.abc import Sequence

NEGATIVE_ENGAGEMENT_DAMPING_FACTOR = 0.25
NEGATIVE_ENGAGEMENT_TRIGGER = -0.2
VERY_NEGATIVE_SENTIMENT_TRIGGER = -0.6
AUTHOR_PROFILE_SCORE_MIN = -5.0
AUTHOR_PROFILE_SCORE_MAX = 5.0
AUTHOR_PROFILE_WEIGHT = 24
MAX_ENGAGEMENT_POINTS = 24


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
    ranked: list[dict] = []
    for post in candidate_posts:
        tags = _normalize_tokens(post.get("interest_tags"))
        overlap = len(preferred_tags.intersection(tags))
        weighted_overlap = sum(max(interest_weights.get(tag, 0.0), 0.0) for tag in tags)
        like_count = int(post.get("like_count", 0))
        reply_count = int(post.get("reply_count", 0))
        active_interest_boost = 15 if active_interest_tag and active_interest_tag in tags else 0
        sentiment_score = float(post.get("sentiment_score", 0.0) or 0.0)
        author_profile_score = float(post.get("author_profile_score", 0.0) or 0.0)
        engagement = _engagement_component(like_count, reply_count, sentiment_score)
        sentiment_boost = _sentiment_component(sentiment_score)
        author_profile_boost = _author_profile_component(author_profile_score)
        score = (
            overlap * 10
            + int(weighted_overlap * 4)
            + active_interest_boost
            + engagement
            + sentiment_boost
            + author_profile_boost
        )
        ranked.append({**post, "rank_score": score})
    ranked.sort(key=lambda item: (item["rank_score"], int(item.get("id", 0))), reverse=True)
    return ranked
