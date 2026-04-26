from celery import shared_task
from django.utils import timezone

from apps.posts.models import IdempotencyRecord, LinkPreviewCache


@shared_task
def cleanup_expired_post_caches() -> dict:
    now = timezone.now()
    expired_idempotency = IdempotencyRecord.objects.filter(expires_at__lte=now).delete()[0]
    expired_link_previews = LinkPreviewCache.objects.filter(expires_at__lte=now).delete()[0]
    return {
        "status": "ok",
        "expired_idempotency_deleted": expired_idempotency,
        "expired_link_previews_deleted": expired_link_previews,
    }
