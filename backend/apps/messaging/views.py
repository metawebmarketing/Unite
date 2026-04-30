import base64
import json
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.accounts.models import Profile
from apps.connections.models import Connection
from apps.moderation.services import is_content_blocked
from apps.messaging.models import DMMessage, DMThread, DMThreadParticipant
from apps.messaging.serializers import DMMessageCreateSerializer, DMThreadCreateSerializer
from apps.notifications.services import create_notification, push_realtime_event
from apps.posts.idempotency import (
    hash_request_payload,
    load_idempotent_response,
    save_idempotent_response,
)
from apps.posts.services import build_link_preview

User = get_user_model()


def get_request_ip_address(request) -> str | None:
    forwarded_for = str(request.META.get("HTTP_X_FORWARDED_FOR", "")).strip()
    if forwarded_for:
        first_ip = forwarded_for.split(",")[0].strip()
        if first_ip:
            return first_ip
    remote_addr = str(request.META.get("REMOTE_ADDR", "")).strip()
    return remote_addr or None


def encode_cursor(timestamp: datetime, item_id: int) -> str:
    payload = {"timestamp": timestamp.isoformat(), "item_id": item_id}
    raw = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> dict:
    raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
    return json.loads(raw.decode("utf-8"))


def canonical_thread_users(user_a_id: int, user_b_id: int) -> tuple[int, int]:
    if user_a_id < user_b_id:
        return user_a_id, user_b_id
    return user_b_id, user_a_id


@transaction.atomic
def ensure_dm_thread(user_one_id: int, user_two_id: int) -> tuple[DMThread, bool]:
    left_id, right_id = canonical_thread_users(user_one_id, user_two_id)
    thread, created = DMThread.objects.get_or_create(user_a_id=left_id, user_b_id=right_id)
    DMThreadParticipant.objects.get_or_create(thread=thread, user_id=left_id)
    DMThreadParticipant.objects.get_or_create(thread=thread, user_id=right_id)
    return thread, created


def is_thread_participant(thread: DMThread, user_id: int) -> bool:
    return thread.user_a_id == user_id or thread.user_b_id == user_id


def thread_other_user_id(thread: DMThread, user_id: int) -> int:
    return thread.other_user_id_for(user_id)


def serialize_thread_item(
    *,
    thread: DMThread,
    request,
    other_profile_map: dict[int, Profile],
    participant_map: dict[int, DMThreadParticipant],
) -> dict:
    user_id = request.user.id
    other_user_id = thread_other_user_id(thread, user_id)
    other_profile = other_profile_map.get(other_user_id)
    latest_message = thread.messages.order_by("-created_at", "-id").first()
    self_participant = participant_map.get(thread.id)
    last_read_id = int(self_participant.last_read_message_id or 0) if self_participant else 0
    unread_count = (
        thread.messages.filter(id__gt=last_read_id).exclude(sender_id=user_id).count()
        if last_read_id
        else thread.messages.exclude(sender_id=user_id).count()
    )
    profile_image_url = ""
    if other_profile and getattr(other_profile, "profile_image", None):
        profile_image_url = request.build_absolute_uri(other_profile.profile_image.url)
    display_name = ""
    username = ""
    if other_profile:
        display_name = (other_profile.display_name or other_profile.user.username).strip()
        username = str(other_profile.user.username).strip()
    else:
        fallback_user = User.objects.filter(id=other_user_id).only("username").first()
        username = str(getattr(fallback_user, "username", "")).strip()
        display_name = username
    return {
        "thread_id": thread.id,
        "other_user_id": other_user_id,
        "other_username": username,
        "other_display_name": display_name,
        "other_profile_image_url": profile_image_url,
        "latest_message_preview": str(getattr(latest_message, "content", "") or "")[:160],
        "latest_message_at": (
            getattr(latest_message, "created_at", None) or thread.last_message_at or thread.created_at
        ).isoformat(),
        "updated_at": thread.updated_at.isoformat(),
        "unread_count": unread_count,
    }


