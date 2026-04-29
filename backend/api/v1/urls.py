from django.urls import include, path

urlpatterns = [
    path("auth/", include("apps.accounts.urls")),
    path("ai/", include("apps.ai_accounts.urls")),
    path("onboarding/", include("apps.accounts.urls_onboarding")),
    path("profile/", include("apps.accounts.urls_profile")),
    path("connections/", include("apps.connections.urls")),
    path("posts/", include("apps.posts.urls")),
    path("messages/", include("apps.messaging.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("notifications", include("apps.notifications.urls")),
    path("feed/", include("apps.feed.urls")),
    path("interests/", include("apps.interests.urls")),
    path("moderation/", include("apps.moderation.urls")),
    path("policy/", include("apps.policy.urls")),
    path("themes/", include("apps.themes.urls")),
    path("themes", include("apps.themes.urls")),
    path("ads/", include("apps.ads.urls")),
    path("install/", include("apps.install.urls")),
]
