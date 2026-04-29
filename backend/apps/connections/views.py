import base64
import json
from datetime import datetime

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Profile
from apps.connections.models import Connection
from apps.connections.serializers import ConnectionSerializer
from apps.feed.cache_utils import bump_user_feed_cache_version
from apps.notifications.services import create_notification

User = get_user_model()


def encode_cursor(updated_at: datetime, connection_id: int) -> str:
    payload = {"updated_at": updated_at.isoformat(), "connection_id": connection_id}
    raw = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> dict:
    raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
    return json.loads(raw.decode("utf-8"))


def get_blocked_user_ids(user_id: int) -> set[int]:
    blocked_pairs = Connection.objects.filter(status=Connection.Status.BLOCKED).filter(
        Q(requester_id=user_id) | Q(recipient_id=user_id)
    ).values_list("requester_id", "recipient_id")
    blocked_ids: set[int] = set()
    for requester_id, recipient_id in blocked_pairs:
        if int(requester_id) != int(user_id):
            blocked_ids.add(int(requester_id))
        if int(recipient_id) != int(user_id):
            blocked_ids.add(int(recipient_id))
    return blocked_ids


def get_connected_user_ids(user_id: int) -> set[int]:
    pairs = Connection.objects.filter(status=Connection.Status.ACCEPTED).filter(
        Q(requester_id=user_id) | Q(recipient_id=user_id)
    ).values_list("requester_id", "recipient_id")
    connected_ids: set[int] = set()
    for requester_id, recipient_id in pairs:
        if int(requester_id) != int(user_id):
            connected_ids.add(int(requester_id))
        if int(recipient_id) != int(user_id):
            connected_ids.add(int(recipient_id))
    return connected_ids


def build_relationship_status(*, viewer_id: int, target_id: int) -> dict:
    if int(viewer_id) == int(target_id):
        return {
            "relationship_status": "self",
            "is_connected": False,
            "is_blocked": False,
            "is_pending_outgoing": False,
            "is_pending_incoming": False,
        }
    is_blocked = Connection.objects.filter(status=Connection.Status.BLOCKED).filter(
        Q(requester_id=viewer_id, recipient_id=target_id) | Q(requester_id=target_id, recipient_id=viewer_id)
    ).exists()
    if is_blocked:
        return {
            "relationship_status": "blocked",
            "is_connected": False,
            "is_blocked": True,
            "is_pending_outgoing": False,
            "is_pending_incoming": False,
        }
    is_connected = Connection.objects.filter(status=Connection.Status.ACCEPTED).filter(
        Q(requester_id=viewer_id, recipient_id=target_id) | Q(requester_id=target_id, recipient_id=viewer_id)
    ).exists()
    if is_connected:
        return {
            "relationship_status": "connected",
            "is_connected": True,
            "is_blocked": False,
            "is_pending_outgoing": False,
            "is_pending_incoming": False,
        }
    is_pending_outgoing = Connection.objects.filter(
        requester_id=viewer_id,
        recipient_id=target_id,
        status=Connection.Status.PENDING,
    ).exists()
    if is_pending_outgoing:
        return {
            "relationship_status": "pending_outgoing",
            "is_connected": False,
            "is_blocked": False,
            "is_pending_outgoing": True,
            "is_pending_incoming": False,
        }
    is_pending_incoming = Connection.objects.filter(
        requester_id=target_id,
        recipient_id=viewer_id,
        status=Connection.Status.PENDING,
    ).exists()
    if is_pending_incoming:
        return {
            "relationship_status": "pending_incoming",
            "is_connected": False,
            "is_blocked": False,
            "is_pending_outgoing": False,
            "is_pending_incoming": True,
        }
    return {
        "relationship_status": "none",
        "is_connected": False,
        "is_blocked": False,
        "is_pending_outgoing": False,
        "is_pending_incoming": False,
    }


