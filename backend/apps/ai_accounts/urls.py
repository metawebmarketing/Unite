from django.urls import path

from apps.ai_accounts.views import AiAuditListView, AiSignupView

urlpatterns = [
    path("signup", AiSignupView.as_view(), name="ai-signup"),
    path("audit", AiAuditListView.as_view(), name="ai-audit"),
]