def serialize_message_item(
    *,
    message: DMMessage,
    request_user_id: int,
    other_participant_last_read_message_id: int | None,
) -> dict:
    sender_status = DMMessage.DeliveryStatus.SENT
    if message.sender_id == request_user_id:
        if other_participant_last_read_message_id and other_participant_last_read_message_id >= message.id:
            sender_status = DMMessage.DeliveryStatus.READ
    else:
        sender_status = DMMessage.DeliveryStatus.READ
    existing_preview = message.link_preview if isinstance(message.link_preview, dict) else {}
    preview_url = str(existing_preview.get("url") or "").strip()
    resolved_preview = (
        existing_preview
        if str(existing_preview.get("image_url") or "").strip()
        else build_link_preview(preview_url) if preview_url else existing_preview
    )
    return {
        "id": message.id,
        "thread_id": message.thread_id,
        "sender_id": message.sender_id,
        "content": message.content,
        "attachments": message.attachments if isinstance(message.attachments, list) else [],
        "link_preview": resolved_preview,
        "created_at": message.created_at.isoformat(),
        "status": sender_status,
    }


def thread_unread_count_for_user(*, thread: DMThread, user_id: int) -> int:
    participant = DMThreadParticipant.objects.filter(thread=thread, user_id=user_id).first()
    last_read_id = int(participant.last_read_message_id or 0) if participant else 0
    queryset = thread.messages.exclude(sender_id=user_id)
    if last_read_id > 0:
        queryset = queryset.filter(id__gt=last_read_id)
    return queryset.count()


class DMThreadListCreateView(APIView):
    throttle_classes = [ScopedRateThrottle]

    def get_throttles(self):
        self.throttle_scope = "messages_list"
        return super().get_throttles()

    def get(self, request):
        page_size = max(1, min(int(request.query_params.get("page_size", 20)), 50))
        search = str(request.query_params.get("search", "")).strip().lower()
        from_profile = str(request.query_params.get("from_profile", "")).strip().lower()
        after_date = str(request.query_params.get("after_date", "")).strip()
        before_date = str(request.query_params.get("before_date", "")).strip()
        cursor = str(request.query_params.get("cursor", "")).strip()

        queryset = DMThread.objects.filter(Q(user_a=request.user) | Q(user_b=request.user)).order_by("-last_message_at", "-id")

        if after_date:
            try:
                queryset = queryset.filter(last_message_at__date__gte=datetime.fromisoformat(after_date).date())
            except ValueError:
                return Response({"detail": "Invalid after_date filter."}, status=status.HTTP_400_BAD_REQUEST)
        if before_date:
            try:
                queryset = queryset.filter(last_message_at__date__lte=datetime.fromisoformat(before_date).date())
            except ValueError:
                return Response({"detail": "Invalid before_date filter."}, status=status.HTTP_400_BAD_REQUEST)
        if cursor:
            try:
                payload = decode_cursor(cursor)
                cursor_timestamp = datetime.fromisoformat(payload["timestamp"])
                cursor_id = int(payload["item_id"])
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                return Response({"detail": "Invalid cursor."}, status=status.HTTP_400_BAD_REQUEST)
            queryset = queryset.filter(
                Q(last_message_at__lt=cursor_timestamp)
                | (Q(last_message_at=cursor_timestamp) & Q(id__lt=cursor_id))
            )

        selected_threads: list[DMThread] = []
        matched = 0
        limit = page_size + 1
        for thread in queryset[: max(limit * 5, 150)]:
            other_user_id = thread_other_user_id(thread, request.user.id)
            other_profile = Profile.objects.select_related("user").filter(user_id=other_user_id).first()
            display_name = (getattr(other_profile, "display_name", "") or getattr(getattr(other_profile, "user", None), "username", "")).strip()
            username = str(getattr(getattr(other_profile, "user", None), "username", "")).strip()
            if search and search not in display_name.lower() and search not in username.lower():
                continue
            if from_profile and from_profile not in display_name.lower() and from_profile not in username.lower():
                continue
            selected_threads.append(thread)
            matched += 1
            if matched >= limit:
                break

        has_more = len(selected_threads) > page_size
        page_threads = selected_threads[:page_size]
        other_user_ids = [thread_other_user_id(thread, request.user.id) for thread in page_threads]
        profiles = Profile.objects.select_related("user").filter(user_id__in=other_user_ids)
        other_profile_map = {profile.user_id: profile for profile in profiles}
        participants = DMThreadParticipant.objects.filter(thread__in=page_threads, user=request.user)
        participant_map = {participant.thread_id: participant for participant in participants}
        items = [
            serialize_thread_item(
                thread=thread,
                request=request,
                other_profile_map=other_profile_map,
                participant_map=participant_map,
            )
            for thread in page_threads
        ]
        next_cursor = None
        if has_more and page_threads:
            anchor = page_threads[-1]
            anchor_timestamp = anchor.last_message_at or anchor.created_at
            next_cursor = encode_cursor(anchor_timestamp, anchor.id)
        return Response({"items": items, "next_cursor": next_cursor, "has_more": has_more})

    def post(self, request):
        serializer = DMThreadCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        recipient_id = serializer.validated_data["recipient_id"]
        thread, created = ensure_dm_thread(request.user.id, recipient_id)
        status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response({"thread_id": thread.id, "created": created}, status=status_code)