class ConnectionListView(APIView):
    def get(self, request, user_id: int | None = None):
        target_user_id = int(user_id or request.user.id)
        page_size = max(1, min(int(request.query_params.get("page_size", 20)), 50))
        search = str(request.query_params.get("search", "")).strip().lower()
        from_profile = str(request.query_params.get("from_profile", "")).strip().lower()
        after_date = str(request.query_params.get("after_date", "")).strip()
        before_date = str(request.query_params.get("before_date", "")).strip()
        cursor = str(request.query_params.get("cursor", "")).strip()

        queryset = (
            Connection.objects.select_related(
                "requester",
                "recipient",
                "requester__profile",
                "recipient__profile",
            )
            .filter(status=Connection.Status.ACCEPTED)
            .filter(Q(requester_id=target_user_id) | Q(recipient_id=target_user_id))
            .order_by("-updated_at", "-id")
        )

        if after_date:
            try:
                queryset = queryset.filter(updated_at__date__gte=datetime.fromisoformat(after_date).date())
            except ValueError:
                return Response({"detail": "Invalid after_date filter."}, status=status.HTTP_400_BAD_REQUEST)
        if before_date:
            try:
                queryset = queryset.filter(updated_at__date__lte=datetime.fromisoformat(before_date).date())
            except ValueError:
                return Response({"detail": "Invalid before_date filter."}, status=status.HTTP_400_BAD_REQUEST)
        if cursor:
            try:
                payload = decode_cursor(cursor)
                cursor_updated_at = datetime.fromisoformat(payload["updated_at"])
                cursor_connection_id = int(payload["connection_id"])
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                return Response({"detail": "Invalid cursor."}, status=status.HTTP_400_BAD_REQUEST)
            queryset = queryset.filter(
                Q(updated_at__lt=cursor_updated_at)
                | (Q(updated_at=cursor_updated_at) & Q(id__lt=cursor_connection_id))
            )

        selected_connections: list[Connection] = []
        matched = 0
        limit = page_size + 1
        for connection in queryset[: max(limit * 5, 150)]:
            other_user = connection.recipient if connection.requester_id == target_user_id else connection.requester
            profile = getattr(other_user, "profile", None)
            display_name = (getattr(profile, "display_name", "") or other_user.username).strip()
            username = str(other_user.username).strip()
            if search and search not in display_name.lower() and search not in username.lower():
                continue
            if from_profile and from_profile not in display_name.lower() and from_profile not in username.lower():
                continue
            selected_connections.append(connection)
            matched += 1
            if matched >= limit:
                break

        has_more = len(selected_connections) > page_size
        page_connections = selected_connections[:page_size]
        connection_user_ids = []
        for connection in page_connections:
            other_user = connection.recipient if connection.requester_id == target_user_id else connection.requester
            connection_user_ids.append(other_user.id)
        profiles = Profile.objects.filter(user_id__in=connection_user_ids)
        profile_interest_map = {profile.user_id: set(profile.interests or []) for profile in profiles}
        request_user_interests = set(getattr(getattr(request.user, "profile", None), "interests", []) or [])

        items = []
        for connection in page_connections:
            other_user = connection.recipient if connection.requester_id == target_user_id else connection.requester
            profile = getattr(other_user, "profile", None)
            display_name = (getattr(profile, "display_name", "") or other_user.username).strip()
            profile_image_url = ""
            if profile and getattr(profile, "profile_image", None):
                profile_image_url = request.build_absolute_uri(profile.profile_image.url)
            shared_interest_count = len(request_user_interests.intersection(profile_interest_map.get(other_user.id, set())))
            items.append(
                {
                    "connection_id": connection.id,
                    "user_id": other_user.id,
                    "username": other_user.username,
                    "display_name": display_name,
                    "profile_image_url": profile_image_url,
                    "shared_interest_count": shared_interest_count,
                    "updated_at": connection.updated_at.isoformat(),
                }
            )

        next_cursor = None
        if has_more and page_connections:
            anchor = page_connections[-1]
            next_cursor = encode_cursor(anchor.updated_at, anchor.id)

        return Response(
            {
                "items": items,
                "next_cursor": next_cursor,
                "has_more": has_more,
            }
        )


