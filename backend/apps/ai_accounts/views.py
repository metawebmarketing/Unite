from rest_framework import permissions, status
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.ai_accounts.models import AiActionAudit
from apps.ai_accounts.serializers import (
    AiActionAuditSerializer,
    AiSignupResponseSerializer,
    AiSignupSerializer,
    build_ai_auth_payload,
)
from apps.ai_accounts.services import log_ai_action


class AiSignupView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "ai_signup"

    def post(self, request):
        serializer = AiSignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user, ai_profile = serializer.save()
        payload = build_ai_auth_payload(user, ai_profile)
        log_ai_action(
            user=user,
            action_name="ai_signup",
            endpoint="/api/v1/ai/signup",
            method="POST",
            status_code=status.HTTP_201_CREATED,
            payload={"provider_name": ai_profile.provider_name, "model_name": ai_profile.model_name},
        )
        response_serializer = AiSignupResponseSerializer(payload)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class AiAuditListView(APIView):
    def get(self, request):
        audits = AiActionAudit.objects.order_by("-created_at")
        if request.user.is_staff:
            user_id = request.query_params.get("user_id")
            if user_id:
                audits = audits.filter(user_id=user_id)
        else:
            if not hasattr(request.user, "ai_account"):
                return Response({"detail": "AI account required."}, status=status.HTTP_403_FORBIDDEN)
            audits = audits.filter(user=request.user)

        action_name = str(request.query_params.get("action_name", "")).strip()
        if action_name:
            audits = audits.filter(action_name=action_name)
        method = str(request.query_params.get("method", "")).strip().upper()
        if method:
            audits = audits.filter(method=method)
        status_code = request.query_params.get("status_code")
        if status_code:
            audits = audits.filter(status_code=status_code)
        limit = max(1, min(int(request.query_params.get("limit", 100)), 500))

        serializer = AiActionAuditSerializer(audits[:limit], many=True)
        return Response(serializer.data)
