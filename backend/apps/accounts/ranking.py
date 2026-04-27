from __future__ import annotations

from collections import defaultdict

from django.db import transaction

from apps.accounts.models import Profile, ProfileActionScore
from apps.feed.sentiment_providers import get_sentiment_provider, score_sentiment_text
from apps.moderation.models import ModerationFlag
from apps.posts.models import Post, PostInteraction

ROLLING_ACTION_LIMIT = 500

ACTION_WEIGHT_BY_TYPE: dict[str, float] = {
    ProfileActionScore.ActionType.POST: 1.4,
    ProfileActionScore.ActionType.REPLY: 1.3,
    ProfileActionScore.ActionType.REPOST: 1.1,
    ProfileActionScore.ActionType.LIKE: 1.0,
    ProfileActionScore.ActionType.QUOTE: 1.2,
    ProfileActionScore.ActionType.BOOKMARK: 0.6,
    ProfileActionScore.ActionType.REPORT: 1.0,
}

TOXIC_FLAG_CATEGORIES = {"harassment", "credible_violence", "illegal_promotion", "csam_csem"}
NEGATIVE_TARGET_ACTION_TYPES = {
    ProfileActionScore.ActionType.REPLY,
    ProfileActionScore.ActionType.REPOST,
    ProfileActionScore.ActionType.QUOTE,
}


def score_post_sentiment(post: Post) -> tuple[str, float]:
    result = score_sentiment_text(post.content or "")
    label = result.label if result.label in {"positive", "neutral", "negative"} else "neutral"
    score = float(max(-1.0, min(1.0, round(result.score, 4))))
    needs_rescore = bool(getattr(result, "needs_rescore", False))
    Post.objects.filter(id=post.id).update(
        sentiment_label=label,
        sentiment_score=score,
        sentiment_needs_rescore=needs_rescore,
    )
    post.sentiment_label = label
    post.sentiment_score = score
    post.sentiment_needs_rescore = needs_rescore
    return label, score


def ensure_post_sentiment(post: Post) -> tuple[str, float]:
    current_label = str(post.sentiment_label or "").strip().lower()
    current_score = float(post.sentiment_score or 0.0)
    if bool(getattr(post, "sentiment_needs_rescore", False)):
        return score_post_sentiment(post)
    if current_label not in {"positive", "neutral", "negative"}:
        return score_post_sentiment(post)
    if current_label == "neutral" and current_score == 0.0:
        # Legacy/seeded rows may have default neutral values without scoring.
        return score_post_sentiment(post)
    return current_label, current_score


def get_sentiment_provider_name() -> str:
    provider = get_sentiment_provider()
    return provider.__class__.__name__


def is_post_toxic(post: Post) -> bool:
    return ModerationFlag.objects.filter(
        content_type="post",
        content_id=post.id,
        category__in=TOXIC_FLAG_CATEGORIES,
    ).exists()


def compute_contribution(
    *,
    action_type: str,
    sentiment_score: float,
    is_false_report: bool = False,
    is_toxic_report: bool = False,
    toggled_off: bool = False,
    target_sentiment_score: float | None = None,
) -> float:
    base_weight = ACTION_WEIGHT_BY_TYPE.get(action_type, 1.0)
    if action_type == ProfileActionScore.ActionType.REPORT:
        if is_false_report:
            return -1.5
        if is_toxic_report:
            return 0.25
        return -0.5
    contribution = sentiment_score * base_weight
    if toggled_off:
        contribution = -contribution
    # Replies/shares/quotes targeting negatively scored content can never
    # produce a positive user contribution. Best case is neutral (0).
    if (
        action_type in NEGATIVE_TARGET_ACTION_TYPES
        and target_sentiment_score is not None
        and float(target_sentiment_score) < 0
        and contribution > 0
    ):
        contribution = 0.0
    return round(contribution, 4)


@transaction.atomic
def record_profile_action_score(
    *,
    profile: Profile,
    action_type: str,
    sentiment_label: str,
    sentiment_score: float,
    post: Post | None = None,
    interaction: PostInteraction | None = None,
    metadata: dict | None = None,
    is_false_report: bool = False,
    is_toxic_report: bool = False,
    toggled_off: bool = False,
    recompute_rollup: bool = True,
    target_sentiment_score: float | None = None,
) -> ProfileActionScore:
    contribution = compute_contribution(
        action_type=action_type,
        sentiment_score=sentiment_score,
        is_false_report=is_false_report,
        is_toxic_report=is_toxic_report,
        toggled_off=toggled_off,
        target_sentiment_score=target_sentiment_score,
    )
    event = ProfileActionScore.objects.create(
        profile=profile,
        action_type=action_type,
        post=post,
        interaction=interaction,
        sentiment_label=sentiment_label,
        sentiment_score=sentiment_score,
        contribution_score=contribution,
        metadata=metadata or {},
    )
    if recompute_rollup:
        recompute_profile_rank_rollups(profile)
    return event


def recompute_profile_rank_rollups(profile: Profile) -> None:
    events = list(
        ProfileActionScore.objects.filter(profile=profile)
        .order_by("-created_at", "-id")[:ROLLING_ACTION_LIMIT]
    )
    total = round(sum(float(event.contribution_score) for event in events), 4)
    grouped: dict[str, dict[str, float | int]] = defaultdict(lambda: {"sum": 0.0, "count": 0, "avg": 0.0})
    for event in events:
        bucket = grouped[event.action_type]
        bucket["sum"] = round(float(bucket["sum"]) + float(event.contribution_score), 4)
        bucket["count"] = int(bucket["count"]) + 1
    for action_type, bucket in grouped.items():
        count = int(bucket["count"])
        bucket["avg"] = round((float(bucket["sum"]) / count), 4) if count else 0.0
        grouped[action_type] = bucket
    Profile.objects.filter(id=profile.id).update(
        rank_overall_score=total,
        rank_action_scores=dict(grouped),
        rank_last_500_count=len(events),
        rank_provider=get_sentiment_provider_name(),
    )
    profile.rank_overall_score = total
    profile.rank_action_scores = dict(grouped)
    profile.rank_last_500_count = len(events)
    profile.rank_provider = get_sentiment_provider_name()
