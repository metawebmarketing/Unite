from dataclasses import dataclass

from django.conf import settings
from django.db.models import Q

from apps.accounts.models import Profile
from apps.connections.models import Connection
from apps.moderation.models import ModerationFlag


@dataclass
class SuggestionCandidate:
    user_id: int
    username: str
    display_name: str
    bio: str
    profile_image_url: str
    is_ai_account: bool
    ai_badge_enabled: bool
    shared_interest_count: int
    reason: str


def build_suggestion_candidates(*, user, limit: int = 40) -> list[dict]:
    if not hasattr(user, "profile") or not isinstance(user.profile.interests, list):
        return []
    user_interests = {str(item).strip().lower() for item in user.profile.interests if str(item).strip()}
    if not user_interests:
        return []

    connected_pairs = Connection.objects.filter(
        Q(requester=user, status=Connection.Status.ACCEPTED)
        | Q(recipient=user, status=Connection.Status.ACCEPTED)
    ).values_list("requester_id", "recipient_id")
    excluded_user_ids = {user.id}
    for requester_id, recipient_id in connected_pairs:
        excluded_user_ids.add(int(requester_id))
        excluded_user_ids.add(int(recipient_id))
    suppressed_categories = [
        str(item).strip().lower()
        for item in getattr(settings, "UNITE_FEED_SUPPRESSED_CATEGORIES", [])
        if str(item).strip()
    ]
    if suppressed_categories:
        flagged_profile_ids = set(
            ModerationFlag.objects.filter(
                content_type="profile",
                category__in=suppressed_categories,
            )
            .exclude(profile_id__isnull=True)
            .values_list("profile_id", flat=True)
        )
        excluded_user_ids.update(
            Profile.objects.filter(id__in=flagged_profile_ids).values_list("user_id", flat=True)
        )

    profiles = (
        Profile.objects.select_related("user")
        .exclude(user_id__in=excluded_user_ids)
        .order_by("-updated_at")[:300]
    )
    similar: list[SuggestionCandidate] = []
    diverse: list[SuggestionCandidate] = []
    for profile in profiles:
        interests = profile.interests if isinstance(profile.interests, list) else []
        normalized = {str(item).strip().lower() for item in interests if str(item).strip()}
        overlap = len(user_interests.intersection(normalized))
        candidate = SuggestionCandidate(
            user_id=profile.user_id,
            username=profile.user.username,
            display_name=profile.display_name or profile.user.username,
            bio=profile.bio or "",
            profile_image_url=profile.profile_image.url if profile.profile_image else "",
            is_ai_account=hasattr(profile.user, "ai_account"),
            ai_badge_enabled=bool(profile.user.ai_account.ai_badge_enabled)
            if hasattr(profile.user, "ai_account")
            else False,
            shared_interest_count=overlap,
            reason="similar_interests" if overlap > 0 else "diversity_injection",
        )
        if overlap > 0:
            similar.append(candidate)
        else:
            diverse.append(candidate)

    similar.sort(key=lambda item: item.shared_interest_count, reverse=True)
    ordered: list[SuggestionCandidate] = []
    similar_index = 0
    diverse_index = 0
    while len(ordered) < limit and (similar_index < len(similar) or diverse_index < len(diverse)):
        if similar_index < len(similar):
            ordered.append(similar[similar_index])
            similar_index += 1
        if len(ordered) % 5 == 4 and diverse_index < len(diverse):
            ordered.append(diverse[diverse_index])
            diverse_index += 1
    while len(ordered) < limit and similar_index < len(similar):
        ordered.append(similar[similar_index])
        similar_index += 1
    while len(ordered) < limit and diverse_index < len(diverse):
        ordered.append(diverse[diverse_index])
        diverse_index += 1
    return [
        {
            "user_id": item.user_id,
            "username": item.username,
            "display_name": item.display_name,
            "bio": item.bio,
            "profile_image_url": item.profile_image_url,
            "is_ai_account": item.is_ai_account,
            "ai_badge_enabled": item.ai_badge_enabled,
            "shared_interest_count": item.shared_interest_count,
            "reason": item.reason,
        }
        for item in ordered
    ]
