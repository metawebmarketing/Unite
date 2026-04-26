from rest_framework.response import Response
from rest_framework.views import APIView

from apps.moderation.models import ModerationFlag
from apps.moderation.serializers import ModerationFlagSerializer


class ModerationFlagListView(APIView):
    def get(self, request):
        queryset = ModerationFlag.objects.order_by("-created_at")[:200]
        serializer = ModerationFlagSerializer(queryset, many=True)
        return Response(serializer.data)
