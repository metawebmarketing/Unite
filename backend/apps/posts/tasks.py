import os
import tempfile
from urllib.parse import urlparse

from celery import shared_task
from django.conf import settings
from django.core.files.base import File
from django.utils import timezone

from apps.posts.models import IdempotencyRecord, LinkPreviewCache, MediaAttachment, UploadedMediaAsset
from apps.posts.storage import MediaStorageConfigError, build_media_url_from_saved_name, get_media_storage_for_mode
from apps.posts.video_processing import generate_video_thumbnail, transcode_video_to_hls, transcode_video_to_mp4


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


@shared_task
def process_uploaded_video(
    saved_name: str,
    thumbnail_saved_name: str,
    hls_manifest_saved_name: str,
    storage_mode: str = "local",
    uploaded_asset_id: int | None = None,
) -> dict:
    asset = None
    if uploaded_asset_id:
        asset = UploadedMediaAsset.objects.filter(id=uploaded_asset_id).first()
    try:
        storage = get_media_storage_for_mode(storage_mode)
    except MediaStorageConfigError as exc:
        if asset:
            asset.processing_status = UploadedMediaAsset.ProcessingStatus.FAILED
            asset.save(update_fields=["processing_status", "updated_at"])
            MediaAttachment.objects.filter(media_url=asset.media_url, media_type=MediaAttachment.MediaType.VIDEO).update(
                processing_status=UploadedMediaAsset.ProcessingStatus.FAILED
            )
        return {"status": "error", "detail": str(exc), "saved_name": saved_name}

    if not storage.exists(saved_name):
        if asset:
            asset.processing_status = UploadedMediaAsset.ProcessingStatus.FAILED
            asset.save(update_fields=["processing_status", "updated_at"])
            MediaAttachment.objects.filter(media_url=asset.media_url, media_type=MediaAttachment.MediaType.VIDEO).update(
                processing_status=UploadedMediaAsset.ProcessingStatus.FAILED
            )
        return {"status": "missing", "saved_name": saved_name}

    with tempfile.TemporaryDirectory(prefix="unite-video-") as temp_dir:
        input_path = os.path.join(temp_dir, "input.mp4")
        output_path = os.path.join(temp_dir, "optimized.mp4")
        thumb_path = os.path.join(temp_dir, "thumb.jpg")
        hls_dir = os.path.join(temp_dir, "hls")
        hls_manifest_path = os.path.join(hls_dir, "playlist.m3u8")

        with storage.open(saved_name, "rb") as source_stream:
            with open(input_path, "wb") as input_file:
                for chunk in source_stream.chunks():
                    input_file.write(chunk)

        try:
            transcode_video_to_mp4(input_path, output_path)
            generate_video_thumbnail(output_path, thumb_path)
            transcode_video_to_hls(output_path, hls_manifest_path, hls_dir)
        except RuntimeError as exc:
            if asset:
                asset.processing_status = UploadedMediaAsset.ProcessingStatus.FAILED
                asset.save(update_fields=["processing_status", "updated_at"])
                MediaAttachment.objects.filter(media_url=asset.media_url, media_type=MediaAttachment.MediaType.VIDEO).update(
                    processing_status=UploadedMediaAsset.ProcessingStatus.FAILED
                )
            return {"status": "error", "detail": str(exc), "saved_name": saved_name}

        if storage.exists(saved_name):
            storage.delete(saved_name)
        with open(output_path, "rb") as optimized_handle:
            storage.save(saved_name, File(optimized_handle, name=os.path.basename(saved_name)))

        if thumbnail_saved_name:
            if storage.exists(thumbnail_saved_name):
                storage.delete(thumbnail_saved_name)
            with open(thumb_path, "rb") as thumb_handle:
                storage.save(thumbnail_saved_name, File(thumb_handle, name=os.path.basename(thumbnail_saved_name)))

        if hls_manifest_saved_name:
            if storage.exists(hls_manifest_saved_name):
                storage.delete(hls_manifest_saved_name)
            with open(hls_manifest_path, "rb") as manifest_handle:
                storage.save(
                    hls_manifest_saved_name,
                    File(manifest_handle, name=os.path.basename(hls_manifest_saved_name)),
                )
            hls_prefix = str(os.path.dirname(hls_manifest_saved_name)).strip("/")
            for segment_name in sorted(os.listdir(hls_dir)):
                if not segment_name.endswith(".ts"):
                    continue
                segment_saved_name = f"{hls_prefix}/{segment_name}"
                local_segment_path = os.path.join(hls_dir, segment_name)
                if storage.exists(segment_saved_name):
                    storage.delete(segment_saved_name)
                with open(local_segment_path, "rb") as segment_handle:
                    storage.save(segment_saved_name, File(segment_handle, name=segment_name))

    if asset:
        asset.processing_status = UploadedMediaAsset.ProcessingStatus.READY
        asset.save(update_fields=["processing_status", "updated_at"])
        MediaAttachment.objects.filter(media_url=asset.media_url, media_type=MediaAttachment.MediaType.VIDEO).update(
            processing_status=UploadedMediaAsset.ProcessingStatus.READY,
            thumbnail_url=asset.thumbnail_url,
            hls_manifest_url=asset.hls_manifest_url,
            media_bytes=asset.media_bytes,
        )

    return {
        "status": "ok",
        "saved_name": saved_name,
        "thumbnail_saved_name": thumbnail_saved_name,
        "hls_manifest_saved_name": hls_manifest_saved_name,
    }


