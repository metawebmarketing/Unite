from django.urls import path

from apps.accounts.views import ProfileImageUploadView, ProfileView

urlpatterns = [
    path("", ProfileView.as_view(), name="profile-detail"),
    path("image", ProfileImageUploadView.as_view(), name="profile-image-upload"),
]
