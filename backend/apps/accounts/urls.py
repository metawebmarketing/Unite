from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import (
    LoginView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    PublicSignupConfigView,
    PublicSignupInviteValidationView,
    SendSignupInviteView,
    SiteSettingsView,
    SignupView,
)

urlpatterns = [
    path("signup", SignupView.as_view(), name="signup"),
    path("signup-config", PublicSignupConfigView.as_view(), name="signup-config"),
    path("signup-invite/validate", PublicSignupInviteValidationView.as_view(), name="signup-invite-validate"),
    path("login", LoginView.as_view(), name="login"),
    path("token/refresh", TokenRefreshView.as_view(), name="token-refresh"),
    path("password-reset/request", PasswordResetRequestView.as_view(), name="password-reset-request"),
    path("password-reset/confirm", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
    path("site-settings", SiteSettingsView.as_view(), name="site-settings"),
    path("site-settings/send-invite", SendSignupInviteView.as_view(), name="site-settings-send-invite"),
]
