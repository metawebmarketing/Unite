from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from apps.notifications.models import Notification


def user_realtime_group(user_id: int) -> str:
    return f"user-{user_id}"


@database_sync_to_async
def unread_count_for_user(user_id: int) -> int:
    return Notification.objects.filter(recipient_id=user_id, is_read=False).count()


class NotificationConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        user = self.scope.get("user")
        if not user or not getattr(user, "is_authenticated", False):
            await self.close(code=4401)
            return
        self.user_id = int(user.id)
        self.group_name = user_realtime_group(self.user_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        unread_count = await unread_count_for_user(self.user_id)
        await self.send_json(
            {
                "event_type": "realtime.connected",
                "payload": {"unread_count": int(unread_count)},
            }
        )

    async def disconnect(self, code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive_json(self, content, **kwargs):
        action = str(content.get("action", "")).strip().lower()
        if action == "ping":
            await self.send_json({"event_type": "realtime.pong", "payload": {}})

    async def realtime_event(self, event):
        await self.send_json(
            {
                "event_type": str(event.get("event_type", "")).strip(),
                "payload": event.get("payload", {}) or {},
            }
        )
