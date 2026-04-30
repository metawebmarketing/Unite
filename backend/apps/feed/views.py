import base64
import json
from hashlib import sha256
from datetime import datetime

from django.conf import settings
from django.core.cache import cache
from django.db.models import Q
from django.db.models import Count, Exists, OuterRef
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.ranking import ensure_post_sentiment
from apps.accounts.models import Profile
from apps.connections.models import Connection
from apps.feed.cache_utils import get_user_feed_cache_version
from apps.feed.serializers import FeedConfigSerializer, FeedPageSerializer
from apps.feed.ranking import score_feed_items
from apps.feed.services import inject_feed_items, load_feed_config
from apps.feed.suggestions import build_suggestion_candidates
from apps.moderation.models import ModerationFlag
from apps.posts.models import Post
from apps.posts.models import PostInteraction
from apps.posts.services import build_link_preview

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
) -> str:
    raw = (
        f"user={user_id}|mode={mode}|cursor={cursor or 'none'}|size={page_size}|"
        f"region={region}|interest={interest_tag or 'none'}|fields={fields_signature}|v={user_cache_version}"
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
        cache_key = build_feed_cache_key(
            user_id=request.user.id,
            mode=mode,
            cursor=cursor,
            page_size=page_size,
            region=region_code,
            interest_tag=interest_tag,
            fields_signature=fields_signature,
            user_cache_version=get_user_feed_cache_version(request.user.id),
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
        hidden_private_user_ids = set()
        if not bool(getattr(request.user, "is_staff", False)):
            hidden_private_user_ids = set(
                Profile.objects.filter(is_private_profile=True)
                .exclude(user_id__in=connected_user_ids)
                .values_list("user_id", flat=True)
            )

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
            .order_by("-created_at", "-id")
        )
        if blocked_user_ids:
            posts_queryset = posts_queryset.exclude(author_id__in=blocked_user_ids)
        if hidden_private_user_ids:
            posts_queryset = posts_queryset.exclude(author_id__in=hidden_private_user_ids)

        if mode == "connections":
            posts_queryset = posts_queryset.filter(author_id__in=connected_user_ids)

        if cursor:
            try:
                payload = decode_cursor(cursor)
                cursor_created_at = datetime.fromisoformat(payload["created_at"])
                cursor_post_id = int(payload["post_id"])
                organic_offset = int(payload.get("organic_offset", 0))
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                return Response({"detail": "Invalid cursor."}, status=status.HTTP_400_BAD_REQUEST)
            posts_queryset = posts_queryset.filter(
                Q(created_at__lt=cursor_created_at)
                | (Q(created_at=cursor_created_at) & Q(id__lt=cursor_post_id))
            )
        if mode == "interest":
            filtered_posts: list[Post] = []
            for post in posts_queryset[:1000]:
                tags = post.interest_tags if isinstance(post.interest_tags, list) else []
                normalized = {str(item).strip().lower() for item in tags}
                if interest_tag in normalized:
                    filtered_posts.append(post)
                if len(filtered_posts) > page_size:
                    break
            selected_posts = filtered_posts
        else:
            selected_posts = list(posts_queryset[: page_size + 1])
        has_more = len(selected_posts) > page_size
        page_posts = selected_posts[:page_size]
        for post in page_posts:
            ensure_post_sentiment(post)
        cursor_anchor_post = page_posts[-1] if page_posts else None
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
                "like_count": post.like_count,
                "reply_count": post.reply_count,
                "sentiment_score": float(getattr(post, "sentiment_score", 0.0) or 0.0),
                "author_profile_score": float(
                    getattr(getattr(post.author, "profile", None), "rank_overall_score", 0.0) or 0.0
                ),
            }
            for post in page_posts
        ]
        ranked = score_feed_items(user_context=user_context, candidate_posts=candidate_posts)
        score_map = {item["id"]: item["rank_score"] for item in ranked}
        rank_order = [item["id"] for item in ranked]
        posts_by_id = {post.id: post for post in page_posts}
        ordered_page_posts = [posts_by_id[post_id] for post_id in rank_order if post_id in posts_by_id]

        organic_items = []
        for post in ordered_page_posts:
            post_data = {
                "id": post.id,
                "author_id": post.author_id,
                "author_username": post.author.username,
                "author_display_name": getattr(getattr(post.author, "profile", None), "display_name", "")
                or post.author.username,
                "author_profile_image_url": request.build_absolute_uri(post.author.profile.profile_image.url)
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
                organic_offset=organic_offset + len(page_posts),
            )

        serializer = FeedPageSerializer(
            {
                "items": injected_items,
                "next_cursor": next_cursor,
                "has_more": has_more,
                "organic_count": len(page_posts),
            }
        )
        payload = serializer.data
        cache.set(cache_key, payload, timeout=int(getattr(settings, "UNITE_FEED_CACHE_TTL_SECONDS", 30)))
        response = Response(payload)
        response["X-Feed-Cache"] = "MISS"
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
