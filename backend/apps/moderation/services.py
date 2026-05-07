from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.accounts.models import Profile, ProfileActionScore
from apps.accounts.ranking import recompute_profile_rank_rollups
from apps.accounts.runtime_config import get_runtime_config
from apps.moderation.media_analysis import detect_policy_categories, resolve_policy_decision
from apps.moderation.models import ModerationFlag, ModerationPenalty
from apps.policy.services import resolve_policy
from apps.posts.models import UploadedMediaAsset

CATEGORY_KEYWORDS = {
    "csam_csem": ["csam", "csem", "child abuse material"],
    "harassment": ["kill yourself", "stupid trash", "go die"],
    "illegal_promotion": ["buy stolen", "illegal drugs", "fake ids"],
    "credible_violence": ["bomb threat", "shoot up", "massacre plan"],
    "graphic_violence": ["graphic violence", "gore", "beheading"],
    "nudity_pornographic": ["porn", "explicit nudity", "sexual content"],
    "child_sexual_exploitative": ["child sexual", "minor sexual", "csam", "csem"],
}


def evaluate_profile_content(profile: Profile, region_code: str | None = None) -> list[ModerationFlag]:
    policy = resolve_policy(region_code)
    blocked_hits = []
    content_blob = f"{profile.bio} {' '.join(profile.interests)}".lower()

    for category in policy.prohibited_categories:
        token = category.replace("_", " ")
        if token in content_blob:
            blocked_hits.append(
                ModerationFlag.objects.create(
                    profile_id=profile.id,
                    content_type="profile",
                    content_id=profile.id,
                    category=category,
                    reason=f"Matched policy token '{token}'",
                    payload={"content_excerpt": content_blob[:240]},
                    policy_region=policy.region_code,
                    policy_version=policy.version,
                )
            )
    return blocked_hits


def evaluate_text_content(
    *,
    text: str,
    region_code: str | None,
    content_type: str,
    content_id: int | None = None,
    profile_id: int | None = None,
) -> list[ModerationFlag]:
    policy = resolve_policy(region_code)
    content_blob = (text or "").lower()
    hits: list[ModerationFlag] = []

    for category in policy.prohibited_categories:
        keywords = CATEGORY_KEYWORDS.get(category, [category.replace("_", " ")])
        for keyword in keywords:
            if keyword in content_blob:
                hits.append(
                    ModerationFlag.objects.create(
                        profile_id=profile_id,
                        content_type=content_type,
                        content_id=content_id,
                        category=category,
                        reason=f"Matched keyword '{keyword}'",
                        payload={"content_excerpt": content_blob[:240]},
                        policy_region=policy.region_code,
                        policy_version=policy.version,
                    )
                )
                break
    return hits


def is_content_blocked(
    *,
    text: str,
    region_code: str | None,
    content_type: str,
    content_id: int | None = None,
    profile_id: int | None = None,
) -> tuple[bool, list[str]]:
    hits = evaluate_text_content(
        text=text,
        region_code=region_code,
        content_type=content_type,
        content_id=content_id,
        profile_id=profile_id,
    )
    categories = [hit.category for hit in hits]
    return (len(categories) > 0, categories)


def evaluate_media_asset(
    *,
    asset: UploadedMediaAsset,
    region_code: str | None,
    profile_id: int | None = None,
) -> tuple[bool, list[str]]:
    policy = resolve_policy(region_code)
    detected_categories = detect_policy_categories(
        type(
            "AssetResultProxy",
            (),
            {
                "actionable_terms": list(asset.analysis_terms or []),
                "category_scores": {
                    str(category): 1.0 for category in list(asset.analysis_categories or [])
                },
                "metadata": {},
            },
        )()
    )
    decision = resolve_policy_decision(
        detected_categories=detected_categories,
        prohibited_categories=policy.prohibited_categories,
        allowed_exceptions=policy.allowed_exceptions,
        is_artwork_source=bool(asset.is_artwork_source),
        is_video_game_capture=bool(asset.is_video_game_capture),
    )
    for category in decision.blocked_categories:
        ModerationFlag.objects.get_or_create(
            profile_id=profile_id,
            content_type="uploaded_media_asset",
            content_id=asset.id,
            category=category,
            defaults={
                "reason": "Media intelligence policy block",
                "payload": {
                    "media_type": asset.media_type,
                    "media_url": asset.media_url,
                },
                "policy_region": policy.region_code,
                "policy_version": policy.version,
            },
        )
    return decision.blocked, decision.blocked_categories


def resolve_penalty_expiry_days() -> int:
    runtime = get_runtime_config()
    configured = runtime.get("penalty_expiry_days", 90)
    try:
        normalized = int(configured)
    except (TypeError, ValueError):
        normalized = 90
    return max(1, normalized)


def expire_stale_penalties() -> int:
    now = timezone.now()
    return ModerationPenalty.objects.filter(active=True, expires_at__lte=now).update(active=False)


