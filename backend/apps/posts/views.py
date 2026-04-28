from datetime import timedelta
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import SuspiciousFileOperation
from django.core.files.storage import default_storage
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.ranking import (
    ensure_post_sentiment,
    is_post_toxic,
    record_profile_action_score,
    score_post_sentiment,
)
from apps.ai_accounts.services import log_ai_action
from apps.moderation.models import ModerationFlag
from apps.moderation.services import is_content_blocked
from apps.connections.models import Connection
from apps.feed.sentiment_providers import score_sentiment_text
from apps.notifications.services import create_notification
from apps.posts.idempotency import (
    hash_request_payload,
    load_idempotent_response,
    save_idempotent_response,
)
from apps.posts.image_processing import optimize_post_image
from apps.posts.models import IdempotencyRecord, MediaAttachment, Post, PostInteraction, SyncReplayEvent
from apps.posts.serializers import PostSerializer, ReactSerializer
from apps.posts.sync_serializers import SyncReplayEventIngestSerializer
from apps.feed.cache_utils import bump_user_feed_cache_version


def get_request_ip_address(request) -> str | None:
    forwarded_for = str(request.META.get("HTTP_X_FORWARDED_FOR", "")).strip()
    if forwarded_for:
        first_ip = forwarded_for.split(",")[0].strip()
        if first_ip:
            return first_ip
    remote_addr = str(request.META.get("REMOTE_ADDR", "")).strip()
    return remote_addr or None


def build_post_queryset_for_user(user):
    return (
        Post.objects.select_related("author")
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
                    user=user,
                    action_type=PostInteraction.ActionType.LIKE,
                )
            ),
            has_bookmarked=Exists(
                PostInteraction.objects.filter(
                    post_id=OuterRef("pk"),
                    user=user,
                    action_type=PostInteraction.ActionType.BOOKMARK,
                )
            ),
            author_is_connected=Exists(
                Connection.objects.filter(
                    status=Connection.Status.ACCEPTED,
                ).filter(
                    Q(requester=user, recipient_id=OuterRef("author_id"))
                    | Q(requester_id=OuterRef("author_id"), recipient=user)
                )
            ),
        )
    )


def serialize_post_with_author(post, request) -> dict:
    ensure_post_sentiment(post)
    payload = dict(PostSerializer(post).data)
    payload["interaction_counts"] = {
        "like": post.like_count,
        "reply": post.reply_count,
        "repost": post.repost_count,
        "quote": post.quote_count,
    }
    payload["has_liked"] = bool(post.has_liked)
    payload["has_bookmarked"] = bool(post.has_bookmarked)
    payload["is_pinned"] = bool(post.is_pinned)
    payload["author_username"] = post.author.username
    payload["author_display_name"] = getattr(getattr(post.author, "profile", None), "display_name", "") or post.author.username
    payload["author_profile_image_url"] = (
        request.build_absolute_uri(post.author.profile.profile_image.url)
        if hasattr(post.author, "profile") and getattr(post.author.profile, "profile_image", None)
        else ""
    )
    payload["author_is_ai"] = hasattr(post.author, "ai_account")
    payload["author_ai_badge_enabled"] = (
        bool(post.author.ai_account.ai_badge_enabled) if hasattr(post.author, "ai_account") else False
    )
    payload["author_is_connected"] = bool(getattr(post, "author_is_connected", False))
    payload["author_profile_rank_score"] = float(
        getattr(getattr(post.author, "profile", None), "rank_overall_score", 0.0) or 0.0
    )
    payload["sentiment_label"] = str(getattr(post, "sentiment_label", "neutral") or "neutral")
    payload["sentiment_score"] = float(getattr(post, "sentiment_score", 0.0) or 0.0)
    return payload


def emit_post_mentions(*, tagged_user_ids: list[int], actor_user, post_id: int, interaction_id: int | None = None) -> None:
    unique_user_ids: set[int] = set()
    for user_id in tagged_user_ids:
        try:
            normalized = int(user_id)
        except (TypeError, ValueError):
            continue
        if normalized > 0 and normalized != actor_user.id:
            unique_user_ids.add(normalized)
    for recipient_id in unique_user_ids:
        create_notification(
            recipient_user_id=recipient_id,
            actor_user_id=actor_user.id,
            event_type="post.mention",
            title="You were mentioned",
            message=f"@{actor_user.username} mentioned you in a post.",
            payload={
                "post_id": int(post_id),
                "interaction_id": int(interaction_id) if interaction_id else None,
            },
        )


