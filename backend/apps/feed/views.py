import base64
import json
from hashlib import sha256
from datetime import datetime, timedelta

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Q
from django.db.models import Count, Exists, OuterRef
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.connections.models import Connection
from apps.accounts.runtime_config import get_runtime_config
from apps.feed.cache_utils import get_user_feed_cache_version
from apps.feed.serializers import FeedConfigSerializer, FeedPageSerializer
from apps.feed.ranking import score_feed_items
from apps.feed.services import inject_feed_items, load_feed_config
from apps.feed.suggestions import build_suggestion_candidates
from apps.moderation.models import ModerationFlag
from apps.posts.models import Post
from apps.posts.models import PostInteraction
from apps.posts.media_intelligence import ensure_post_analysis
from apps.posts.services import build_link_preview
from apps.posts.storage import resolve_public_media_url

ALLOWED_POST_DATA_FIELDS = {
    "id",
    "author_id",
    "author_username",
    "author_display_name",
    "author_profile_image_url",
    "author_is_ai",
    "author_ai_badge_enabled",
    "author_is_connected",
    "author_profile_rank_score",
    "content",
    "interest_tags",
    "created_at",
    "link_preview",
    "rank_score",
    "interaction_counts",
    "has_liked",
    "has_bookmarked",
    "is_pinned",
    "sentiment_label",
    "sentiment_score",
    "attachments",
    "is_root_post",
}


def encode_cursor(created_at: datetime, post_id: int, organic_offset: int) -> str:
    payload = {
        "created_at": created_at.isoformat(),
        "post_id": post_id,
        "organic_offset": organic_offset,
    }
    raw = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> dict:
    raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
    return json.loads(raw.decode("utf-8"))


def build_feed_cache_key(
    *,
    user_id: int,
    mode: str,
    cursor: str | None,
    page_size: int,
    region: str,
    interest_tag: str | None,
    fields_signature: str,
    user_cache_version: int,
    policy_signature: str,
) -> str:
    raw = (
        f"user={user_id}|mode={mode}|cursor={cursor or 'none'}|size={page_size}|"
        f"region={region}|interest={interest_tag or 'none'}|fields={fields_signature}|"
        f"v={user_cache_version}|policy={policy_signature}"
    )
    digest = sha256(raw.encode("utf-8")).hexdigest()
    return f"feed:v2:{digest}"


def parse_requested_post_fields(raw_fields: str | None) -> set[str] | None:
    if not raw_fields:
        return None
    requested = {
        token.strip().lower()
        for token in raw_fields.split(",")
        if token and token.strip()
    }
    if not requested:
        return None
    selected = requested.intersection(ALLOWED_POST_DATA_FIELDS)
    if not selected:
        return None
    return selected


def _parse_feed_policy() -> dict[str, int]:
    runtime_config = get_runtime_config()
    return {
        "default_window_hours": max(
            1,
            int(
                runtime_config.get(
                    "feed_date_lookback_hours",
                    getattr(settings, "UNITE_FEED_FRESHNESS_WINDOW_HOURS", 168),
                )
            ),
        ),
        "interest_window_hours": max(1, int(getattr(settings, "UNITE_FEED_INTEREST_FRESHNESS_WINDOW_HOURS", 336))),
        "fallback_lookback_hours": max(
            1,
            int(
                runtime_config.get(
                    "feed_fallback_date_lookback_hours",
                    getattr(settings, "UNITE_FEED_FALLBACK_LOOKBACK_HOURS", 720),
                )
            ),
        ),
        "fallback_post_count": max(
            1,
            int(
                runtime_config.get(
                    "feed_fallback_post_count",
                    getattr(settings, "UNITE_FEED_FALLBACK_POST_COUNT", 100),
                )
            ),
        ),
        "max_candidates": max(50, int(getattr(settings, "UNITE_FEED_MAX_CANDIDATES", 250))),
        "min_rank_score": int(getattr(settings, "UNITE_FEED_MIN_RANK_SCORE", -250)),
    }


