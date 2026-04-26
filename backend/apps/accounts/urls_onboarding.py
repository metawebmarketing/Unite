from django.urls import path

from apps.accounts.views import OnboardingInterestsView

urlpatterns = [
    path("interests", OnboardingInterestsView.as_view(), name="onboarding-interests"),
]
