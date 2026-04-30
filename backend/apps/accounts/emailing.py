from django.conf import settings
from django.core.mail import get_connection
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags

from apps.accounts.runtime_config import get_runtime_config


def _site_context() -> dict:
    runtime_config = get_runtime_config()
    site_name = str(runtime_config.get("site_name", "")).strip() or "Unite"
    frontend_base_url = str(runtime_config.get("frontend_base_url", "")).rstrip("/") or "http://localhost:5173"
    support_email = str(runtime_config.get("support_email", "")).strip() or "support@unite.local"
    return {
        "site_name": site_name,
        "frontend_base_url": frontend_base_url,
        "support_email": support_email,
    }


def send_templated_email(
    *,
    to_email: str,
    subject: str,
    template_name: str,
    template_context: dict | None = None,
) -> None:
    runtime_config = get_runtime_config()
    context = {
        **_site_context(),
        **(template_context or {}),
    }
    html_body = render_to_string(template_name, context)
    text_body = strip_tags(html_body)
    email_backend = str(runtime_config.get("email_backend", "")).strip() or getattr(settings, "EMAIL_BACKEND", "")
    connection = get_connection(
        backend=email_backend,
        host=str(runtime_config.get("email_host", "")).strip(),
        port=int(runtime_config.get("email_port", 25) or 25),
        username=str(runtime_config.get("email_host_user", "")).strip(),
        password=str(runtime_config.get("email_host_password", "")).strip(),
        use_tls=bool(runtime_config.get("email_use_tls", False)),
        use_ssl=bool(runtime_config.get("email_use_ssl", False)),
        timeout=float(runtime_config.get("email_timeout_seconds", 10.0) or 10.0),
    )
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=str(runtime_config.get("default_from_email", "")).strip()
        or getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@unite.local"),
        to=[str(to_email).strip()],
        connection=connection,
    )
    message.attach_alternative(html_body, "text/html")
    message.send(fail_silently=False)


def send_password_reset_email(*, to_email: str, reset_url: str) -> None:
    send_templated_email(
        to_email=to_email,
        subject="Unite password reset instructions",
        template_name="emails/password_reset.html",
        template_context={"reset_url": reset_url},
    )


def send_signup_invite_email(*, to_email: str, invite_url: str) -> None:
    send_templated_email(
        to_email=to_email,
        subject="You are invited to join Unite",
        template_name="emails/invite_signup.html",
        template_context={"invite_url": invite_url},
    )
