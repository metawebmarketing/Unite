from django.urls import path

from apps.install.views import DemoDataResetView, InstallRunView, InstallStatusView

urlpatterns = [
    path("status", InstallStatusView.as_view(), name="install-status"),
    path("run", InstallRunView.as_view(), name="install-run"),
    path("demo-data/reset", DemoDataResetView.as_view(), name="install-demo-reset"),
]
