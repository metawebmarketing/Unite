from django.urls import path

from apps.accounts.views import ProfileImageUploadView, ProfileView, PublicProfileView

urlpatterns = [
    path("", ProfileView.as_view(), name="profile-detail"),
    path("image", ProfileImageUploadView.as_view(), name="profile-image-upload"),
    path("users/<int:user_id>", PublicProfileView.as_view(), name="profile-public-detail"),
]
