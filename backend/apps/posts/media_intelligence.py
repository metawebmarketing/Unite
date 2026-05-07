from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import os
import tempfile

from django.utils import timezone

from apps.accounts.ranking import ensure_post_sentiment
from apps.moderation.media_analysis import derive_actionable_terms, file_fingerprint
from apps.moderation.media_providers import get_media_provider
from apps.moderation.models import ModerationFlag
from apps.moderation.services import evaluate_media_asset, is_content_blocked
from apps.policy.services import resolve_policy
from apps.posts.models import MediaAttachment, Post, UploadedMediaAsset
from apps.posts.storage import get_media_storage_for_mode


@dataclass(frozen=True)
class PostAnalysisOutcome:
    status: str
    blocked_categories: list[str]
    actionable_terms: list[str]


def compute_post_fingerprint(post: Post) -> str:
    attachment_tokens = []
    for attachment in post.attachments.all():
        attachment_tokens.append(
            f"{attachment.media_type}:{attachment.media_url}:{attachment.processing_status}:{attachment.media_bytes}"
        )
    payload = "|".join(
        [
            str(post.content or ""),
            str(post.link_url or ""),
            ",".join(sorted(str(item).strip().lower() for item in list(post.interest_tags or []))),
            ",".join(sorted(attachment_tokens)),
        ]
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def compute_interaction_fingerprint(
    *,
    action_type: str,
    post_id: int,
    content: str,
    link_url: str,
    attachments: list[dict],
) -> str:
    attachment_tokens = [
        f"{str(item.get('media_type', '')).strip().lower()}:{str(item.get('media_url', '')).strip()}"
        for item in attachments
    ]
    payload = "|".join(
        [
            str(action_type or ""),
            str(post_id),
            str(content or ""),
            str(link_url or ""),
            ",".join(sorted(attachment_tokens)),
        ]
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def ensure_uploaded_media_asset_analysis(
    *,
    asset: UploadedMediaAsset,
    region_code: str,
    force: bool = False,
) -> dict:
    fingerprint = file_fingerprint(
        file_path=asset.storage_saved_name or asset.media_url,
        media_url=asset.media_url,
        media_bytes=int(asset.media_bytes or 0),
    )
    if (
        not force
        and not bool(asset.needs_analysis_refresh)
        and str(asset.analysis_fingerprint or "") == fingerprint
        and str(asset.analysis_status or "") in {"approved", "blocked", "failed"}
    ):
        return {
            "status": str(asset.analysis_status),
            "blocked_categories": list(asset.analysis_categories or []),
            "actionable_terms": list(asset.analysis_terms or []),
            "skipped": True,
        }

    try:
        storage = get_media_storage_for_mode(str(asset.storage_mode or "local").strip().lower() or "local")
        saved_name = str(asset.storage_saved_name or "").strip()
        if not saved_name and str(asset.media_url or "").startswith("/media/"):
            saved_name = str(asset.media_url).split("/media/", 1)[-1].lstrip("/")
        if not saved_name:
            raise RuntimeError("Missing storage reference for media analysis.")
        with tempfile.TemporaryDirectory(prefix="unite-media-analysis-") as temp_dir:
            suffix = ".mp4" if str(asset.media_type) == MediaAttachment.MediaType.VIDEO else ".jpg"
            local_path = os.path.join(temp_dir, f"asset{suffix}")
            with storage.open(saved_name, "rb") as source_stream:
                with open(local_path, "wb") as output_file:
                    for chunk in source_stream.chunks():
                        output_file.write(chunk)
            provider = get_media_provider(str(asset.media_type or ""))
            if str(asset.media_type) == MediaAttachment.MediaType.VIDEO:
                result = provider.analyze_video(local_path)
            else:
                result = provider.analyze_image(local_path)
    except Exception as exc:
        asset.analysis_status = UploadedMediaAsset.AnalysisStatus.FAILED
        asset.analysis_fingerprint = fingerprint
        asset.analysis_payload = {"error": str(exc)}
        asset.analysis_completed_at = timezone.now()
        asset.needs_analysis_refresh = False
        asset.save(
            update_fields=[
                "analysis_status",
                "analysis_fingerprint",
                "analysis_payload",
                "analysis_completed_at",
                "needs_analysis_refresh",
                "updated_at",
            ]
        )
        return {"status": "failed", "blocked_categories": [], "actionable_terms": []}

    detected_categories = list(result.category_scores.keys())
    policy = resolve_policy(region_code)
    blocked, blocked_categories = evaluate_media_asset(
        asset=asset,
        region_code=region_code,
    )
    status = UploadedMediaAsset.AnalysisStatus.BLOCKED if blocked else UploadedMediaAsset.AnalysisStatus.APPROVED
    asset.analysis_status = status
    asset.analysis_fingerprint = fingerprint
    asset.analysis_terms = list(result.actionable_terms)
    merged_categories = sorted(set(detected_categories).union(blocked_categories))
    asset.analysis_categories = merged_categories
    asset.analysis_payload = dict(result.metadata)
    asset.analysis_provider = str(result.metadata.get("provider", ""))
    asset.analysis_model_name = str(result.metadata.get("model", ""))
    asset.analysis_completed_at = timezone.now()
    asset.needs_analysis_refresh = False
    asset.save(
        update_fields=[
            "analysis_status",
            "analysis_fingerprint",
            "analysis_terms",
            "analysis_categories",
            "analysis_payload",
            "analysis_provider",
            "analysis_model_name",
            "analysis_completed_at",
            "needs_analysis_refresh",
            "updated_at",
        ]
    )
    if blocked:
        MediaAttachment.objects.filter(media_url=asset.media_url, media_type=asset.media_type).update(
            processing_status=UploadedMediaAsset.ProcessingStatus.FAILED
        )
    return {
        "status": status,
        "blocked_categories": blocked_categories,
        "actionable_terms": list(result.actionable_terms),
        "allowed_exceptions": list(policy.allowed_exceptions or []),
    }


def ensure_post_analysis(*, post: Post, region_code: str) -> PostAnalysisOutcome:
    fingerprint = compute_post_fingerprint(post)
    modules = dict(post.analysis_modules or {})
    if (
        not bool(post.needs_analysis_refresh)
        and str(post.analysis_fingerprint or "") == fingerprint
        and str(post.analysis_status or "") in {"approved", "blocked", "failed"}
    ):
        return PostAnalysisOutcome(
            status=str(post.analysis_status),
            blocked_categories=list(post.analysis_blocked_categories or []),
            actionable_terms=list(post.analysis_terms or []),
        )

    blocked_categories: set[str] = set()
    media_terms: list[str] = []
    for attachment in post.attachments.all():
        asset = (
            UploadedMediaAsset.objects.filter(
                media_url=str(attachment.media_url or "").strip(),
                media_type=str(attachment.media_type or "").strip(),
            )
            .order_by("-updated_at")
            .first()
        )
        if not asset:
            continue
        media_outcome = ensure_uploaded_media_asset_analysis(asset=asset, region_code=region_code)
        blocked_categories.update(str(item).strip().lower() for item in media_outcome.get("blocked_categories", []))
        media_terms.extend(str(item).strip().lower() for item in media_outcome.get("actionable_terms", []))

    text_blob = f"{str(post.content or '')} {str(post.link_url or '')}".strip()
    text_blocked, text_categories = is_content_blocked(
        text=text_blob,
        region_code=region_code,
        content_type="post",
        content_id=post.id,
        profile_id=getattr(getattr(post.author, "profile", None), "id", None),
    )
    if text_blocked:
        blocked_categories.update(str(item).strip().lower() for item in text_categories)

    content_signature = sha256(text_blob.encode("utf-8")).hexdigest()
    sentiment_meta = dict(modules.get("sentiment") or {})
    if sentiment_meta.get("fingerprint") != content_signature or bool(post.sentiment_needs_rescore):
        ensure_post_sentiment(post)
        modules["sentiment"] = {"fingerprint": content_signature, "completed": True}

    terms = derive_actionable_terms(
        text=str(post.content or ""),
        interest_tags=list(post.interest_tags or []),
        media_terms=media_terms,
    )
    status = Post.AnalysisStatus.BLOCKED if blocked_categories else Post.AnalysisStatus.APPROVED
    post.analysis_status = status
    post.analysis_fingerprint = fingerprint
    post.analysis_terms = terms
    post.analysis_blocked_categories = sorted(blocked_categories)
    post.analysis_modules = modules
    post.analysis_completed_at = timezone.now()
    post.needs_analysis_refresh = False
    post.save(
        update_fields=[
            "analysis_status",
            "analysis_fingerprint",
            "analysis_terms",
            "analysis_blocked_categories",
            "analysis_modules",
            "analysis_completed_at",
            "needs_analysis_refresh",
            "updated_at",
        ]
    )
    for category in sorted(blocked_categories):
        ModerationFlag.objects.get_or_create(
            profile_id=getattr(getattr(post.author, "profile", None), "id", None),
            content_type="post",
            content_id=post.id,
            category=category,
            defaults={
                "reason": "Post media intelligence policy block",
                "payload": {"post_id": post.id},
                "policy_region": region_code,
                "policy_version": "media-intelligence-v1",
            },
        )
    return PostAnalysisOutcome(
        status=status,
        blocked_categories=sorted(blocked_categories),
        actionable_terms=terms,
    )