class UserSearchView(APIView):
    def get(self, request):
        page_size = max(1, min(int(request.query_params.get("page_size", 20)), 50))
        search = str(request.query_params.get("search", "")).strip()
        from_profile = str(request.query_params.get("from_profile", "")).strip()
        after_date = str(request.query_params.get("after_date", "")).strip()
        before_date = str(request.query_params.get("before_date", "")).strip()
        cursor = str(request.query_params.get("cursor", "")).strip()

        if len(search) < 3:
            return Response(
                {
                    "items": [],
                    "next_cursor": None,
                    "has_more": False,
                }
            )

        blocked_ids = get_blocked_user_ids(request.user.id)
        connected_user_ids = get_connected_user_ids(request.user.id)
        excluded_private_ids = set(
            Profile.objects.filter(is_private_profile=True)
            .exclude(user_id=request.user.id)
            .exclude(user_id__in=connected_user_ids)
            .values_list("user_id", flat=True)
        )
        excluded_ids = {request.user.id, *blocked_ids, *excluded_private_ids}
        queryset = Profile.objects.select_related("user").exclude(user_id__in=excluded_ids)
        if search:
            queryset = queryset.filter(
                Q(display_name__icontains=search) | Q(user__username__icontains=search)
            )
        if from_profile:
            queryset = queryset.filter(
                Q(display_name__icontains=from_profile) | Q(user__username__icontains=from_profile)
            )
        if after_date:
            try:
                queryset = queryset.filter(updated_at__date__gte=datetime.fromisoformat(after_date).date())
            except ValueError:
                return Response({"detail": "Invalid after_date filter."}, status=status.HTTP_400_BAD_REQUEST)
        if before_date:
            try:
                queryset = queryset.filter(updated_at__date__lte=datetime.fromisoformat(before_date).date())
            except ValueError:
                return Response({"detail": "Invalid before_date filter."}, status=status.HTTP_400_BAD_REQUEST)
        if cursor:
            try:
                payload = decode_cursor(cursor)
                cursor_updated_at = datetime.fromisoformat(payload["updated_at"])
                cursor_profile_id = int(payload["connection_id"])
            except (ValueError, TypeError, KeyError, json.JSONDecodeError):
                return Response({"detail": "Invalid cursor."}, status=status.HTTP_400_BAD_REQUEST)
            queryset = queryset.filter(
                Q(updated_at__lt=cursor_updated_at)
                | (Q(updated_at=cursor_updated_at) & Q(id__lt=cursor_profile_id))
            )

        page_profiles = list(queryset.order_by("-updated_at", "-id")[: page_size + 1])
        has_more = len(page_profiles) > page_size
        profiles = page_profiles[:page_size]

        request_user_interests = set(getattr(getattr(request.user, "profile", None), "interests", []) or [])
        candidate_user_ids = [profile.user_id for profile in profiles]
        accepted_pairs = Connection.objects.filter(
            status=Connection.Status.ACCEPTED,
        ).filter(
            Q(requester=request.user, recipient_id__in=candidate_user_ids)
            | Q(requester_id__in=candidate_user_ids, recipient=request.user)
        ).values_list("requester_id", "recipient_id")
        connected_user_ids: set[int] = set()
        for requester_id, recipient_id in accepted_pairs:
            if requester_id != request.user.id:
                connected_user_ids.add(int(requester_id))
            if recipient_id != request.user.id:
                connected_user_ids.add(int(recipient_id))

        items = []
        for profile in profiles:
            display_name = (profile.display_name or profile.user.username).strip()
            profile_image_url = request.build_absolute_uri(profile.profile_image.url) if profile.profile_image else ""
            shared_interest_count = len(request_user_interests.intersection(set(profile.interests or [])))
            items.append(
                {
                    "connection_id": profile.id,
                    "user_id": profile.user_id,
                    "username": profile.user.username,
                    "display_name": display_name,
                    "profile_image_url": profile_image_url,
                    "shared_interest_count": shared_interest_count,
                    "updated_at": profile.updated_at.isoformat(),
                    "is_connected": profile.user_id in connected_user_ids,
                }
            )

        next_cursor = None
        if has_more and profiles:
            anchor = profiles[-1]
            next_cursor = encode_cursor(anchor.updated_at, anchor.id)

        return Response(
            {
                "items": items,
                "next_cursor": next_cursor,
                "has_more": has_more,
            }
        )


