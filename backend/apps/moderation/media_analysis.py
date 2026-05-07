from __future__ import annotations

from dataclasses import dataclass
import os
import re

from apps.moderation.media_providers import MediaAnalysisResult


GRAPHIC_VIOLENCE = "graphic_violence"
NUDITY_PORNOGRAPHIC = "nudity_pornographic"
CHILD_SEXUAL_EXPLOITATIVE = "child_sexual_exploitative"
NON_GRAPHIC_VIOLENCE = "non_graphic_violence"
NON_GRAPHIC_NUDITY = "non_graphic_nudity"


POLICY_KEYWORDS: dict[str, tuple[str, ...]] = {
    GRAPHIC_VIOLENCE: ("graphic violence", "gore", "bloody fight", "murder", "execution"),
    NUDITY_PORNOGRAPHIC: ("porn", "sexual activity", "explicit nudity", "erotic"),
    CHILD_SEXUAL_EXPLOITATIVE: ("child sexual", "minor sexual", "csam", "csem"),
    NON_GRAPHIC_VIOLENCE: ("combat", "fight scene", "battle", "action game"),
    NON_GRAPHIC_NUDITY: ("art nude", "classical nude", "figure drawing"),
}

ALLOWED_EXCEPTION_CONTEXTS = {
    "artwork_non_graphic_nudity",
    "artwork_non_graphic_violence",
    "video_game_non_graphic_nudity",
    "video_game_non_graphic_violence",
}


@dataclass(frozen=True)
class MediaPolicyDecision:
    blocked: bool
    blocked_categories: list[str]
    matched_categories: list[str]


def quick_filename_precheck(filename: str) -> tuple[bool, list[str]]:
    normalized = str(filename or "").strip().lower()
    if not normalized:
        return False, []
    category_hits: list[str] = []
    if any(token in normalized for token in ("csam", "csem", "child-sex", "child_porn")):
        category_hits.append(CHILD_SEXUAL_EXPLOITATIVE)
    if any(token in normalized for token in ("gore", "beheading", "graphic-violence")):
        category_hits.append(GRAPHIC_VIOLENCE)
    if any(token in normalized for token in ("porn", "xxx", "explicit-nude")):
        category_hits.append(NUDITY_PORNOGRAPHIC)
    return len(category_hits) > 0, sorted(set(category_hits))


def _normalize_terms(values: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for value in values:
        token = str(value).strip().lower()
        if not token:
            continue
        compact = re.sub(r"[^a-z0-9_ -]+", " ", token)
        compact = re.sub(r"\s+", " ", compact).strip()
        if not compact or compact in seen:
            continue
        seen.add(compact)
        normalized.append(compact)
    return normalized


def derive_actionable_terms(*, text: str, interest_tags: list[str], media_terms: list[str]) -> list[str]:
    terms: list[str] = []
    terms.extend(str(tag).strip().lower() for tag in interest_tags if str(tag).strip())
    if text:
        terms.extend(
            token.strip().lower()
            for token in re.findall(r"[a-zA-Z0-9_]{3,}", text)
            if token.strip()
        )
    terms.extend(media_terms)
    return _normalize_terms(terms)[:128]


def detect_policy_categories(result: MediaAnalysisResult) -> list[str]:
    combined_terms: list[str] = []
    combined_terms.extend(result.actionable_terms)
    combined_terms.extend(result.category_scores.keys())
    blob = " ".join(combined_terms).lower()
    matched: list[str] = []
    for category, keywords in POLICY_KEYWORDS.items():
        if any(keyword in blob for keyword in keywords):
            matched.append(category)
    return sorted(set(matched))


def _is_exception_allowed(
    *,
    category: str,
    allowed_exceptions: list[str],
    is_artwork_source: bool,
    is_video_game_capture: bool,
) -> bool:
    exception_set = {str(item).strip().lower() for item in allowed_exceptions}
    if category == NON_GRAPHIC_NUDITY and is_artwork_source:
        return "artwork_non_graphic_nudity" in exception_set
    if category == NON_GRAPHIC_VIOLENCE and is_artwork_source:
        return "artwork_non_graphic_violence" in exception_set
    if category == NON_GRAPHIC_NUDITY and is_video_game_capture:
        return "video_game_non_graphic_nudity" in exception_set
    if category == NON_GRAPHIC_VIOLENCE and is_video_game_capture:
        return "video_game_non_graphic_violence" in exception_set
    return False


def resolve_policy_decision(
    *,
    detected_categories: list[str],
    prohibited_categories: list[str],
    allowed_exceptions: list[str],
    is_artwork_source: bool,
    is_video_game_capture: bool,
) -> MediaPolicyDecision:
    prohibited = {str(item).strip().lower() for item in prohibited_categories if str(item).strip()}
    blocked: list[str] = []
    matched: list[str] = []
    for category in sorted(set(detected_categories)):
        normalized = str(category).strip().lower()
        matched.append(normalized)
        if normalized not in prohibited:
            continue
        if _is_exception_allowed(
            category=normalized,
            allowed_exceptions=allowed_exceptions,
            is_artwork_source=is_artwork_source,
            is_video_game_capture=is_video_game_capture,
        ):
            continue
        blocked.append(normalized)
    return MediaPolicyDecision(
        blocked=len(blocked) > 0,
        blocked_categories=blocked,
        matched_categories=matched,
    )


def file_fingerprint(*, file_path: str, media_url: str, media_bytes: int) -> str:
    basename = os.path.basename(str(file_path or "")).strip().lower()
    return f"{media_url.strip().lower()}::{basename}::{int(media_bytes or 0)}"

