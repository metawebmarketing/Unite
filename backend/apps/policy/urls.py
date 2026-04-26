from django.urls import path

from apps.policy.views import PolicyPackListCreateView, PolicyResolveView

urlpatterns = [
    path("resolve", PolicyResolveView.as_view(), name="policy-resolve"),
    path("packs", PolicyPackListCreateView.as_view(), name="policy-packs"),
]
