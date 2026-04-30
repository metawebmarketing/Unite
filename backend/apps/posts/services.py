import re
from html import unescape
from datetime import timedelta
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from apps.posts.models import LinkPreviewCache


def build_link_preview(url: str) -> dict:
    if not url:
        return {}
    remote_fetch_enabled = bool(getattr(settings, "UNITE_ENABLE_REMOTE_LINK_FETCH", False))
    cached = LinkPreviewCache.objects.filter(url=url, expires_at__gt=timezone.now()).first()
    if cached:
        cached_preview = {
            "url": url,
            "host": cached.host,
            "title": cached.title,
            "description": cached.description,
            "image_url": cached.image_url,
            "source": cached.source,
        }
        if cached.image_url or not remote_fetch_enabled:
            return cached_preview
        # Backfill stale cache records that were created before image extraction support.
        preview = fetch_remote_link_metadata(url=url, fallback=cached_preview)
        ttl_seconds = int(getattr(settings, "UNITE_LINK_PREVIEW_TTL_SECONDS", 86400))
        LinkPreviewCache.objects.update_or_create(
            url=url,
            defaults={
                "host": preview["host"],
                "title": preview["title"][:255],
                "description": preview["description"][:512],
                "image_url": str(preview.get("image_url", ""))[:2048],
                "source": preview["source"],
                "expires_at": timezone.now() + timedelta(seconds=max(60, ttl_seconds)),
            },
        )
        return preview

    parsed = urlparse(url)
    host = parsed.netloc.lower()
    path = parsed.path.strip("/") or "home"
    fallback_title = path.split("/")[-1].replace("-", " ").replace("_", " ").strip()
    fallback_title = fallback_title[:80].title() if fallback_title else host

    preview = {
        "url": url,
        "host": host,
        "title": fallback_title or host,
        "description": f"Preview from {host}",
        "image_url": "",
        "source": "fallback",
    }
    if remote_fetch_enabled:
        preview = fetch_remote_link_metadata(url=url, fallback=preview)

    ttl_seconds = int(getattr(settings, "UNITE_LINK_PREVIEW_TTL_SECONDS", 86400))
    LinkPreviewCache.objects.update_or_create(
        url=url,
        defaults={
            "host": preview["host"],
            "title": preview["title"][:255],
            "description": preview["description"][:512],
            "image_url": str(preview.get("image_url", ""))[:2048],
            "source": preview["source"],
            "expires_at": timezone.now() + timedelta(seconds=max(60, ttl_seconds)),
        },
    )
    return preview


def fetch_remote_link_metadata(url: str, fallback: dict) -> dict:
    try:
        request = Request(url, headers={"User-Agent": "UniteBot/1.0"})
        with urlopen(request, timeout=3) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                return fallback
            html = response.read(32768).decode("utf-8", errors="ignore")
    except Exception:
        return fallback

    title = extract_html_title(html, fallback["title"])
    description = (
        extract_meta_content(html, "description")
        or extract_meta_content(html, "og:description")
        or fallback["description"]
    )
    image_url = (
        extract_meta_content(html, "og:image")
        or extract_meta_content(html, "og:image:secure_url")
        or extract_meta_content(html, "og:image:url")
        or extract_meta_content(html, "twitter:image")
        or extract_meta_content(html, "twitter:image:src")
        or extract_meta_content(html, "image")
        or ""
    )
    normalized_image_url = normalize_remote_url(image_url, fallback["url"])
    if not normalized_image_url:
        normalized_image_url = fetch_origin_image_fallback(url)
    return {
        **fallback,
        "title": title[:255],
        "description": description[:512],
        "image_url": normalized_image_url[:2048],
        "source": "remote",
    }


def extract_html_title(html: str, fallback: str) -> str:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    if not title_match:
        return fallback
    title = unescape(title_match.group(1)).strip()
    return title or fallback


def extract_meta_content(html: str, name_or_property: str) -> str:
    target_key = str(name_or_property).strip().lower()
    for attributes in iter_meta_attributes(html):
        selector = str(
            attributes.get("property") or attributes.get("name") or attributes.get("itemprop") or ""
        ).strip().lower()
        content = str(attributes.get("content") or "").strip()
        if selector == target_key and content:
            return unescape(content)
    return ""


def iter_meta_attributes(html: str):
    meta_tags = re.findall(r"<meta\b[^>]*>", html, flags=re.IGNORECASE | re.DOTALL)
    for tag in meta_tags:
        attributes = {}
        for key, double_quoted, single_quoted, bare_value in re.findall(
            r'([a-zA-Z_:][a-zA-Z0-9_:\-]*)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|([^\s>]+))',
            tag,
            flags=re.IGNORECASE,
        ):
            value = double_quoted or single_quoted or bare_value
            attributes[str(key).lower()] = value
        if attributes:
            yield attributes


def normalize_remote_url(candidate_url: str, page_url: str) -> str:
    if not candidate_url:
        return ""
    normalized_url = candidate_url.strip()
    if not normalized_url:
        return ""
    parsed = urlparse(normalized_url)
    if parsed.scheme in {"http", "https"}:
        return normalized_url
    return urljoin(page_url, normalized_url)


def fetch_origin_image_fallback(page_url: str) -> str:
    origin_url = derive_origin_url(page_url)
    if not origin_url:
        return ""
    try:
        request = Request(origin_url, headers={"User-Agent": "UniteBot/1.0"})
        with urlopen(request, timeout=3) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text/html" not in content_type:
                return ""
            html = response.read(32768).decode("utf-8", errors="ignore")
    except Exception:
        return ""
    image_url = (
        extract_meta_content(html, "og:image")
        or extract_meta_content(html, "og:image:secure_url")
        or extract_meta_content(html, "og:image:url")
        or extract_meta_content(html, "twitter:image")
        or extract_meta_content(html, "twitter:image:src")
        or extract_meta_content(html, "image")
        or ""
    )
    return normalize_remote_url(image_url, origin_url)


def derive_origin_url(page_url: str) -> str:
    parsed = urlparse(str(page_url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    return f"{parsed.scheme}://{parsed.netloc}/"


def validate_media_url(media_url: str, media_type: str) -> bool:
    lower = media_url.lower()
    image_ext = (".png", ".jpg", ".jpeg", ".webp", ".gif")
    video_ext = (".mp4", ".webm", ".mov")
    if media_type == "image":
        return lower.endswith(image_ext)
    if media_type == "video":
        return lower.endswith(video_ext)
    return False