class DMUserSuggestionView(APIView):
    throttle_classes = [ScopedRateThrottle]

    def get_throttles(self):
        self.throttle_scope = "messages_list"
        return super().get_throttles()

    def get(self, request):
        query = str(request.query_params.get("query", "")).strip().lower()
        limit = max(1, min(int(request.query_params.get("limit", 50)), 50))
        profile_queryset = Profile.objects.select_related("user").exclude(user=request.user)
        if query:
            profile_queryset = profile_queryset.filter(
                Q(user__username__icontains=query) | Q(display_name__icontains=query)
            )
        profiles = profile_queryset[:200]
        accepted_pairs = Connection.objects.filter(
            status=Connection.Status.ACCEPTED
        ).filter(
            Q(requester=request.user) | Q(recipient=request.user)
        ).values_list("requester_id", "recipient_id")
        connected_user_ids: set[int] = set()
        for requester_id, recipient_id in accepted_pairs:
            if requester_id != request.user.id:
                connected_user_ids.add(int(requester_id))
            if recipient_id != request.user.id:
                connected_user_ids.add(int(recipient_id))

        items = []
        for profile in profiles:
            username = str(profile.user.username).strip()
            display_name = (profile.display_name or username).strip()
            if query and query not in username.lower() and query not in display_name.lower():
                continue
            profile_image_url = request.build_absolute_uri(profile.profile_image.url) if profile.profile_image else ""
            rank_score = float(getattr(profile, "rank_overall_score", 0.0) or 0.0)
            is_connected = profile.user_id in connected_user_ids
            items.append(
                {
                    "user_id": profile.user_id,
                    "username": username,
                    "display_name": display_name,
                    "profile_image_url": profile_image_url,
                    "is_connected": is_connected,
                    "rank_overall_score": rank_score,
                }
            )
        items.sort(
            key=lambda item: (
                0 if item["is_connected"] else 1,
                -float(item["rank_overall_score"]),
                str(item["username"]).lower(),
            )
        )
        return Response({"items": items[:limit]})


