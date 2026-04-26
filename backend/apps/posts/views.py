from datetime import timedelta

from django.conf import settings
from django.db.models import Count, Exists, OuterRef, Q, Sum
from django.utils import timezone
from rest_framework import status
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_accounts.services import log_ai_action
from apps.moderation.models import ModerationFlag
from apps.moderation.services import is_content_blocked
from apps.posts.idempotency import (
    hash_request_payload,
    load_idempotent_response,
    save_idempotent_response,
)
from apps.posts.models import IdempotencyRecord, Post, PostInteraction, SyncReplayEvent
from apps.posts.serializers import PostSerializer, ReactSerializer
from apps.posts.sync_serializers import SyncReplayEventIngestSerializer


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
        queryset = (
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
                        user=request.user,
                        action_type=PostInteraction.ActionType.LIKE,
                    )
                ),
            )
            .all()[:50]
        )
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
        serializer.save(author=request.user)
        response_payload = dict(serializer.data)
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
        action = serializer.validated_data["action"]
        content = serializer.validated_data.get("content", "")
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
                defaults={"content": content},
            )
            if not created:
                interaction.delete()
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
        )
        if action in {PostInteraction.ActionType.REPLY, PostInteraction.ActionType.QUOTE} and content:
            region_code = request.user.profile.location if hasattr(request.user, "profile") else "global"
            blocked, categories = is_content_blocked(
                text=content,
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
            serialized["interaction_counts"] = {
                "like": post.like_count,
                "reply": post.reply_count,
                "repost": post.repost_count,
                "quote": post.quote_count,
            }
            serialized["has_liked"] = bool(post.has_liked)
        result.append(serialized)
    return result
