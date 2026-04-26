from apps.accounts.models import Profile
from apps.moderation.models import ModerationFlag
from apps.policy.services import resolve_policy

CATEGORY_KEYWORDS = {
    "csam_csem": ["csam", "csem", "child abuse material"],
    "harassment": ["kill yourself", "stupid trash", "go die"],
    "illegal_promotion": ["buy stolen", "illegal drugs", "fake ids"],
    "credible_violence": ["bomb threat", "shoot up", "massacre plan"],
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
