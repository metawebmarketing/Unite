from django.urls import path

from apps.themes.views import ActiveThemeView, ThemeUploadView

urlpatterns = [
    path("upload", ThemeUploadView.as_view(), name="theme-upload"),
    path("upload/", ThemeUploadView.as_view(), name="theme-upload-slash"),
    path("active", ActiveThemeView.as_view(), name="theme-active"),
    path("active/", ActiveThemeView.as_view(), name="theme-active-slash"),
]
