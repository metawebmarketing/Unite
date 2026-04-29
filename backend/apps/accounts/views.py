from django.shortcuts import get_object_or_404
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.db.models import Q
from django.utils.http import urlsafe_base64_encode
from django.utils.encoding import force_bytes
from rest_framework import permissions, status
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import Profile
from apps.accounts.image_processing import optimize_profile_image
from apps.accounts.services import queue_profile_generation
from apps.accounts.serializers import (
    AuthResponseSerializer,
    LoginSerializer,
    OnboardingInterestsSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    ProfileImageUploadSerializer,
    ProfileSerializer,
    SignupSerializer,
    build_auth_payload,
)
from apps.connections.models import Connection

User = get_user_model()
class SignupView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = SignupSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        profile = Profile.objects.get(user=user)
        queue_profile_generation(profile.id, profile.location or "global")
        payload = build_auth_payload(user)
        return Response(AuthResponseSerializer(payload).data, status=status.HTTP_201_CREATED)


class LoginView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        payload = build_auth_payload(user)
        return Response(AuthResponseSerializer(payload).data)


class PasswordResetRequestView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset_request"

    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        user = User.objects.filter(email__iexact=email, is_active=True).first()

        response_payload = {
            "message": "If an account exists for this email, reset instructions have been issued.",
        }
        if user:
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = default_token_generator.make_token(user)
            reset_path = f"/reset-password?uid={uid}&token={token}"
            send_mail(
                subject="Unite password reset instructions",
                message=f"Use this reset link: {reset_path}",
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@unite.local"),
                recipient_list=[user.email],
                fail_silently=True,
            )
            if settings.DEBUG:
                response_payload["debug_reset"] = {"uid": uid, "token": token}
        return Response(response_payload, status=status.HTTP_202_ACCEPTED)


class PasswordResetConfirmView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "password_reset_confirm"

    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        user.set_password(serializer.validated_data["new_password"])
        user.save(update_fields=["password"])
        return Response({"message": "Password has been reset."}, status=status.HTTP_200_OK)


class ProfileView(APIView):
    def get(self, request):
        profile = get_object_or_404(Profile, user=request.user)
        serializer = ProfileSerializer(profile, context={"request": request})
        return Response(serializer.data)

    def patch(self, request):
        profile = get_object_or_404(Profile, user=request.user)
        serializer = ProfileSerializer(profile, data=request.data, partial=True, context={"request": request})
        serializer.is_valid(raise_exception=True)
        updated_profile = serializer.save()
        if any(field in serializer.validated_data for field in ("location", "interests")):
            queue_profile_generation(updated_profile.id, updated_profile.location or "global")
        return Response(serializer.data)


class PublicProfileView(APIView):
    def get(self, request, user_id: int):
        profile = get_object_or_404(Profile.objects.select_related("user"), user_id=user_id)
        serializer = ProfileSerializer(profile, context={"request": request})
        payload = dict(serializer.data)
        payload["user_id"] = profile.user_id
        payload["username"] = profile.user.username
        is_self = bool(request.user.id == profile.user_id)
        is_staff = bool(getattr(request.user, "is_staff", False))
        is_connected = Connection.objects.filter(
            status=Connection.Status.ACCEPTED,
        ).filter(
            Q(requester=request.user, recipient_id=profile.user_id)
            | Q(requester_id=profile.user_id, recipient=request.user)
        ).exists()
        is_blocked = Connection.objects.filter(
            status=Connection.Status.BLOCKED,
        ).filter(
            Q(requester=request.user, recipient_id=profile.user_id)
            | Q(requester_id=profile.user_id, recipient=request.user)
        ).exists()
        can_view_private = bool(is_self or is_staff or is_connected)
        is_limited_view = bool(is_blocked or (profile.is_private_profile and not can_view_private))
        for private_field in (
            "receive_notifications",
            "receive_email_notifications",
            "receive_push_notifications",
            "is_private_profile",
            "require_connection_approval",
            "algorithm_profile_status",
            "algorithm_vector",
            "rank_overall_score",
            "rank_action_scores",
            "rank_last_500_count",
            "rank_provider",
        ):
            payload.pop(private_field, None)
        if is_limited_view:
            allowed_fields = {
                "display_name",
                "bio",
                "location",
                "profile_link_url",
                "profile_image_url",
                "username",
                "user_id",
                "connection_count",
                "is_ai_account",
                "ai_badge_enabled",
            }
            payload = {key: value for key, value in payload.items() if key in allowed_fields}
        payload["is_limited_view"] = is_limited_view
        payload["can_view_feed"] = bool(not is_limited_view)
        payload["is_blocked_view"] = is_blocked
        return Response(payload)


class ProfileImageUploadView(APIView):
    def post(self, request):
        profile = get_object_or_404(Profile, user=request.user)
        serializer = ProfileImageUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        processed = optimize_profile_image(
            serializer.validated_data["image"],
            crop_x=serializer.validated_data.get("crop_x"),
            crop_y=serializer.validated_data.get("crop_y"),
            crop_size=serializer.validated_data.get("crop_size"),
            output_size=int(getattr(settings, "UNITE_PROFILE_IMAGE_SIZE", 256)),
        )
        filename = f"profile-{profile.user_id}.jpg"
        profile.profile_image.save(filename, processed, save=True)
        response_serializer = ProfileSerializer(profile, context={"request": request})
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class OnboardingInterestsView(APIView):
    def post(self, request):
        serializer = OnboardingInterestsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        profile = get_object_or_404(Profile, user=request.user)
        profile.interests = serializer.validated_data["interests"]
        if "location" in serializer.validated_data:
            profile.location = serializer.validated_data["location"]
        profile.save(update_fields=["interests", "location", "updated_at"])
        queue_profile_generation(profile.id, profile.location or "global")
        return Response(
            {
                "interests_count": len(profile.interests),
                "location": profile.location,
                "profile_generation": "queued",
            },
            status=status.HTTP_202_ACCEPTED,
        )