def _derive_saved_name_from_media_url(media_url: str) -> str:
    normalized_url = str(media_url or "").strip()
    if not normalized_url:
        return ""
    parsed = urlparse(normalized_url)
    path = str(parsed.path or normalized_url).strip()
    media_url_prefix = str(getattr(settings, "MEDIA_URL", "/media/") or "/media/")
    if media_url_prefix and path.startswith(media_url_prefix):
        return path[len(media_url_prefix) :].lstrip("/")
    return path.lstrip("/")


@shared_task
def repair_missing_video_thumbnail(media_url: str, uploaded_asset_id: int | None = None) -> dict:
    return repair_missing_video_thumbnail_now(media_url=media_url, uploaded_asset_id=uploaded_asset_id)


def repair_missing_video_thumbnail_now(media_url: str, uploaded_asset_id: int | None = None) -> dict:
    asset = None
    if uploaded_asset_id:
        asset = UploadedMediaAsset.objects.filter(
            id=uploaded_asset_id,
            media_type=MediaAttachment.MediaType.VIDEO,
        ).first()
    if asset is None:
        asset = UploadedMediaAsset.objects.filter(
            media_url=str(media_url or "").strip(),
            media_type=MediaAttachment.MediaType.VIDEO,
        ).first()
    media_url_token = str(getattr(asset, "media_url", "") or media_url).strip()
    if not media_url_token:
        return {"status": "missing_media_url"}
    storage_mode = str(getattr(asset, "storage_mode", "") or "local").strip().lower() or "local"
    try:
        storage = get_media_storage_for_mode(storage_mode)
    except MediaStorageConfigError as exc:
        return {"status": "error", "detail": str(exc), "media_url": media_url_token}

    source_saved_name = str(getattr(asset, "storage_saved_name", "") or "").strip()
    if not source_saved_name:
        source_saved_name = _derive_saved_name_from_media_url(media_url_token)
    if not source_saved_name or not storage.exists(source_saved_name):
        return {"status": "missing_source", "media_url": media_url_token}

    thumbnail_saved_name = str(getattr(asset, "thumbnail_saved_name", "") or "").strip()
    if not thumbnail_saved_name:
        source_root, _ = os.path.splitext(source_saved_name)
        thumbnail_saved_name = f"{source_root}.jpg"

    with tempfile.TemporaryDirectory(prefix="unite-video-thumb-repair-") as temp_dir:
        input_path = os.path.join(temp_dir, "input.mp4")
        thumb_path = os.path.join(temp_dir, "thumb.jpg")
        with storage.open(source_saved_name, "rb") as source_stream:
            with open(input_path, "wb") as input_file:
                for chunk in source_stream.chunks():
                    input_file.write(chunk)
        try:
            generate_video_thumbnail(input_path, thumb_path)
        except RuntimeError as exc:
            return {"status": "error", "detail": str(exc), "media_url": media_url_token}
        if storage.exists(thumbnail_saved_name):
            storage.delete(thumbnail_saved_name)
        with open(thumb_path, "rb") as thumb_handle:
            storage.save(thumbnail_saved_name, File(thumb_handle, name=os.path.basename(thumbnail_saved_name)))

    thumbnail_url = build_media_url_from_saved_name(thumbnail_saved_name, storage_mode=storage_mode)
    if asset:
        asset.thumbnail_saved_name = thumbnail_saved_name
        asset.thumbnail_url = thumbnail_url
        asset.save(update_fields=["thumbnail_saved_name", "thumbnail_url", "updated_at"])
    MediaAttachment.objects.filter(
        media_type=MediaAttachment.MediaType.VIDEO,
        media_url=media_url_token,
    ).update(thumbnail_url=thumbnail_url)
    return {
        "status": "ok",
        "media_url": media_url_token,
        "thumbnail_saved_name": thumbnail_saved_name,
        "thumbnail_url": thumbnail_url,
    }