class ConnectionStatusView(APIView):
    throttle_classes = []

    def get(self, request, user_id: int):
        if request.user.id == user_id:
            return Response(
                {
                    "user_id": user_id,
                    "relationship_status": "self",
                    "is_connected": False,
                    "is_blocked": False,
                    "is_pending_outgoing": False,
                    "is_pending_incoming": False,
                    "requires_approval": False,
                    "common_connections": [],
                    "common_connection_count": 0,
                }
            )
        target_user = User.objects.filter(id=user_id).first()
        if not target_user:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        relationship = build_relationship_status(viewer_id=request.user.id, target_id=user_id)

        def accepted_neighbor_ids(target_id: int) -> set[int]:
            pairs = Connection.objects.filter(
                status=Connection.Status.ACCEPTED,
            ).filter(
                Q(requester_id=target_id) | Q(recipient_id=target_id)
            ).values_list("requester_id", "recipient_id")
            ids = set()
            for requester_id, recipient_id in pairs:
                if requester_id != target_id:
                    ids.add(int(requester_id))
                if recipient_id != target_id:
                    ids.add(int(recipient_id))
            return ids

        request_neighbors = accepted_neighbor_ids(request.user.id)
        target_neighbors = accepted_neighbor_ids(user_id)
        common_ids = request_neighbors.intersection(target_neighbors)

        common_profiles = Profile.objects.select_related("user").filter(user_id__in=common_ids).order_by("display_name")[:3]
        common_connections = []
        for profile in common_profiles:
            common_connections.append(
                {
                    "user_id": profile.user_id,
                    "username": profile.user.username,
                    "display_name": profile.display_name or profile.user.username,
                    "profile_image_url": request.build_absolute_uri(profile.profile_image.url)
                    if getattr(profile, "profile_image", None)
                    else "",
                }
            )

        return Response(
            {
                "user_id": user_id,
                **relationship,
                "requires_approval": bool(
                    getattr(getattr(target_user, "profile", None), "require_connection_approval", False)
                ),
                "common_connections": common_connections,
                "common_connection_count": len(common_ids),
            }
        )


class ConnectUserView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "connect_action"
    ai_throttle_scope = "connect_action_ai"

    def resolve_throttle_scope(self, user) -> str:
        return self.ai_throttle_scope if hasattr(user, "ai_account") else "connect_action"

    def get_throttles(self):
        self.throttle_scope = self.resolve_throttle_scope(self.request.user)
        return super().get_throttles()

    @transaction.atomic
    def post(self, request, user_id: int):
        if request.user.id == user_id:
            return Response({"detail": "Cannot connect to yourself."}, status=status.HTTP_400_BAD_REQUEST)
        target_user = User.objects.filter(id=user_id).select_related("profile").first()
        if not target_user:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        if Connection.objects.filter(status=Connection.Status.BLOCKED).filter(
            Q(requester=request.user, recipient_id=user_id) | Q(requester_id=user_id, recipient=request.user)
        ).exists():
            return Response({"detail": "Connection unavailable."}, status=status.HTTP_403_FORBIDDEN)
        reverse_pending = Connection.objects.filter(
            requester_id=user_id,
            recipient=request.user,
            status=Connection.Status.PENDING,
        ).first()
        should_accept = bool(reverse_pending) or not bool(
            getattr(getattr(target_user, "profile", None), "require_connection_approval", False)
        )
        connection, _ = Connection.objects.update_or_create(
            requester=request.user,
            recipient_id=user_id,
            defaults={"status": Connection.Status.ACCEPTED if should_accept else Connection.Status.PENDING},
        )
        if reverse_pending and reverse_pending.status != Connection.Status.ACCEPTED:
            reverse_pending.status = Connection.Status.ACCEPTED
            reverse_pending.save(update_fields=["status", "updated_at"])
        if should_accept:
            reverse = Connection.objects.filter(requester_id=user_id, recipient=request.user).first()
            if reverse and reverse.status != Connection.Status.ACCEPTED:
                reverse.status = Connection.Status.ACCEPTED
                reverse.save(update_fields=["status", "updated_at"])
            bump_user_feed_cache_version(request.user.id)
            bump_user_feed_cache_version(user_id)
            create_notification(
                recipient_user_id=user_id,
                actor_user_id=request.user.id,
                event_type="connection.accepted",
                title="New connection",
                message=f"@{request.user.username} connected with you.",
                payload={"connection_id": int(connection.id), "user_id": int(request.user.id)},
            )
        else:
            create_notification(
                recipient_user_id=user_id,
                actor_user_id=request.user.id,
                event_type="connection.request",
                title="Connection request",
                message=f"@{request.user.username} requested to connect.",
                payload={"connection_id": int(connection.id), "user_id": int(request.user.id)},
            )

        serializer = ConnectionSerializer(connection)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class DisconnectUserView(APIView):
    @transaction.atomic
    def post(self, request, user_id: int):
        if request.user.id == user_id:
            return Response({"detail": "Cannot disconnect from yourself."}, status=status.HTTP_400_BAD_REQUEST)
        deleted_count, _ = Connection.objects.filter(
            Q(requester=request.user, recipient_id=user_id) | Q(requester_id=user_id, recipient=request.user)
        ).delete()
        if deleted_count:
            bump_user_feed_cache_version(request.user.id)
            bump_user_feed_cache_version(user_id)
        return Response({"disconnected": bool(deleted_count > 0)})


