import re
from datetime import timedelta
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from apps.posts.models import LinkPreviewCache


def build_link_preview(url: str) -> dict:
    if not url:
        return {}
    cached = LinkPreviewCache.objects.filter(url=url, expires_at__gt=timezone.now()).first()
    if cached:
        return {
            "url": url,
            "host": cached.host,
            "title": cached.title,
            "description": cached.description,
            "source": cached.source,
        }

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
        "source": "fallback",
    }
    if bool(getattr(settings, "UNITE_ENABLE_REMOTE_LINK_FETCH", False)):
        preview = fetch_remote_link_metadata(url=url, fallback=preview)

    ttl_seconds = int(getattr(settings, "UNITE_LINK_PREVIEW_TTL_SECONDS", 86400))
    LinkPreviewCache.objects.update_or_create(
        url=url,
        defaults={
            "host": preview["host"],
            "title": preview["title"][:255],
            "description": preview["description"][:512],
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
            html = response.read(8192).decode("utf-8", errors="ignore")
    except Exception:
        return fallback

    title_match = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
    description_match = re.search(
        r'<meta\s+name=["\']description["\']\s+content=["\'](.*?)["\']',
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    title = title_match.group(1).strip() if title_match else fallback["title"]
    description = description_match.group(1).strip() if description_match else fallback["description"]
    return {
        **fallback,
        "title": title[:255],
        "description": description[:512],
        "source": "remote",
    }


def validate_media_url(media_url: str, media_type: str) -> bool:
    lower = media_url.lower()
    image_ext = (".png", ".jpg", ".jpeg", ".webp", ".gif")
    video_ext = (".mp4", ".webm", ".mov")
    if media_type == "image":
        return lower.endswith(image_ext)
    if media_type == "video":
        return lower.endswith(video_ext)
    return False