def get_active_penalty_count(*, user_id: int) -> int:
    expire_stale_penalties()
    return ModerationPenalty.objects.filter(user_id=user_id, active=True).count()


def get_user_posting_restriction(*, user_id: int) -> tuple[bool, int]:
    active_penalty_count = get_active_penalty_count(user_id=user_id)
    return active_penalty_count >= 3, active_penalty_count


def _resolve_flag_target_user_id(flag: ModerationFlag) -> int | None:
    if flag.target_user_id:
        return int(flag.target_user_id)
    payload = dict(flag.payload or {})
    raw_target_user_id = payload.get("target_user_id")
    try:
        normalized_target_user_id = int(raw_target_user_id)
    except (TypeError, ValueError):
        normalized_target_user_id = 0
    if normalized_target_user_id > 0:
        return normalized_target_user_id
    if flag.content_type == "post" and flag.content_id:
        from apps.posts.models import Post

        post_author_id = (
            Post.objects.filter(id=flag.content_id)
            .values_list("author_id", flat=True)
            .first()
        )
        if post_author_id:
            return int(post_author_id)
    return None


def _resolve_flag_reporter_user_id(flag: ModerationFlag) -> int | None:
    if flag.reporter_user_id:
        return int(flag.reporter_user_id)
    payload = dict(flag.payload or {})
    raw_reporter_user_id = payload.get("reported_by_user_id")
    try:
        normalized_reporter_user_id = int(raw_reporter_user_id)
    except (TypeError, ValueError):
        normalized_reporter_user_id = 0
    if normalized_reporter_user_id > 0:
        return normalized_reporter_user_id
    return None


def create_penalty(
    *,
    user_id: int,
    reason_type: str,
    source_flag: ModerationFlag | None,
    points: int = 1,
) -> ModerationPenalty:
    now = timezone.now()
    expires_at = now + timedelta(days=resolve_penalty_expiry_days())
    if source_flag:
        existing = ModerationPenalty.objects.filter(source_flag=source_flag, reason_type=reason_type).first()
        if existing:
            return existing
    penalty = ModerationPenalty.objects.create(
        user_id=user_id,
        reason_type=reason_type,
        source_flag=source_flag,
        points=max(1, int(points or 1)),
        active=True,
        expires_at=expires_at,
    )
    profile = Profile.objects.filter(user_id=user_id).first()
    if profile:
        ProfileActionScore.objects.create(
            profile=profile,
            action_type=ProfileActionScore.ActionType.REPORT,
            sentiment_label="negative",
            sentiment_score=-1.0,
            contribution_score=-1.0 * float(max(1, int(points or 1))),
            metadata={
                "source": "moderation_penalty",
                "reason_type": reason_type,
                "penalty_id": penalty.id,
                "source_flag_id": source_flag.id if source_flag else None,
            },
        )
        recompute_profile_rank_rollups(profile)
    return penalty


@transaction.atomic
def resolve_flag_decision(
    *,
    flag: ModerationFlag,
    reviewer_user_id: int,
    decision: str,
    apply_penalty: bool,
    review_note: str = "",
    report_outcome: str = "valid_report",
) -> ModerationFlag:
    normalized_decision = str(decision or "").strip().lower()
    if normalized_decision not in {
        ModerationFlag.Status.APPROVED,
        ModerationFlag.Status.DENIED,
    }:
        raise ValueError("Invalid moderation decision.")
    normalized_report_outcome = str(report_outcome or "").strip().lower()
    if normalized_report_outcome not in {"valid_report", "false_report"}:
        raise ValueError("Invalid report outcome.")
    penalty_user_id: int | None = None
    penalty_reason_type = ModerationPenalty.ReasonType.CONTENT_VIOLATION
    if flag.category == "user_report":
        reporter_user_id = _resolve_flag_reporter_user_id(flag)
        target_user_id = _resolve_flag_target_user_id(flag)
        if normalized_report_outcome == "false_report":
            penalty_user_id = reporter_user_id
            penalty_reason_type = ModerationPenalty.ReasonType.FALSE_REPORT
        else:
            penalty_user_id = target_user_id
            penalty_reason_type = ModerationPenalty.ReasonType.CONTENT_VIOLATION
    else:
        penalty_user_id = _resolve_flag_target_user_id(flag)

    flag.status = normalized_decision
    flag.apply_penalty = bool(apply_penalty)
    flag.review_note = str(review_note or "").strip()
    flag.reviewed_by_user_id = reviewer_user_id
    flag.reviewed_at = timezone.now()
    flag.save(
        update_fields=[
            "status",
            "apply_penalty",
            "review_note",
            "reviewed_by_user_id",
            "reviewed_at",
        ]
    )

    if (
        normalized_decision == ModerationFlag.Status.APPROVED
        and bool(apply_penalty)
        and penalty_user_id
    ):
        create_penalty(
            user_id=int(penalty_user_id),
            reason_type=penalty_reason_type,
            source_flag=flag,
            points=1,
        )
    return flag
