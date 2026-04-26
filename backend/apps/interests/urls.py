from django.urls import path

from apps.interests.views import InterestSuggestionsView, TopInterestPostsView, TopInterestsView

urlpatterns = [
    path("top", TopInterestsView.as_view(), name="interests-top"),
    path("top-posts", TopInterestPostsView.as_view(), name="interests-top-posts"),
    path("suggest", InterestSuggestionsView.as_view(), name="interests-suggest"),
]
