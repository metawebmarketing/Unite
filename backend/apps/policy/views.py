from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import status
from rest_framework.permissions import IsAdminUser, IsAuthenticated

from apps.policy.models import PolicyPack
from apps.policy.serializers import (
    PolicyPackSerializer,
    PolicyResolveRequestSerializer,
    PolicyResolveResponseSerializer,
)
from apps.policy.services import resolve_policy


class PolicyResolveView(APIView):
    def get_permissions(self):
        return [IsAdminUser()]

    def post(self, request):
        request_serializer = PolicyResolveRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        policy = resolve_policy(
            request_serializer.validated_data["region_code"],
            user_key=request_serializer.validated_data.get("user_key") or None,
            at_time=request_serializer.validated_data.get("at_time"),
        )
        response_serializer = PolicyResolveResponseSerializer(policy.__dict__)
        return Response(response_serializer.data)


class PolicyPackListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAdminUser()]
        return [IsAuthenticated()]

    def get(self, request):
        region_code = request.query_params.get("region_code")
        queryset = PolicyPack.objects.order_by("-created_at")
        if region_code:
            queryset = queryset.filter(region_code=region_code.lower())
        serializer = PolicyPackSerializer(queryset[:100], many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = PolicyPackSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save(region_code=serializer.validated_data["region_code"].lower())
        return Response(serializer.data, status=status.HTTP_201_CREATED)
