from django.urls import path

from apps.ads.views import AdEventIngestView, AdMetricsView, AdSlotConfigDetailView, AdSlotConfigListCreateView

urlpatterns = [
    path("events", AdEventIngestView.as_view(), name="ads-events"),
    path("metrics", AdMetricsView.as_view(), name="ads-metrics"),
    path("configs", AdSlotConfigListCreateView.as_view(), name="ads-configs"),
    path("configs/<int:config_id>", AdSlotConfigDetailView.as_view(), name="ads-config-detail"),
]
