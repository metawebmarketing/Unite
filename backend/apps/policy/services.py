from dataclasses import dataclass
from hashlib import sha256
from datetime import datetime

from django.db import models
from django.utils import timezone
from apps.policy.models import PolicyPack

DEFAULT_CATEGORIES = [
    "csam_csem",
    "harassment",
    "illegal_promotion",
    "credible_violence",
]


@dataclass
class ResolvedPolicy:
    region_code: str
    version: str
    prohibited_categories: list[str]
    rollout_percentage: int
    source: str


def _is_in_rollout(rollout_percentage: int, user_key: str | None) -> bool:
    percentage = max(0, min(100, int(rollout_percentage)))
    if percentage >= 100:
        return True
    if percentage <= 0:
        return False
    if not user_key:
        return False
    digest = sha256(user_key.encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    return bucket < percentage


def resolve_policy(
    region_code: str | None,
    *,
    user_key: str | None = None,
    at_time: datetime | None = None,
) -> ResolvedPolicy:
    resolved_region = (region_code or "global").lower()
    now = at_time or timezone.now()
    candidate_regions = [resolved_region]
    if resolved_region != "global":
        candidate_regions.append("global")

    for candidate_region in candidate_regions:
        queryset = (
            PolicyPack.objects.filter(region_code=candidate_region, enabled=True)
            .filter(effective_from__lte=now)
            .filter(models.Q(effective_to__isnull=True) | models.Q(effective_to__gte=now))
            .order_by("-created_at")
        )
        for pack in queryset:
            if _is_in_rollout(pack.rollout_percentage, user_key):
                return ResolvedPolicy(
                    region_code=pack.region_code,
                    version=pack.version,
                    prohibited_categories=list(pack.prohibited_categories),
                    rollout_percentage=pack.rollout_percentage,
                    source="policy_pack",
                )

    return ResolvedPolicy(
        region_code=resolved_region,
        version="default-v1",
        prohibited_categories=DEFAULT_CATEGORIES,
        rollout_percentage=100,
        source="default",
    )
