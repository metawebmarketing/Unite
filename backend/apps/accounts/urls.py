from django.urls import path

from apps.accounts.views import (
    LoginView,
    PasswordResetConfirmView,
    PasswordResetRequestView,
    SignupView,
)

urlpatterns = [
    path("signup", SignupView.as_view(), name="signup"),
    path("login", LoginView.as_view(), name="login"),
    path("password-reset/request", PasswordResetRequestView.as_view(), name="password-reset-request"),
    path("password-reset/confirm", PasswordResetConfirmView.as_view(), name="password-reset-confirm"),
]
