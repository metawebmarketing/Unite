from django.db.models import Q
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.notifications.models import Notification
from apps.notifications.serializers import NotificationSerializer
from apps.notifications.services import mark_all_notifications_read, unread_notification_count


class NotificationListView(APIView):
    def get(self, request):
        page_size = max(1, min(int(request.query_params.get("page_size", 30)), 100))
        cursor = str(request.query_params.get("cursor", "")).strip()
        queryset = Notification.objects.filter(recipient=request.user).order_by("-created_at", "-id")
        if cursor:
            try:
                cursor_id = int(cursor)
            except ValueError:
                cursor_id = 0
            if cursor_id > 0:
                anchor = Notification.objects.filter(id=cursor_id, recipient=request.user).first()
                if anchor:
                    queryset = queryset.filter(
                        Q(created_at__lt=anchor.created_at)
                        | (Q(created_at=anchor.created_at) & Q(id__lt=anchor.id))
                    )

        page_items = list(queryset[: page_size + 1])
        has_more = len(page_items) > page_size
        items = page_items[:page_size]
        next_cursor = str(items[-1].id) if has_more and items else None
        serializer = NotificationSerializer(items, many=True)
        return Response(
            {
                "items": serializer.data,
                "unread_count": unread_notification_count(request.user.id),
                "next_cursor": next_cursor,
                "has_more": has_more,
            }
        )


class NotificationMarkAllReadView(APIView):
    def post(self, request):
        unread_count = mark_all_notifications_read(user_id=request.user.id)
        return Response({"unread_count": unread_count})
