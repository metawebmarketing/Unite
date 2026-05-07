from django.contrib.auth import get_user_model
from django.db.models import Count, IntegerField, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Profile
from apps.moderation.models import ModerationFlag, ModerationPenalty
from apps.moderation.serializers import (
    AccountBanSerializer,
    ModerationDecisionSerializer,
    ModerationFlagSerializer,
    ModerationPenaltySerializer,
    PenaltyRemovalSerializer,
)
from apps.moderation.services import expire_stale_penalties, resolve_flag_decision


class ModerationFlagListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        queryset = ModerationFlag.objects.order_by("-created_at")
        status_filter = str(request.query_params.get("status", "")).strip().lower()
        category_filter = str(request.query_params.get("category", "")).strip().lower()
        reporter_user_id_filter = str(request.query_params.get("reporter_user_id", "")).strip()
        target_user_id_filter = str(request.query_params.get("target_user_id", "")).strip()
        created_after = str(request.query_params.get("created_after", "")).strip()
        created_before = str(request.query_params.get("created_before", "")).strip()
        query = str(request.query_params.get("query", "")).strip()
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if category_filter:
            queryset = queryset.filter(category=category_filter)
        if reporter_user_id_filter.isdigit():
            queryset = queryset.filter(reporter_user_id=int(reporter_user_id_filter))
        if target_user_id_filter.isdigit():
            queryset = queryset.filter(target_user_id=int(target_user_id_filter))
        if query:
            queryset = queryset.filter(
                Q(reason__icontains=query)
                | Q(category__icontains=query)
                | Q(content_type__icontains=query)
            )
        if created_after:
            queryset = queryset.filter(created_at__gte=created_after)
        if created_before:
            queryset = queryset.filter(created_at__lte=created_before)
        limit = max(1, min(500, int(request.query_params.get("limit", 200) or 200)))
        queryset = queryset[:limit]
        serializer = ModerationFlagSerializer(queryset, many=True)
        return Response(serializer.data)


class ModerationFlagDecisionView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, flag_id: int):
        flag = get_object_or_404(ModerationFlag, id=flag_id)
        serializer = ModerationDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        updated_flag = resolve_flag_decision(
            flag=flag,
            reviewer_user_id=request.user.id,
            decision=serializer.validated_data["decision"],
            apply_penalty=serializer.validated_data.get("apply_penalty", True),
            review_note=serializer.validated_data.get("review_note", ""),
            report_outcome=serializer.validated_data.get("report_outcome", "valid_report"),
        )
        return Response(ModerationFlagSerializer(updated_flag).data, status=status.HTTP_200_OK)


class ModerationAccountSearchView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request):
        expire_stale_penalties()
        now = timezone.now()
        query = str(request.query_params.get("query", "")).strip()
        page = max(1, int(request.query_params.get("page", 1) or 1))
        page_size = max(1, min(100, int(request.query_params.get("page_size", 25) or 25)))
        sort_by = str(request.query_params.get("sort_by", "active_penalty_count")).strip().lower()
        sort_dir = str(request.query_params.get("sort_dir", "desc")).strip().lower()

        users = get_user_model().objects.select_related("profile").annotate(
            active_penalty_count=Coalesce(
                Subquery(
                    ModerationPenalty.objects.filter(
                        user_id=OuterRef("id"),
                        active=True,
                        expires_at__gt=now,
                    )
                    .values("user_id")
                    .annotate(total=Count("id"))
                    .values("total")[:1],
                    output_field=IntegerField(),
                ),
                Value(0),
            )
        )
        if query:
            user_filter = (
                Q(username__icontains=query)
                | Q(email__icontains=query)
                | Q(profile__display_name__icontains=query)
            )
            if query.isdigit():
                user_filter = user_filter | Q(id=int(query))
            users = users.filter(user_filter)
        else:
            users = users.filter(active_penalty_count__gt=0)

        sort_fields = {
            "user_id": "id",
            "username": "username",
            "email": "email",
            "active_penalty_count": "active_penalty_count",
            "is_banned": "profile__is_banned",
            "banned_at": "profile__banned_at",
        }
        sort_field = sort_fields.get(sort_by, "active_penalty_count")
        if sort_dir == "asc":
            users = users.order_by(sort_field, "-id")
        else:
            users = users.order_by(f"-{sort_field}", "-id")

        total_count = users.count()
        offset = (page - 1) * page_size
        users = users[offset : offset + page_size]
        payload = []
        for user in users:
            profile = getattr(user, "profile", None)
            payload.append(
                {
                    "user_id": user.id,
                    "username": user.username,
                    "email": user.email,
                    "is_staff": bool(user.is_staff),
                    "is_active": bool(user.is_active),
                    "is_banned": bool(getattr(profile, "is_banned", False)),
                    "banned_at": getattr(profile, "banned_at", None),
                    "banned_reason": str(getattr(profile, "banned_reason", "") or ""),
                    "active_penalty_count": int(getattr(user, "active_penalty_count", 0) or 0),
                }
            )
        return Response(
            {
                "count": total_count,
                "page": page,
                "page_size": page_size,
                "results": payload,
            }
        )


class ModerationPenaltyListView(APIView):
    permission_classes = [IsAdminUser]

    def get(self, request, user_id: int):
        expire_stale_penalties()
        penalties = ModerationPenalty.objects.filter(user_id=user_id).order_by("-created_at")[:200]
        return Response(ModerationPenaltySerializer(penalties, many=True).data)


class ModerationPenaltyRemoveView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, penalty_id: int):
        penalty = get_object_or_404(ModerationPenalty, id=penalty_id)
        serializer = PenaltyRemovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        penalty.active = False
        penalty.removed_by_user_id = request.user.id
        penalty.removed_at = timezone.now()
        penalty.removed_reason = serializer.validated_data.get("remove_reason", "")
        penalty.save(update_fields=["active", "removed_by_user_id", "removed_at", "removed_reason"])
        return Response(ModerationPenaltySerializer(penalty).data)


class ModerationPenaltyClearView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, user_id: int):
        serializer = PenaltyRemovalSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        now = timezone.now()
        remove_reason = serializer.validated_data.get("remove_reason", "")
        penalties = ModerationPenalty.objects.filter(user_id=user_id, active=True)
        updated_count = penalties.update(
            active=False,
            removed_by_user_id=request.user.id,
            removed_at=now,
            removed_reason=remove_reason,
        )
        return Response({"cleared_count": updated_count}, status=status.HTTP_200_OK)


class ModerationBanAccountView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, user_id: int):
        serializer = AccountBanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = get_object_or_404(Profile, user_id=user_id)
        profile.is_banned = True
        profile.banned_at = timezone.now()
        profile.banned_reason = serializer.validated_data.get("reason", "")
        profile.save(update_fields=["is_banned", "banned_at", "banned_reason", "updated_at"])
        return Response({"user_id": user_id, "is_banned": True, "banned_reason": profile.banned_reason})


class ModerationUnbanAccountView(APIView):
    permission_classes = [IsAdminUser]

    def post(self, request, user_id: int):
        profile = get_object_or_404(Profile, user_id=user_id)
        profile.is_banned = False
        profile.banned_at = None
        profile.banned_reason = ""
        profile.save(update_fields=["is_banned", "banned_at", "banned_reason", "updated_at"])
        return Response({"user_id": user_id, "is_banned": False})
