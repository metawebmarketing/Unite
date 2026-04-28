from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.contrib.auth import get_user_model

from apps.notifications.consumers import user_realtime_group
from apps.notifications.models import Notification

User = get_user_model()


def push_realtime_event(*, user_id: int, event_type: str, payload: dict | None = None) -> None:
    channel_layer = get_channel_layer()
    if not channel_layer or user_id <= 0:
        return
    try:
        async_to_sync(channel_layer.group_send)(
            user_realtime_group(int(user_id)),
            {
                "type": "realtime.event",
                "event_type": str(event_type).strip(),
                "payload": payload or {},
            },
        )
    except Exception:
        # Realtime delivery should not break request/worker execution.
        return


def unread_notification_count(user_id: int) -> int:
    if user_id <= 0:
        return 0
    return Notification.objects.filter(recipient_id=user_id, is_read=False).count()


def create_notification(
    *,
    recipient_user_id: int,
    actor_user_id: int | None = None,
    event_type: str,
    title: str = "",
    message: str = "",
    payload: dict | None = None,
) -> Notification | None:
    recipient_user_id = int(recipient_user_id or 0)
    if recipient_user_id <= 0:
        return None
    if actor_user_id and int(actor_user_id) == recipient_user_id:
        return None
    if not User.objects.filter(id=recipient_user_id, is_active=True).exists():
        return None
    notification = Notification.objects.create(
        recipient_id=recipient_user_id,
        actor_user_id=int(actor_user_id) if actor_user_id else None,
        event_type=str(event_type).strip(),
        title=str(title).strip(),
        message=str(message).strip(),
        payload=payload or {},
    )
    unread_count = unread_notification_count(recipient_user_id)
    push_realtime_event(
        user_id=recipient_user_id,
        event_type="notification.created",
        payload={"notification": serialize_notification(notification), "unread_count": unread_count},
    )
    push_realtime_event(
        user_id=recipient_user_id,
        event_type="notification.unread_count",
        payload={"unread_count": unread_count},
    )
    return notification


def mark_all_notifications_read(*, user_id: int) -> int:
    user_id = int(user_id or 0)
    if user_id <= 0:
        return 0
    Notification.objects.filter(recipient_id=user_id, is_read=False).update(is_read=True)
    push_realtime_event(
        user_id=user_id,
        event_type="notification.unread_count",
        payload={"unread_count": 0},
    )
    return 0


def serialize_notification(notification: Notification) -> dict:
    return {
        "id": int(notification.id),
        "recipient_id": int(notification.recipient_id),
        "actor_user_id": int(notification.actor_user_id) if notification.actor_user_id else None,
        "event_type": str(notification.event_type or ""),
        "title": str(notification.title or ""),
        "message": str(notification.message or ""),
        "payload": notification.payload if isinstance(notification.payload, dict) else {},
        "is_read": bool(notification.is_read),
        "created_at": notification.created_at.isoformat(),
    }
