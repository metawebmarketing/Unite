from django.db import transaction
from rest_framework import status
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.connections.models import Connection
from apps.connections.serializers import ConnectionSerializer


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

        connection, _ = Connection.objects.get_or_create(
            requester=request.user,
            recipient_id=user_id,
            defaults={"status": Connection.Status.PENDING},
        )
        reverse = Connection.objects.filter(requester_id=user_id, recipient=request.user).first()
        if reverse and connection.status != Connection.Status.ACCEPTED:
            connection.status = Connection.Status.ACCEPTED
            reverse.status = Connection.Status.ACCEPTED
            connection.save(update_fields=["status", "updated_at"])
            reverse.save(update_fields=["status", "updated_at"])

        serializer = ConnectionSerializer(connection)
        return Response(serializer.data, status=status.HTTP_201_CREATED)