class PendingConnectionListView(APIView):
    def get(self, request):
        pending_connections = (
            Connection.objects.select_related("requester", "requester__profile")
            .filter(recipient=request.user, status=Connection.Status.PENDING)
            .order_by("-updated_at", "-id")
        )
        items = []
        for connection in pending_connections:
            requester = connection.requester
            profile = getattr(requester, "profile", None)
            items.append(
                {
                    "connection_id": connection.id,
                    "user_id": requester.id,
                    "username": requester.username,
                    "display_name": (getattr(profile, "display_name", "") or requester.username).strip(),
                    "profile_image_url": request.build_absolute_uri(profile.profile_image.url)
                    if profile and getattr(profile, "profile_image", None)
                    else "",
                    "updated_at": connection.updated_at.isoformat(),
                }
            )
        return Response({"items": items})


class ApproveConnectionView(APIView):
    @transaction.atomic
    def post(self, request, user_id: int):
        pending = Connection.objects.filter(
            requester_id=user_id,
            recipient=request.user,
            status=Connection.Status.PENDING,
        ).first()
        if not pending:
            return Response({"detail": "Pending request not found."}, status=status.HTTP_404_NOT_FOUND)
        pending.status = Connection.Status.ACCEPTED
        pending.save(update_fields=["status", "updated_at"])
        Connection.objects.update_or_create(
            requester=request.user,
            recipient_id=user_id,
            defaults={"status": Connection.Status.ACCEPTED},
        )
        bump_user_feed_cache_version(request.user.id)
        bump_user_feed_cache_version(user_id)
        create_notification(
            recipient_user_id=user_id,
            actor_user_id=request.user.id,
            event_type="connection.accepted",
            title="Connection approved",
            message=f"@{request.user.username} approved your connection request.",
            payload={"connection_id": int(pending.id), "user_id": int(request.user.id)},
        )
        return Response({"approved": True})


class DenyConnectionView(APIView):
    @transaction.atomic
    def post(self, request, user_id: int):
        deleted_count, _ = Connection.objects.filter(
            requester_id=user_id,
            recipient=request.user,
            status=Connection.Status.PENDING,
        ).delete()
        return Response({"denied": bool(deleted_count > 0)})


class BlockUserView(APIView):
    @transaction.atomic
    def post(self, request, user_id: int):
        if request.user.id == user_id:
            return Response({"detail": "Cannot block yourself."}, status=status.HTTP_400_BAD_REQUEST)
        if not User.objects.filter(id=user_id).exists():
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        Connection.objects.filter(
            Q(requester=request.user, recipient_id=user_id) | Q(requester_id=user_id, recipient=request.user)
        ).exclude(status=Connection.Status.BLOCKED).delete()
        blocked, _ = Connection.objects.update_or_create(
            requester=request.user,
            recipient_id=user_id,
            defaults={"status": Connection.Status.BLOCKED},
        )
        bump_user_feed_cache_version(request.user.id)
        bump_user_feed_cache_version(user_id)
        serializer = ConnectionSerializer(blocked)
        return Response(serializer.data, status=status.HTTP_200_OK)


class UnblockUserView(APIView):
    @transaction.atomic
    def post(self, request, user_id: int):
        deleted_count, _ = Connection.objects.filter(
            requester=request.user,
            recipient_id=user_id,
            status=Connection.Status.BLOCKED,
        ).delete()
        bump_user_feed_cache_version(request.user.id)
        bump_user_feed_cache_version(user_id)
        return Response({"unblocked": bool(deleted_count > 0)})