class PostImageUploadView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "post_upload_image"
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        image_file = request.FILES.get("image")
        if not image_file:
            return Response({"detail": "Image file is required."}, status=status.HTTP_400_BAD_REQUEST)
        content_type = str(getattr(image_file, "content_type", "") or "").lower()
        if not content_type.startswith("image/"):
            return Response({"detail": "Only image uploads are allowed."}, status=status.HTTP_400_BAD_REQUEST)
        max_bytes = int(getattr(settings, "UNITE_POST_IMAGE_MAX_BYTES", 8 * 1024 * 1024))
        if max_bytes > 0 and int(getattr(image_file, "size", 0) or 0) > max_bytes:
            return Response(
                {"detail": "Image exceeds maximum upload size."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            processed = optimize_post_image(
                image_file,
                max_width=int(getattr(settings, "UNITE_POST_IMAGE_MAX_WIDTH", 1600)),
                max_height=int(getattr(settings, "UNITE_POST_IMAGE_MAX_HEIGHT", 1600)),
                quality=int(getattr(settings, "UNITE_POST_IMAGE_QUALITY", 85)),
            )
            filename = f"post-{request.user.id}-{uuid4().hex}.jpg"
            save_path = f"posts/{request.user.id}/{filename}"
            saved_name = default_storage.save(save_path, processed)
            media_url = default_storage.url(saved_name)
        except (SuspiciousFileOperation, OSError, ValueError):
            return Response({"detail": "Unable to process image upload."}, status=status.HTTP_400_BAD_REQUEST)
        absolute_media_url = request.build_absolute_uri(media_url)
        return Response(
            {"media_type": "image", "media_url": absolute_media_url},
            status=status.HTTP_201_CREATED,
        )


class PostListCreateView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "post_write"
    ai_throttle_scope = "post_write_ai"

    def resolve_throttle_scope(self, user) -> str:
        return self.ai_throttle_scope if hasattr(user, "ai_account") else "post_write"

    def get_throttles(self):
        if self.request.method == "GET":
            return []
        self.throttle_scope = self.resolve_throttle_scope(self.request.user)
        return super().get_throttles()

    def get(self, request):
        queryset = build_post_queryset_for_user(request.user).filter(parent_post__isnull=True)[:50]
        serializer = PostSerializer(queryset, many=True)
        return Response(_serialize_posts(serializer.data, queryset))

    def post(self, request):
        def ai_log(status_code: int, payload: dict) -> None:
            log_ai_action(
                user=request.user,
                action_name="post_create",
                endpoint=request.path,
                method=request.method,
                status_code=status_code,
                payload={"response": payload},
            )

        idempotency_key = request.headers.get("Idempotency-Key")
        request_hash = hash_request_payload(request.data if isinstance(request.data, dict) else {})
        if idempotency_key:
            payload, status_code, found = load_idempotent_response(
                user_id=request.user.id,
                endpoint="posts.create",
                key=idempotency_key,
                request_hash=request_hash,
            )
            if found:
                ai_log(status_code, payload)
                return Response(payload, status=status_code)

        serializer = PostSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_ip_address = get_request_ip_address(request)
        region_code = request.user.profile.location if hasattr(request.user, "profile") else "global"
        burst_window_seconds = int(getattr(settings, "UNITE_SPAM_BURST_WINDOW_SECONDS", 60))
        burst_max_posts = int(getattr(settings, "UNITE_SPAM_BURST_MAX_POSTS", 5))
        repeated_link_window_seconds = int(getattr(settings, "UNITE_SPAM_LINK_WINDOW_SECONDS", 600))
        repeated_link_max_posts = int(getattr(settings, "UNITE_SPAM_LINK_MAX_POSTS", 3))
        if burst_window_seconds > 0 and burst_max_posts > 0:
            recent_count = Post.objects.filter(
                author=request.user,
                created_at__gte=timezone.now() - timedelta(seconds=burst_window_seconds),
            ).count()
            if recent_count >= burst_max_posts:
                response_payload = {
                    "detail": "Posting too quickly. Please wait before posting again.",
                    "spam_rule": "burst_post_limit",
                }
                if idempotency_key:
                    save_idempotent_response(
                        user_id=request.user.id,
                        endpoint="posts.create",
                        key=idempotency_key,
                        request_hash=request_hash,
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        response_body=response_payload,
                    )
                ai_log(status.HTTP_429_TOO_MANY_REQUESTS, response_payload)
                return Response(response_payload, status=status.HTTP_429_TOO_MANY_REQUESTS)
        blocked, categories = is_content_blocked(
            text=f"{serializer.validated_data['content']} {serializer.validated_data.get('link_url', '')}",
            region_code=region_code,
            content_type="post",
            profile_id=getattr(request.user.profile, "id", None) if hasattr(request.user, "profile") else None,
        )
        if blocked:
            response_payload = {
                "detail": "Content violates policy.",
                "blocked_categories": categories,
            }
            if idempotency_key:
                save_idempotent_response(
                    user_id=request.user.id,
                    endpoint="posts.create",
                    key=idempotency_key,
                    request_hash=request_hash,
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    response_body=response_payload,
                )
            ai_log(status.HTTP_422_UNPROCESSABLE_ENTITY, response_payload)
            return Response(
                {
                    **response_payload,
                },
                status=status.HTTP_422_UNPROCESSABLE_ENTITY,
            )
        recent_duplicate_exists = Post.objects.filter(
            author=request.user,
            content=serializer.validated_data["content"],
            created_at__gte=timezone.now() - timedelta(seconds=30),
        ).exists()
        if recent_duplicate_exists:
            response_payload = {"detail": "Duplicate content detected. Please wait before reposting."}
            if idempotency_key:
                save_idempotent_response(
                    user_id=request.user.id,
                    endpoint="posts.create",
                    key=idempotency_key,
                    request_hash=request_hash,
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    response_body=response_payload,
                )
            ai_log(status.HTTP_429_TOO_MANY_REQUESTS, response_payload)
            return Response(response_payload, status=status.HTTP_429_TOO_MANY_REQUESTS)
        link_url = serializer.validated_data.get("link_url", "")
        if link_url and repeated_link_window_seconds > 0 and repeated_link_max_posts > 0:
            repeated_link_count = Post.objects.filter(
                author=request.user,
                link_url=link_url,
                created_at__gte=timezone.now() - timedelta(seconds=repeated_link_window_seconds),
            ).count()
            if repeated_link_count >= repeated_link_max_posts:
                response_payload = {
                    "detail": "Repeated link sharing detected. Please vary links or wait before reposting.",
                    "spam_rule": "repeated_link_limit",
                }
                if idempotency_key:
                    save_idempotent_response(
                        user_id=request.user.id,
                        endpoint="posts.create",
                        key=idempotency_key,
                        request_hash=request_hash,
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        response_body=response_payload,
                    )
                ai_log(status.HTTP_429_TOO_MANY_REQUESTS, response_payload)
                return Response(response_payload, status=status.HTTP_429_TOO_MANY_REQUESTS)
        created_post = serializer.save(author=request.user, ip_address=request_ip_address)
        sentiment_label, sentiment_score = score_post_sentiment(created_post)
        emit_post_mentions(
            tagged_user_ids=created_post.tagged_user_ids if isinstance(created_post.tagged_user_ids, list) else [],
            actor_user=request.user,
            post_id=created_post.id,
        )
        if hasattr(request.user, "profile"):
            record_profile_action_score(
                profile=request.user.profile,
                action_type="post",
                sentiment_label=sentiment_label,
                sentiment_score=sentiment_score,
                post=created_post,
                metadata={"source": "post_create"},
            )
        bump_user_feed_cache_version(request.user.id)
        response_payload = dict(serializer.data)
        response_payload["sentiment_label"] = sentiment_label
        response_payload["sentiment_score"] = sentiment_score
        if idempotency_key:
            save_idempotent_response(
                user_id=request.user.id,
                endpoint="posts.create",
                key=idempotency_key,
                request_hash=request_hash,
                status_code=status.HTTP_201_CREATED,
                response_body=response_payload,
            )
        ai_log(status.HTTP_201_CREATED, response_payload)
        return Response(response_payload, status=status.HTTP_201_CREATED)


class PostReactView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "post_react"
    ai_throttle_scope = "post_react_ai"

    def resolve_throttle_scope(self, user) -> str:
        return self.ai_throttle_scope if hasattr(user, "ai_account") else "post_react"

    def get_throttles(self):
        self.throttle_scope = self.resolve_throttle_scope(self.request.user)
        return super().get_throttles()

    def post(self, request, post_id: int):
        def ai_log(status_code: int, payload: dict) -> None:
            log_ai_action(
                user=request.user,
                action_name="post_react",
                endpoint=request.path,
                method=request.method,
                status_code=status_code,
                payload={"response": payload, "post_id": post_id},
            )

        idempotency_key = request.headers.get("Idempotency-Key")
        request_hash = hash_request_payload(request.data if isinstance(request.data, dict) else {})
        if idempotency_key:
            payload, status_code, found = load_idempotent_response(
                user_id=request.user.id,
                endpoint=f"posts.react:{post_id}",
                key=idempotency_key,
                request_hash=request_hash,
            )
            if found:
                ai_log(status_code, payload)
                return Response(payload, status=status_code)

        serializer = ReactSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request_ip_address = get_request_ip_address(request)
        action = serializer.validated_data["action"]
        content = serializer.validated_data.get("content", "")
        link_url = serializer.validated_data.get("link_url", "")
        attachments = serializer.validated_data.get("attachments", [])
        tagged_user_ids = serializer.validated_data.get("tagged_user_ids", [])
        post = Post.objects.filter(id=post_id).first()
        if not post:
            response_payload = {"detail": "Post not found."}
            if idempotency_key:
                save_idempotent_response(
                    user_id=request.user.id,
                    endpoint=f"posts.react:{post_id}",
                    key=idempotency_key,
                    request_hash=request_hash,
                    status_code=status.HTTP_404_NOT_FOUND,
                    response_body=response_payload,
                )
            ai_log(status.HTTP_404_NOT_FOUND, response_payload)
            return Response(response_payload, status=status.HTTP_404_NOT_FOUND)
        post_sentiment_label, post_sentiment_score = ensure_post_sentiment(post)
        post_is_toxic = is_post_toxic(post)

        singleton_actions = {
            PostInteraction.ActionType.LIKE,
            PostInteraction.ActionType.BOOKMARK,
            PostInteraction.ActionType.REPOST,
            PostInteraction.ActionType.REPORT,
        }
        if action in singleton_actions:
            interaction, created = PostInteraction.objects.get_or_create(
                post=post,
                user=request.user,
                action_type=action,
                defaults={"content": content, "ip_address": request_ip_address},
            )
            if not created:
                if hasattr(request.user, "profile") and action != PostInteraction.ActionType.REPORT:
                    record_profile_action_score(
                        profile=request.user.profile,
                        action_type=action,
                        sentiment_label=post_sentiment_label,
                        sentiment_score=post_sentiment_score,
                        post=post,
                        interaction=interaction,
                        metadata={"source": "post_react", "toggled_off": True},
                        toggled_off=True,
                        target_sentiment_score=post_sentiment_score,
                    )
                interaction.delete()
                bump_user_feed_cache_version(request.user.id)
                response_payload = {"toggled": "off", "action": action}
                if idempotency_key:
                    save_idempotent_response(
                        user_id=request.user.id,
                        endpoint=f"posts.react:{post_id}",
                        key=idempotency_key,
                        request_hash=request_hash,
                        status_code=status.HTTP_200_OK,
                        response_body=response_payload,
                    )
                ai_log(status.HTTP_200_OK, response_payload)
                return Response(response_payload)
            if action == PostInteraction.ActionType.REPORT:
                ModerationFlag.objects.create(
                    profile_id=getattr(request.user.profile, "id", None)
                    if hasattr(request.user, "profile")
                    else None,
                    content_type="post",
                    content_id=post.id,
                    category="user_report",
                    reason="User submitted report action",
                    payload={"reported_by_user_id": request.user.id},
                    policy_region=getattr(request.user.profile, "location", "global")
                    if hasattr(request.user, "profile")
                    else "global",
                    policy_version="user-action",
                )
            if hasattr(request.user, "profile"):
                is_false_report = action == PostInteraction.ActionType.REPORT and (
                    post_sentiment_label != "negative" and not post_is_toxic
                )
                record_profile_action_score(
                    profile=request.user.profile,
                    action_type=action,
                    sentiment_label=post_sentiment_label,
                    sentiment_score=post_sentiment_score,
                    post=post,
                    interaction=interaction,
                    metadata={"source": "post_react", "is_false_report": is_false_report},
                    is_false_report=is_false_report,
                    is_toxic_report=action == PostInteraction.ActionType.REPORT and post_is_toxic,
                    target_sentiment_score=post_sentiment_score,
                )
            if action in {
                PostInteraction.ActionType.LIKE,
                PostInteraction.ActionType.REPOST,
            }:
                action_verb = "liked" if action == PostInteraction.ActionType.LIKE else "reposted"
                create_notification(
                    recipient_user_id=post.author_id,
                    actor_user_id=request.user.id,
                    event_type=f"post.{action}",
                    title=f"New {action}",
                    message=f"@{request.user.username} {action_verb} your post.",
                    payload={"post_id": int(post.id), "interaction_id": int(interaction.id)},
                )
            bump_user_feed_cache_version(request.user.id)
            response_payload = {"toggled": "on", "action": action}
            if idempotency_key:
                save_idempotent_response(
                    user_id=request.user.id,
                    endpoint=f"posts.react:{post_id}",
                    key=idempotency_key,
                    request_hash=request_hash,
                    status_code=status.HTTP_201_CREATED,
                    response_body=response_payload,
                )
            ai_log(status.HTTP_201_CREATED, response_payload)
            return Response(response_payload, status=status.HTTP_201_CREATED)

        interaction = PostInteraction.objects.create(
            post=post,
            user=request.user,
            action_type=action,
            content=content,
            link_url=link_url,
            attachments=attachments,
            tagged_user_ids=tagged_user_ids,
            ip_address=request_ip_address,
        )
        if action in {PostInteraction.ActionType.REPLY, PostInteraction.ActionType.QUOTE} and (content or link_url):
            region_code = request.user.profile.location if hasattr(request.user, "profile") else "global"
            blocked, categories = is_content_blocked(
                text=f"{content} {link_url}",
                region_code=region_code,
                content_type="post_interaction",
                content_id=interaction.id,
                profile_id=getattr(request.user.profile, "id", None)
                if hasattr(request.user, "profile")
                else None,
            )
            if blocked:
                interaction.delete()
                response_payload = {
                    "detail": "Interaction content violates policy.",
                    "blocked_categories": categories,
                }
                if idempotency_key:
                    save_idempotent_response(
                        user_id=request.user.id,
                        endpoint=f"posts.react:{post_id}",
                        key=idempotency_key,
                        request_hash=request_hash,
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        response_body=response_payload,
                    )
                ai_log(status.HTTP_422_UNPROCESSABLE_ENTITY, response_payload)
                return Response(response_payload, status=status.HTTP_422_UNPROCESSABLE_ENTITY)
            if action == PostInteraction.ActionType.REPLY:
                reply_post = Post.objects.create(
                    author=request.user,
                    parent_post=post,
                    content=content,
                    link_url=link_url,
                    visibility=post.visibility,
                    interest_tags=post.interest_tags if isinstance(post.interest_tags, list) else [],
                    tagged_user_ids=tagged_user_ids,
                    ip_address=request_ip_address,
                )
                for attachment in attachments:
                    MediaAttachment.objects.create(
                        post=reply_post,
                        media_type=str(attachment.get("media_type", "")).strip().lower(),
                        media_url=str(attachment.get("media_url", "")).strip(),
                    )
                reply_sentiment_label, reply_sentiment_score = score_post_sentiment(reply_post)
                if hasattr(request.user, "profile"):
                    record_profile_action_score(
                        profile=request.user.profile,
                        action_type=PostInteraction.ActionType.REPLY,
                        sentiment_label=reply_sentiment_label,
                        sentiment_score=reply_sentiment_score,
                        post=reply_post,
                        interaction=interaction,
                        metadata={"source": "post_react_reply"},
                        target_sentiment_score=post_sentiment_score,
                    )
                create_notification(
                    recipient_user_id=post.author_id,
                    actor_user_id=request.user.id,
                    event_type="post.reply",
                    title="New reply",
                    message=f"@{request.user.username} replied to your post.",
                    payload={"post_id": int(post.id), "reply_post_id": int(reply_post.id), "interaction_id": int(interaction.id)},
                )
                mention_targets = set(tagged_user_ids or [])
                mention_targets.discard(post.author_id)
                emit_post_mentions(
                    tagged_user_ids=list(mention_targets),
                    actor_user=request.user,
                    post_id=reply_post.id,
                    interaction_id=interaction.id,
                )
            elif action == PostInteraction.ActionType.QUOTE:
                if hasattr(request.user, "profile"):
                    quote_sentiment = score_sentiment_text(content)
                    record_profile_action_score(
                        profile=request.user.profile,
                        action_type=PostInteraction.ActionType.QUOTE,
                        sentiment_label=quote_sentiment.label,
                        sentiment_score=quote_sentiment.score,
                        post=post,
                        interaction=interaction,
                        metadata={"source": "post_react_quote"},
                        target_sentiment_score=post_sentiment_score,
                    )
                create_notification(
                    recipient_user_id=post.author_id,
                    actor_user_id=request.user.id,
                    event_type="post.quote",
                    title="New quote",
                    message=f"@{request.user.username} quoted your post.",
                    payload={"post_id": int(post.id), "interaction_id": int(interaction.id)},
                )
                mention_targets = set(tagged_user_ids or [])
                mention_targets.discard(post.author_id)
                emit_post_mentions(
                    tagged_user_ids=list(mention_targets),
                    actor_user=request.user,
                    post_id=post.id,
                    interaction_id=interaction.id,
                )
        elif action == PostInteraction.ActionType.QUOTE:
            if hasattr(request.user, "profile"):
                record_profile_action_score(
                    profile=request.user.profile,
                    action_type=PostInteraction.ActionType.QUOTE,
                    sentiment_label=post_sentiment_label,
                    sentiment_score=post_sentiment_score,
                    post=post,
                    interaction=interaction,
                    metadata={"source": "post_react_quote_target"},
                    target_sentiment_score=post_sentiment_score,
                )
            create_notification(
                recipient_user_id=post.author_id,
                actor_user_id=request.user.id,
                event_type="post.quote",
                title="New quote",
                message=f"@{request.user.username} quoted your post.",
                payload={"post_id": int(post.id), "interaction_id": int(interaction.id)},
            )
            mention_targets = set(tagged_user_ids or [])
            mention_targets.discard(post.author_id)
            emit_post_mentions(
                tagged_user_ids=list(mention_targets),
                actor_user=request.user,
                post_id=post.id,
                interaction_id=interaction.id,
            )
        bump_user_feed_cache_version(request.user.id)
        response_payload = {"id": interaction.id, "action": action}
        if idempotency_key:
            save_idempotent_response(
                user_id=request.user.id,
                endpoint=f"posts.react:{post_id}",
                key=idempotency_key,
                request_hash=request_hash,
                status_code=status.HTTP_201_CREATED,
                response_body=response_payload,
            )
        ai_log(status.HTTP_201_CREATED, response_payload)
        return Response(response_payload, status=status.HTTP_201_CREATED)


class PostDetailView(APIView):
    def get(self, request, post_id: int):
        post = build_post_queryset_for_user(request.user).filter(id=post_id).first()
        if not post:
            return Response({"detail": "Post not found."}, status=status.HTTP_404_NOT_FOUND)
        reply_posts = build_post_queryset_for_user(request.user).filter(parent_post_id=post.id).order_by("created_at")[:100]
        replies = [serialize_post_with_author(reply_post, request) for reply_post in reply_posts]
        return Response({"post": serialize_post_with_author(post, request), "replies": replies})


class UserPostListView(APIView):
    def get(self, request, user_id: int):
        posts = (
            build_post_queryset_for_user(request.user)
            .filter(author_id=user_id, parent_post__isnull=True)
            .order_by("-is_pinned", "-created_at")[:50]
        )
        return Response([serialize_post_with_author(post, request) for post in posts])


class BookmarkedPostListView(APIView):
    def get(self, request):
        posts = (
            build_post_queryset_for_user(request.user)
            .filter(interactions__user=request.user, interactions__action_type=PostInteraction.ActionType.BOOKMARK)
            .filter(parent_post__isnull=True)
            .order_by("-created_at")
            .distinct()[:50]
        )
        return Response([serialize_post_with_author(post, request) for post in posts])


class PinnedPostListView(APIView):
    def get(self, request):
        posts = (
            build_post_queryset_for_user(request.user)
            .filter(author=request.user, is_pinned=True, parent_post__isnull=True)
            .order_by("-updated_at", "-created_at")[:50]
        )
        return Response([serialize_post_with_author(post, request) for post in posts])


class PostPinView(APIView):
    def post(self, request, post_id: int):
        post = Post.objects.filter(id=post_id, author=request.user).first()
        if not post:
            return Response({"detail": "Post not found."}, status=status.HTTP_404_NOT_FOUND)
        if post.parent_post_id:
            return Response({"detail": "Replies cannot be pinned."}, status=status.HTTP_400_BAD_REQUEST)
        post.is_pinned = not bool(post.is_pinned)
        post.save(update_fields=["is_pinned", "updated_at"])
        bump_user_feed_cache_version(request.user.id)
        return Response({"is_pinned": bool(post.is_pinned)})


class PostSyncMetricsView(APIView):
    def get(self, request):
        now = timezone.now()
        records = IdempotencyRecord.objects.filter(user=request.user, expires_at__gt=now)
        sync_events = SyncReplayEvent.objects.filter(user=request.user)
        aggregates = records.aggregate(
            replay_total=Sum("replay_count"),
            conflict_total=Sum("conflict_count"),
        )
        success_events = sync_events.filter(outcome=SyncReplayEvent.Outcome.SUCCESS).count()
        dropped_events = sync_events.filter(outcome=SyncReplayEvent.Outcome.DROPPED).count()
        retry_events = sync_events.filter(outcome=SyncReplayEvent.Outcome.RETRY).count()
        payload = {
            "active_idempotency_records": records.count(),
            "replay_total": int(aggregates["replay_total"] or 0),
            "conflict_total": int(aggregates["conflict_total"] or 0),
            "sync_events": {
                "success": success_events,
                "dropped": dropped_events,
                "retry": retry_events,
            },
            "latest_record_at": records.order_by("-created_at").values_list("created_at", flat=True).first(),
        }
        return Response(payload)


class PostSyncEventIngestView(APIView):
    def post(self, request):
        serializer = SyncReplayEventIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        SyncReplayEvent.objects.create(
            user=request.user,
            source=serializer.validated_data["source"],
            kind=serializer.validated_data["kind"],
            endpoint=serializer.validated_data["endpoint"],
            outcome=serializer.validated_data["outcome"],
            status_code=serializer.validated_data.get("status_code"),
            idempotency_key=serializer.validated_data.get("idempotency_key", ""),
            queued_at=serializer.validated_data.get("queued_at"),
            detail=serializer.validated_data.get("detail", ""),
        )
        return Response({"ingested": True}, status=status.HTTP_201_CREATED)


def _serialize_posts(serialized_posts: list[dict], queryset) -> list[dict]:
    mapped = {post.id: post for post in queryset}
    result: list[dict] = []
    for serialized in serialized_posts:
        post = mapped.get(serialized["id"])
        if post:
            ensure_post_sentiment(post)
            serialized["interaction_counts"] = {
                "like": post.like_count,
                "reply": post.reply_count,
                "repost": post.repost_count,
                "quote": post.quote_count,
            }
            serialized["has_liked"] = bool(post.has_liked)
            serialized["has_bookmarked"] = bool(post.has_bookmarked)
            serialized["is_pinned"] = bool(post.is_pinned)
            serialized["author_is_connected"] = bool(getattr(post, "author_is_connected", False))
            serialized["sentiment_label"] = str(getattr(post, "sentiment_label", "neutral") or "neutral")
            serialized["sentiment_score"] = float(getattr(post, "sentiment_score", 0.0) or 0.0)
        result.append(serialized)
    return result
