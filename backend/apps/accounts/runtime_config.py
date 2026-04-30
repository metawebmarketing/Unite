from django.conf import settings

from apps.accounts.models import SiteSetting


def _resolved_string(override_value: str, fallback_value: str) -> str:
    token = str(override_value or "").strip()
    if token:
        return token
    return str(fallback_value or "").strip()


def _resolved_number(override_value, fallback_value, caster):
    if override_value is None:
        return caster(fallback_value)
    return caster(override_value)


def _resolved_boolean(override_value, fallback_value) -> bool:
    if override_value is None:
        return bool(fallback_value)
    return bool(override_value)


def get_runtime_config() -> dict:
    settings_obj = SiteSetting.get_solo()
    return {
        "site_name": _resolved_string(settings_obj.site_name, getattr(settings, "UNITE_SITE_NAME", "Unite")),
        "support_email": _resolved_string(
            settings_obj.support_email, getattr(settings, "UNITE_SUPPORT_EMAIL", "support@unite.local")
        ),
        "frontend_base_url": _resolved_string(
            settings_obj.frontend_base_url, getattr(settings, "UNITE_FRONTEND_BASE_URL", "http://localhost:5173")
        ).rstrip("/"),
        "default_from_email": _resolved_string(
            settings_obj.default_from_email, getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@unite.local")
        ),
        "email_backend": _resolved_string(
            settings_obj.email_backend, getattr(settings, "EMAIL_BACKEND", "django.core.mail.backends.smtp.EmailBackend")
        ),
        "email_host": _resolved_string(settings_obj.email_host, getattr(settings, "EMAIL_HOST", "localhost")),
        "email_port": _resolved_number(settings_obj.email_port, getattr(settings, "EMAIL_PORT", 25), int),
        "email_host_user": _resolved_string(settings_obj.email_host_user, getattr(settings, "EMAIL_HOST_USER", "")),
        "email_host_password": _resolved_string(
            settings_obj.email_host_password, getattr(settings, "EMAIL_HOST_PASSWORD", "")
        ),
        "email_use_tls": _resolved_boolean(settings_obj.email_use_tls, getattr(settings, "EMAIL_USE_TLS", False)),
        "email_use_ssl": _resolved_boolean(settings_obj.email_use_ssl, getattr(settings, "EMAIL_USE_SSL", False)),
        "email_timeout_seconds": _resolved_number(
            settings_obj.email_timeout_seconds, getattr(settings, "EMAIL_TIMEOUT", 10), float
        ),
        "enforce_signup_ip_country_match": _resolved_boolean(
            settings_obj.enforce_signup_ip_country_match,
            getattr(settings, "UNITE_ENFORCE_SIGNUP_IP_COUNTRY_MATCH", True),
        ),
        "allow_signup_on_ip_country_lookup_failure": _resolved_boolean(
            settings_obj.allow_signup_on_ip_country_lookup_failure,
            getattr(settings, "UNITE_ALLOW_SIGNUP_ON_IP_COUNTRY_LOOKUP_FAILURE", True),
        ),
        "ip_country_lookup_timeout_seconds": _resolved_number(
            settings_obj.ip_country_lookup_timeout_seconds,
            getattr(settings, "UNITE_IP_COUNTRY_LOOKUP_TIMEOUT_SECONDS", 3.0),
            float,
        ),
        "ip_country_lookup_url_template": _resolved_string(
            settings_obj.ip_country_lookup_url_template,
            getattr(settings, "UNITE_IP_COUNTRY_LOOKUP_URL_TEMPLATE", "http://ip-api.com/json/{ip}?fields=status,country"),
        ),
    }