class DMThreadUserSuggestionView(APIView):
    throttle_classes = [ScopedRateThrottle]

    def get_throttles(self):
        self.throttle_scope = "messages_list"
        return super().get_throttles()

    def get(self, request):
        query = str(request.query_params.get("query", "")).strip().lower()
        if len(query) < 3:
            return Response({"items": []})
        limit = max(1, min(int(request.query_params.get("limit", 50)), 50))
        thread_queryset = DMThread.objects.filter(
            Q(user_a=request.user) | Q(user_b=request.user)
        ).order_by("-last_message_at", "-id")
        thread_other_user_ids: list[int] = []
        seen_user_ids: set[int] = set()
        for thread in thread_queryset[:300]:
            other_user_id = thread_other_user_id(thread, request.user.id)
            if other_user_id in seen_user_ids:
                continue
            seen_user_ids.add(other_user_id)
            thread_other_user_ids.append(other_user_id)
            if len(thread_other_user_ids) >= 200:
                break

        if not thread_other_user_ids:
            return Response({"items": []})

        profiles = (
            Profile.objects.select_related("user")
            .filter(user_id__in=thread_other_user_ids)
            .filter(
                Q(user__username__icontains=query) | Q(display_name__icontains=query)
            )
        )
        profile_by_user_id = {profile.user_id: profile for profile in profiles}
        items = []
        for user_id in thread_other_user_ids:
            profile = profile_by_user_id.get(user_id)
            if not profile:
                continue
            username = str(profile.user.username).strip()
            display_name = (profile.display_name or username).strip()
            if query not in username.lower() and query not in display_name.lower():
                continue
            profile_image_url = request.build_absolute_uri(profile.profile_image.url) if profile.profile_image else ""
            items.append(
                {
                    "user_id": profile.user_id,
                    "username": username,
                    "display_name": display_name,
                    "profile_image_url": profile_image_url,
                    "is_connected": False,
                    "rank_overall_score": 0.0,
                }
            )
            if len(items) >= limit:
                break
        return Response({"items": items})