class FeedListView(APIView):
    def get(self, request):
        mode = request.query_params.get("mode", "both").lower()
        if mode not in {"connections", "suggestions", "both", "interest"}:
            return Response({"detail": "Invalid mode."}, status=status.HTTP_400_BAD_REQUEST)
        interest_tag = str(request.query_params.get("interest_tag", "")).strip().lower()
        if mode == "interest" and not interest_tag:
            return Response(
                {"detail": "interest_tag is required when mode=interest."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        region_code = request.user.profile.location if hasattr(request.user, "profile") else "global"
        user_interests = request.user.profile.interests if hasattr(request.user, "profile") else []
        is_ai_account = hasattr(request.user, "ai_account")
        user_experiment_flags = []
        if hasattr(request.user, "profile") and isinstance(request.user.profile.algorithm_vector, dict):
            raw_flags = request.user.profile.algorithm_vector.get("experiment_flags")
            if isinstance(raw_flags, list):
                user_experiment_flags = raw_flags
        config = load_feed_config(
            region_code=region_code,
            user_interest_tags=user_interests,
            is_ai_account=is_ai_account,
            user_experiment_flags=user_experiment_flags,
        )
        page_size = max(1, min(int(request.query_params.get("page_size", 20)), 50))
        cursor = request.query_params.get("cursor")
        requested_fields = parse_requested_post_fields(request.query_params.get("fields"))
        fields_signature = ",".join(sorted(requested_fields)) if requested_fields else "all"
        organic_offset = 0
        policy = _parse_feed_policy()
        policy_signature = (
            f"{policy['default_window_hours']}-"
            f"{policy['interest_window_hours']}-"
            f"{policy['fallback_lookback_hours']}-"
            f"{policy['fallback_post_count']}-"
            f"{policy['max_candidates']}-"
            f"{policy['min_rank_score']}"
        )
        cache_key = build_feed_cache_key(
            user_id=request.user.id,
            mode=mode,
            cursor=cursor,
            page_size=page_size,
            region=region_code,
            interest_tag=interest_tag,
            fields_signature=fields_signature,
            user_cache_version=get_user_feed_cache_version(request.user.id),
            policy_signature=policy_signature,
        )
        cached = cache.get(cache_key)
        if cached is not None:
            response = Response(cached)
            response["X-Feed-Cache"] = "HIT"
            return response
        suppressed_categories = tuple(
            str(item).strip().lower()
            for item in getattr(settings, "UNITE_FEED_SUPPRESSED_CATEGORIES", [])
            if str(item).strip()
        )
        now_ts = timezone.now()
        freshness_window_hours = (
            policy["interest_window_hours"] if mode == "interest" else policy["default_window_hours"]
        )
        freshness_cutoff = now_ts - timedelta(hours=freshness_window_hours)
        connected_pairs = Connection.objects.filter(
            status=Connection.Status.ACCEPTED,
        ).filter(
            Q(requester=request.user) | Q(recipient=request.user)
        ).values_list("requester_id", "recipient_id")
        connected_user_ids = {request.user.id}
        for requester_id, recipient_id in connected_pairs:
            connected_user_ids.add(int(requester_id))
            connected_user_ids.add(int(recipient_id))
        blocked_pairs = Connection.objects.filter(
            status=Connection.Status.BLOCKED,
        ).filter(
            Q(requester=request.user) | Q(recipient=request.user)
        ).values_list("requester_id", "recipient_id")
        blocked_user_ids: set[int] = set()
        for requester_id, recipient_id in blocked_pairs:
            if int(requester_id) != request.user.id:
                blocked_user_ids.add(int(requester_id))
            if int(recipient_id) != request.user.id:
                blocked_user_ids.add(int(recipient_id))
        is_staff_user = bool(getattr(request.user, "is_staff", False))

        posts_queryset = (
            Post.objects.select_related("author", "author__profile")
            .prefetch_related("attachments")
            .annotate(
                like_count=Count(
                    "interactions",
                    filter=Q(interactions__action_type=PostInteraction.ActionType.LIKE),
                ),
                reply_count=Count(
                    "interactions",
                    filter=Q(interactions__action_type=PostInteraction.ActionType.REPLY),
                ),
                repost_count=Count(
                    "interactions",
                    filter=Q(interactions__action_type=PostInteraction.ActionType.REPOST),
                ),
                quote_count=Count(
                    "interactions",
                    filter=Q(interactions__action_type=PostInteraction.ActionType.QUOTE),
                ),
                has_liked=Exists(
                    PostInteraction.objects.filter(
                        post_id=OuterRef("pk"),
                        user=request.user,
                        action_type=PostInteraction.ActionType.LIKE,
                    )
                ),
                has_bookmarked=Exists(
                    PostInteraction.objects.filter(
                        post_id=OuterRef("pk"),
                        user=request.user,
                        action_type=PostInteraction.ActionType.BOOKMARK,
                    )
                ),
                author_is_connected=Exists(
                    Connection.objects.filter(
                        status=Connection.Status.ACCEPTED,
                    ).filter(
                        Q(requester=request.user, recipient_id=OuterRef("author_id"))
                        | Q(requester_id=OuterRef("author_id"), recipient=request.user)
                    )
                ),
                has_safety_flag=Exists(
                    ModerationFlag.objects.filter(
                        content_type="post",
                        content_id=OuterRef("pk"),
                        category__in=suppressed_categories if suppressed_categories else ["__none__"],
                    )
                )
                if suppressed_categories
                else Exists(ModerationFlag.objects.none()),
            )
            .filter(has_safety_flag=False)
            .filter(parent_post__isnull=True)
            .exclude(author_id=request.user.id)
            .order_by("-created_at", "-id")
        )
        if blocked_user_ids:
            posts_queryset = posts_queryset.exclude(author_id__in=blocked_user_ids)
        if not is_staff_user:
            posts_queryset = posts_queryset.exclude(
                Q(author__profile__is_private_profile=True) & ~Q(author_id__in=connected_user_ids)
            )

        if mode == "connections":
            posts_queryset = posts_queryset.filter(author_id__in=connected_user_ids)

        if cursor:
            try:
                payload = decode_cursor(cursor)
                organic_offset = int(payload.get("organic_offset", 0))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                return Response({"detail": "Invalid cursor."}, status=status.HTTP_400_BAD_REQUEST)
        if mode == "interest" and connection.features.supports_json_field_contains:
            posts_queryset = posts_queryset.filter(interest_tags__contains=[interest_tag])
        candidate_limit = max(page_size + 1, policy["max_candidates"])
        offset_start = max(0, organic_offset)
        primary_queryset = posts_queryset.filter(created_at__gte=freshness_cutoff)
        selected_posts = list(primary_queryset[:candidate_limit])
        if len(selected_posts) < policy["fallback_post_count"]:
            fallback_window_hours = max(freshness_window_hours, policy["fallback_lookback_hours"])
            if fallback_window_hours > freshness_window_hours:
                fallback_cutoff = now_ts - timedelta(hours=fallback_window_hours)
                selected_posts = list(posts_queryset.filter(created_at__gte=fallback_cutoff)[:candidate_limit])
                freshness_window_hours = fallback_window_hours
                if len(selected_posts) < policy["fallback_post_count"]:
                    selected_posts = list(posts_queryset[:candidate_limit])
        if mode == "interest" and not connection.features.supports_json_field_contains:
            filtered_posts: list[Post] = []
            for post in selected_posts:
                tags = post.interest_tags if isinstance(post.interest_tags, list) else []
                normalized_tags = {str(item).strip().lower() for item in tags if str(item).strip()}
                if interest_tag in normalized_tags:
                    filtered_posts.append(post)
                if len(filtered_posts) >= candidate_limit:
                    break
            selected_posts = filtered_posts
        page_posts = selected_posts
        for post in page_posts:
            should_refresh_analysis = bool(getattr(post, "needs_analysis_refresh", False)) or str(
                getattr(post, "analysis_status", "pending")
            ).strip().lower() in {"pending", "processing", "failed"}
            if should_refresh_analysis:
                ensure_post_analysis(post=post, region_code=region_code)
        user_context = {}
        if hasattr(request.user, "profile"):
            profile = request.user.profile
            if isinstance(profile.algorithm_vector, dict):
                user_context = {**profile.algorithm_vector}
            if isinstance(profile.interests, list):
                user_context["profile_interests"] = profile.interests
        if interest_tag:
            user_context["active_interest_tag"] = interest_tag
        candidate_posts = [
            {
                "id": post.id,
                "interest_tags": post.interest_tags if isinstance(post.interest_tags, list) else [],
                "media_action_terms": list(getattr(post, "analysis_terms", []) or []),
                "like_count": post.like_count,
                "reply_count": post.reply_count,
                "sentiment_score": float(getattr(post, "sentiment_score", 0.0) or 0.0),
                "author_profile_score": float(
                    getattr(getattr(post.author, "profile", None), "rank_overall_score", 0.0) or 0.0
                ),
                "created_at": post.created_at.isoformat(),
            }
            for post in page_posts
        ]
        user_context["now_ts"] = now_ts
        ranked = score_feed_items(user_context=user_context, candidate_posts=candidate_posts)
        score_map = {item["id"]: item["rank_score"] for item in ranked}
        rank_order = [item["id"] for item in ranked]
        posts_by_id = {post.id: post for post in page_posts}
        ordered_posts = [posts_by_id[post_id] for post_id in rank_order if post_id in posts_by_id]
        has_more = len(ordered_posts) > (offset_start + page_size)
        ordered_page_posts = ordered_posts[offset_start : offset_start + page_size]
        cursor_anchor_post = ordered_page_posts[-1] if ordered_page_posts else None

        organic_items = []
        for post in ordered_page_posts:
            attachments = [
                {
                    "media_type": attachment.media_type,
                    "media_url": resolve_public_media_url(attachment.media_url, request),
                    "thumbnail_url": resolve_public_media_url(attachment.thumbnail_url, request),
                    "hls_manifest_url": resolve_public_media_url(attachment.hls_manifest_url, request),
                    "processing_status": str(attachment.processing_status or "ready"),
                    "media_bytes": int(attachment.media_bytes or 0),
                }
                for attachment in post.attachments.all()
            ]
            post_data = {
                "id": post.id,
                "author_id": post.author_id,
                "author_username": post.author.username,
                "author_display_name": getattr(getattr(post.author, "profile", None), "display_name", "")
                or post.author.username,
                "author_profile_image_url": resolve_public_media_url(post.author.profile.profile_image.url, request)
                if hasattr(post.author, "profile") and getattr(post.author.profile, "profile_image", None)
                else "",
                "author_is_ai": hasattr(post.author, "ai_account"),
                "author_ai_badge_enabled": bool(post.author.ai_account.ai_badge_enabled)
                if hasattr(post.author, "ai_account")
                else False,
                "author_is_connected": bool(getattr(post, "author_is_connected", False)),
                "author_profile_rank_score": float(
                    getattr(getattr(post.author, "profile", None), "rank_overall_score", 0.0) or 0.0
                ),
                "content": post.content or "No content provided.",
                "interest_tags": post.interest_tags if isinstance(post.interest_tags, list) else [],
                "created_at": post.created_at.isoformat(),
                "link_preview": (
                    post.link_preview
                    if isinstance(post.link_preview, dict) and str(post.link_preview.get("image_url") or "").strip()
                    else build_link_preview(str(post.link_url or "").strip()) if str(post.link_url or "").strip() else {}
                ),
                "rank_score": score_map.get(post.id, 0),
                "interaction_counts": {
                    "like": post.like_count,
                    "reply": post.reply_count,
                    "repost": post.repost_count,
                    "quote": post.quote_count,
                },
                "has_liked": bool(post.has_liked),
                "has_bookmarked": bool(post.has_bookmarked),
                "is_pinned": bool(post.is_pinned),
                "sentiment_label": str(getattr(post, "sentiment_label", "neutral") or "neutral"),
                "sentiment_score": float(getattr(post, "sentiment_score", 0.0) or 0.0),
                "analysis_status": str(getattr(post, "analysis_status", "pending") or "pending"),
                "attachments": attachments,
                "is_root_post": True,
            }
            if requested_fields is not None:
                post_data = {key: value for key, value in post_data.items() if key in requested_fields}
            organic_items.append(
                {
                    "item_type": "post",
                    "source_module": "organic",
                    "injection_reason": "",
                    "data": post_data,
                }
            )
        injected_items = inject_feed_items(
            organic_items=organic_items,
            mode=mode,
            config=config,
            organic_offset=organic_offset,
            suggestion_candidates=build_suggestion_candidates(user=request.user),
        )
        connected_for_suggestions = {item for item in connected_user_ids if item != request.user.id}
        for item in injected_items:
            if item.get("item_type") != "suggestion":
                continue
            data = item.get("data", {})
            profile_image_url = str(data.get("profile_image_url", "")).strip()
            if profile_image_url and profile_image_url.startswith("/"):
                data["profile_image_url"] = request.build_absolute_uri(profile_image_url)
            suggestion_user_id = int(data.get("user_id") or 0)
            data["is_connected"] = suggestion_user_id in connected_for_suggestions

        next_cursor = None
        if has_more and cursor_anchor_post:
            next_cursor = encode_cursor(
                created_at=cursor_anchor_post.created_at,
                post_id=cursor_anchor_post.id,
                organic_offset=organic_offset + len(ordered_page_posts),
            )
            if bool(getattr(settings, "UNITE_FEED_NEXT_CURSOR_PREFETCH_ENABLED", True)):
                prefetch_key = (
                    f"feed:next-cursor:{int(request.user.id)}:{mode}:{interest_tag or 'none'}:{next_cursor}"
                )
                cache.set(
                    prefetch_key,
                    {
                        "page_size": int(getattr(settings, "UNITE_FEED_NEXT_CURSOR_PREFETCH_PAGE_SIZE", 20)),
                        "created_at": now_ts.isoformat(),
                    },
                    timeout=int(getattr(settings, "UNITE_FEED_CACHE_TTL_SECONDS", 30)),
                )

        serializer = FeedPageSerializer(
            {
                "items": injected_items,
                "next_cursor": next_cursor,
                "has_more": has_more,
                "organic_count": len(ordered_page_posts),
                "policy_version": policy_signature,
            }
        )
        payload = serializer.data
        cache.set(cache_key, payload, timeout=int(getattr(settings, "UNITE_FEED_CACHE_TTL_SECONDS", 30)))
        response = Response(payload)
        response["X-Feed-Cache"] = "MISS"
        response["X-Feed-Candidate-Cap"] = str(policy["max_candidates"])
        response["X-Feed-Freshness-Hours"] = str(freshness_window_hours)
        return response


class FeedConfigView(APIView):
    permission_classes = [permissions.IsAdminUser]

    def get(self, request):
        region_code = request.user.profile.location if hasattr(request.user, "profile") else "global"
        user_interests = request.user.profile.interests if hasattr(request.user, "profile") else []
        user_experiment_flags = []
        if hasattr(request.user, "profile") and isinstance(request.user.profile.algorithm_vector, dict):
            raw_flags = request.user.profile.algorithm_vector.get("experiment_flags")
            if isinstance(raw_flags, list):
                user_experiment_flags = raw_flags
        config = load_feed_config(
            region_code=region_code,
            user_interest_tags=user_interests,
            is_ai_account=hasattr(request.user, "ai_account"),
            user_experiment_flags=user_experiment_flags,
        )
        serializer = FeedConfigSerializer(config.__dict__)
        return Response(serializer.data)
