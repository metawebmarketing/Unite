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

User = get_user_model()


def encode_cursor(updated_at: datetime, connection_id: int) -> str:
    payload = {"updated_at": updated_at.isoformat(), "connection_id": connection_id}
    raw = json.dumps(payload).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii")


def decode_cursor(cursor: str) -> dict:
    raw = base64.urlsafe_b64decode(cursor.encode("ascii"))
    return json.loads(raw.decode("utf-8"))


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

        queryset = Profile.objects.select_related("user").exclude(user_id=request.user.id)
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
                    "is_connected": False,
                    "common_connections": [],
                    "common_connection_count": 0,
                }
            )
        target_user = User.objects.filter(id=user_id).first()
        if not target_user:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        is_connected = Connection.objects.filter(
            status=Connection.Status.ACCEPTED,
        ).filter(
            Q(requester=request.user, recipient_id=user_id) | Q(requester_id=user_id, recipient=request.user)
        ).exists()

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
                "is_connected": is_connected,
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
        if not User.objects.filter(id=user_id).exists():
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        connection, _ = Connection.objects.get_or_create(
            requester=request.user,
            recipient_id=user_id,
            defaults={"status": Connection.Status.ACCEPTED},
        )
        if connection.status != Connection.Status.ACCEPTED:
            connection.status = Connection.Status.ACCEPTED
            connection.save(update_fields=["status", "updated_at"])
        reverse = Connection.objects.filter(requester_id=user_id, recipient=request.user).first()
        if reverse and reverse.status != Connection.Status.ACCEPTED:
            reverse.status = Connection.Status.ACCEPTED
            reverse.save(update_fields=["status", "updated_at"])
        bump_user_feed_cache_version(request.user.id)
        bump_user_feed_cache_version(user_id)

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
