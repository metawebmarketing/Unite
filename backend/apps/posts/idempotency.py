import hashlib
import json
from datetime import timedelta

from django.utils import timezone
from django.db.models import F

from apps.posts.models import IdempotencyRecord

IDEMPOTENCY_TTL_SECONDS = 24 * 60 * 60


def hash_request_payload(payload: dict) -> str:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def load_idempotent_response(
    *,
    user_id: int,
    endpoint: str,
    key: str,
    request_hash: str,
) -> tuple[dict | None, int | None, bool]:
    record = (
        IdempotencyRecord.objects.filter(
            user_id=user_id,
            endpoint=endpoint,
            key=key,
            expires_at__gt=timezone.now(),
        )
        .order_by("-created_at")
        .first()
    )
    if not record:
        return None, None, False
    if record.request_hash != request_hash:
        IdempotencyRecord.objects.filter(id=record.id).update(conflict_count=F("conflict_count") + 1)
        return {"detail": "Idempotency key reused with different payload."}, 409, True
    IdempotencyRecord.objects.filter(id=record.id).update(
        replay_count=F("replay_count") + 1,
        last_replayed_at=timezone.now(),
    )
    return record.response_body, int(record.status_code), True


def save_idempotent_response(
    *,
    user_id: int,
    endpoint: str,
    key: str,
    request_hash: str,
    status_code: int,
    response_body: dict,
) -> None:
    IdempotencyRecord.objects.update_or_create(
        user_id=user_id,
        endpoint=endpoint,
        key=key,
        defaults={
            "request_hash": request_hash,
            "status_code": int(status_code),
            "response_body": response_body,
            "expires_at": timezone.now() + timedelta(seconds=IDEMPOTENCY_TTL_SECONDS),
        },
    )
