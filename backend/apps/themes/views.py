from rest_framework import status
from rest_framework.permissions import AllowAny, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.themes.models import ThemeConfig
from apps.themes.serializers import ThemeConfigSerializer, ThemeUploadSerializer


class ThemeUploadView(APIView):
    def get_permissions(self):
        return [IsAdminUser()]

    def post(self, request):
        serializer = ThemeUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ThemeConfig.objects.filter(is_active=True).update(is_active=False)
        theme = ThemeConfig.objects.create(
            name=serializer.validated_data["name"],
            version=serializer.validated_data["version"],
            tokens=serializer.validated_data["tokens"],
            is_active=True,
            uploaded_by=request.user,
        )
        response_serializer = ThemeConfigSerializer(theme)
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class ActiveThemeView(APIView):
    def get_permissions(self):
        return [AllowAny()]

    def get(self, request):
        theme = ThemeConfig.objects.filter(is_active=True).order_by("-updated_at").first()
        if not theme:
            return Response(None, status=status.HTTP_200_OK)
        serializer = ThemeConfigSerializer(theme)
        return Response(serializer.data)
