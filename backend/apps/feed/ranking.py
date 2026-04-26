from collections.abc import Sequence


def _normalize_tokens(values: Sequence[object] | None) -> set[str]:
    if not values:
        return set()
    normalized: set[str] = set()
    for value in values:
        token = str(value).strip().lower()
        if token:
            normalized.add(token)
    return normalized


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
        engagement = int(post.get("like_count", 0)) * 2 + int(post.get("reply_count", 0))
        active_interest_boost = 15 if active_interest_tag and active_interest_tag in tags else 0
        score = overlap * 10 + int(weighted_overlap * 4) + active_interest_boost + engagement
        ranked.append({**post, "rank_score": score})
    ranked.sort(key=lambda item: (item["rank_score"], int(item.get("id", 0))), reverse=True)
    return ranked
