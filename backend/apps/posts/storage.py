from urllib.parse import urlparse

from django.conf import settings
from django.core.files.storage import storages

from apps.accounts.runtime_config import get_runtime_config


class MediaStorageConfigError(Exception):
    pass


def get_media_storage_mode() -> str:
    runtime = get_runtime_config()
    token = str(runtime.get("media_storage_mode", "local") or "local").strip().lower()
    if token not in {"local", "s3"}:
        return "local"
    return token


def get_media_storage_for_mode(mode: str):
    normalized_mode = str(mode or "local").strip().lower()
    if normalized_mode not in {"local", "s3"}:
        normalized_mode = "local"
    if normalized_mode == "local":
        return storages["default"]
    alias = str(getattr(settings, "UNITE_MEDIA_S3_STORAGE_ALIAS", "media_s3") or "media_s3").strip()
    try:
        return storages[alias]
    except Exception as exc:
        raise MediaStorageConfigError(
            f"Media storage alias '{alias}' is not configured for mode '{normalized_mode}'."
        ) from exc


def get_media_storage():
    return get_media_storage_for_mode(get_media_storage_mode())


def resolve_public_media_url(raw_url: str, request=None) -> str:
    token = str(raw_url or "").strip()
    if not token:
        return ""
    runtime = get_runtime_config()
    media_base_url = str(runtime.get("media_public_base_url", "") or "").strip().rstrip("/")
    parsed = urlparse(token)
    if parsed.scheme and parsed.netloc and not parsed.path.startswith(str(getattr(settings, "MEDIA_URL", "/media/"))):
        return token
    if not media_base_url:
        if parsed.scheme and parsed.netloc:
            return token
        if request is not None:
            return request.build_absolute_uri(token)
        return token
    path = parsed.path if (parsed.scheme and parsed.netloc) else token
    normalized_path = f"/{str(path or '').lstrip('/')}"
    return f"{media_base_url}{normalized_path}"


def build_media_url_from_saved_name(saved_name: str, request=None, storage_mode: str | None = None) -> str:
    storage = get_media_storage_for_mode(storage_mode) if storage_mode else get_media_storage()
    storage_url = str(storage.url(saved_name) or "")
    return resolve_public_media_url(storage_url, request)
