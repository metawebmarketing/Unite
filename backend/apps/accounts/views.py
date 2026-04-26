from django.shortcuts import get_object_or_404
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
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
        queue_profile_generation(updated_profile.id, updated_profile.location or "global")
        return Response(serializer.data)


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
