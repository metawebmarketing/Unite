import ipaddress
import json
from typing import Optional
from urllib.error import URLError
from urllib.request import Request, urlopen

from apps.accounts.runtime_config import get_runtime_config


def normalize_country_name(value: str) -> str:
    return str(value or "").strip().lower()


def extract_client_ip(request) -> str:
    forwarded_for = str(request.META.get("HTTP_X_FORWARDED_FOR", "")).strip()
    if forwarded_for:
        return str(forwarded_for.split(",")[0]).strip()
    real_ip = str(request.META.get("HTTP_X_REAL_IP", "")).strip()
    if real_ip:
        return real_ip
    return str(request.META.get("REMOTE_ADDR", "")).strip()


def is_lookup_eligible_ip(raw_ip: str) -> bool:
    try:
        parsed = ipaddress.ip_address(raw_ip)
    except ValueError:
        return False
    if parsed.is_private or parsed.is_loopback or parsed.is_link_local or parsed.is_reserved or parsed.is_multicast:
        return False
    return True


def lookup_country_by_ip(raw_ip: str) -> Optional[str]:
    if not is_lookup_eligible_ip(raw_ip):
        return None
    runtime_config = get_runtime_config()
    url_template = str(runtime_config.get("ip_country_lookup_url_template", "") or "").strip()
    if not url_template:
        return None
    request_url = url_template.format(ip=raw_ip)
    timeout_seconds = float(runtime_config.get("ip_country_lookup_timeout_seconds", 3.0) or 3.0)
    http_request = Request(request_url, headers={"User-Agent": "UniteSignupCountryCheck/1.0"})
    try:
        with urlopen(http_request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (URLError, TimeoutError, OSError, ValueError):
        return None
    if str(payload.get("status", "")).lower() != "success":
        return None
    country_name = str(payload.get("country", "")).strip()
    return country_name or None


def is_signup_country_valid_for_ip(request, selected_country: str) -> bool:
    runtime_config = get_runtime_config()
    enforce = bool(runtime_config.get("enforce_signup_ip_country_match", True))
    if not enforce:
        return True
    client_ip = extract_client_ip(request)
    if not client_ip:
        return True
    ip_country = lookup_country_by_ip(client_ip)
    if not ip_country:
        allow_on_failure = bool(runtime_config.get("allow_signup_on_ip_country_lookup_failure", True))
        return allow_on_failure
    return normalize_country_name(ip_country) == normalize_country_name(selected_country)
