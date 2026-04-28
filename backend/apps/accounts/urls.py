from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from apps.accounts.views import (
    LoginView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    SignupView,
)

urlpatterns = [
    path("signup", SignupView.as_view(), name="signup"),
    path("login", LoginView.as_view(), name="login"),
    path("token/refresh", TokenRefreshView.as_view(), name="token-refresh"),
    path("password-reset/request", PasswordResetRequestView.as_view(), name="password-reset-request"),
    path("password-reset/confirm", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
]