class DMThreadMessageListCreateView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "messages_send"
    ai_throttle_scope = "messages_send_ai"

    def resolve_throttle_scope(self) -> str:
        if self.request.method == "GET":
            return "messages_list"
        return self.ai_throttle_scope if hasattr(self.request.user, "ai_account") else self.throttle_scope

    def get_throttles(self):
        self.throttle_scope = self.resolve_throttle_scope()
        return super().get_throttles()

    def get(self, request, thread_id: int):
        thread = DMThread.objects.filter(id=thread_id).first()
        if not thread:
            return Response({"detail": "Thread not found."}, status=status.HTTP_404_NOT_FOUND)
        if not is_thread_participant(thread, request.user.id):
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        page_size = max(1, min(int(request.query_params.get("page_size", 30)), 80))
        cursor = str(request.query_params.get("cursor", "")).strip()
        queryset = thread.messages.select_related("sender").order_by("-created_at", "-id")
        if cursor:
            try:
                payload = decode_cursor(cursor)
                cursor_timestamp = datetime.fromisoformat(payload["timestamp"])
                cursor_message_id = int(payload["item_id"])
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                return Response({"detail": "Invalid cursor."}, status=status.HTTP_400_BAD_REQUEST)
            queryset = queryset.filter(
                Q(created_at__lt=cursor_timestamp)
                | (Q(created_at=cursor_timestamp) & Q(id__lt=cursor_message_id))
            )

        page_messages = list(queryset[: page_size + 1])
        has_more = len(page_messages) > page_size
        messages = page_messages[:page_size]

        latest_message = thread.messages.order_by("-created_at", "-id").first()
        if latest_message and latest_message.sender_id != request.user.id:
            DMThreadParticipant.objects.update_or_create(
                thread=thread,
                user=request.user,
                defaults={
                    "last_read_at": timezone.now(),
                    "last_read_message": latest_message,
                },
            )
            other_user_id = thread_other_user_id(thread, request.user.id)
            push_realtime_event(
                user_id=other_user_id,
                event_type="dm.thread.read",
                payload={
                    "thread_id": int(thread.id),
                    "read_by_user_id": int(request.user.id),
                    "last_read_message_id": int(latest_message.id),
                },
            )

        other_user_id = thread_other_user_id(thread, request.user.id)
        other_participant = DMThreadParticipant.objects.filter(thread=thread, user_id=other_user_id).first()
        other_last_read_message_id = (
            int(other_participant.last_read_message_id)
            if other_participant and other_participant.last_read_message_id
            else None
        )

        items = [
            serialize_message_item(
                message=message,
                request_user_id=request.user.id,
                other_participant_last_read_message_id=other_last_read_message_id,
            )
            for message in messages
        ]
        next_cursor = None
        if has_more and messages:
            anchor = messages[-1]
            next_cursor = encode_cursor(anchor.created_at, anchor.id)
        return Response(
            {
                "items": items,
                "next_cursor": next_cursor,
                "has_more": has_more,
                "thread_id": thread.id,
            }
        )

    def post(self, request, thread_id: int):
        thread = DMThread.objects.filter(id=thread_id).first()
        if not thread:
            return Response({"detail": "Thread not found."}, status=status.HTTP_404_NOT_FOUND)
        if not is_thread_participant(thread, request.user.id):
            return Response({"detail": "Forbidden."}, status=status.HTTP_403_FORBIDDEN)

        idempotency_key = request.headers.get("Idempotency-Key")
        request_payload = request.data if isinstance(request.data, dict) else {}
        request_hash = hash_request_payload(request_payload)
        if idempotency_key:
            payload, status_code, found = load_idempotent_response(
                user_id=request.user.id,
                endpoint=f"messages.send:{thread_id}",
                key=idempotency_key,
                request_hash=request_hash,
            )
            if found:
                return Response(payload, status=status_code)

        serializer = DMMessageCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        content = serializer.validated_data.get("content", "")
        link_url = serializer.validated_data.get("link_url", "")
        request_profile = Profile.objects.filter(user=request.user).only("id", "location").first()
        region_code = str(getattr(request_profile, "location", "") or "global")
        blocked, categories = is_content_blocked(
            text=f"{content} {link_url}",
            region_code=region_code,
            content_type="direct_message",
            profile_id=getattr(request_profile, "id", None),
        )
        if blocked:
            response_payload = {
                "detail": "Message violates policy.",
                "blocked_categories": categories,
            }
            if idempotency_key:
                save_idempotent_response(
                    user_id=request.user.id,
                    endpoint=f"messages.send:{thread_id}",
                    key=idempotency_key,
                    request_hash=request_hash,
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    response_body=response_payload,
                )
            return Response(response_payload, status=status.HTTP_422_UNPROCESSABLE_ENTITY)

        link_preview = build_link_preview(link_url) if link_url else {}
        message = DMMessage.objects.create(
            thread=thread,
            sender=request.user,
            content=content,
            attachments=serializer.validated_data.get("attachments", []),
            link_preview=link_preview,
            ip_address=get_request_ip_address(request),
        )
        thread.last_message_at = message.created_at
        thread.save(update_fields=["last_message_at", "updated_at"])
        DMThreadParticipant.objects.update_or_create(
            thread=thread,
            user=request.user,
            defaults={
                "last_read_at": message.created_at,
                "last_read_message": message,
            },
        )
        response_payload = serialize_message_item(
            message=message,
            request_user_id=request.user.id,
            other_participant_last_read_message_id=None,
        )
        recipient_user_id = thread_other_user_id(thread, request.user.id)
        create_notification(
            recipient_user_id=recipient_user_id,
            actor_user_id=request.user.id,
            event_type="dm.message",
            title="New private conversation",
            message=f"@{request.user.username} started a private conversation with you.",
            payload={
                "thread_id": int(thread.id),
                "message_id": int(message.id),
                "preview": str(content or "")[:120],
            },
        )
        push_realtime_event(
            user_id=recipient_user_id,
            event_type="dm.message.created",
            payload={
                "thread_id": int(thread.id),
                "message": response_payload,
                "thread_unread_count": thread_unread_count_for_user(thread=thread, user_id=recipient_user_id),
            },
        )
        push_realtime_event(
            user_id=request.user.id,
            event_type="dm.message.sent",
            payload={"thread_id": int(thread.id), "message": response_payload},
        )
        if idempotency_key:
            save_idempotent_response(
                user_id=request.user.id,
                endpoint=f"messages.send:{thread_id}",
                key=idempotency_key,
                request_hash=request_hash,
                status_code=status.HTTP_201_CREATED,
                response_body=response_payload,
            )
        return Response(response_payload, status=status.HTTP_201_CREATED)
