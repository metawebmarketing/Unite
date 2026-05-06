import json
import os
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from django.conf import settings


@lru_cache(maxsize=4)
def _resolve_media_binary(binary_name: str) -> str:
    settings_key = f"UNITE_{binary_name.upper()}_PATH"
    configured_path = str(getattr(settings, settings_key, "") or "").strip()
    if configured_path and Path(configured_path).exists():
        return configured_path
    on_path = shutil.which(binary_name)
    if on_path:
        return on_path
    local_app_data = str(os.environ.get("LOCALAPPDATA", "") or "").strip()
    if local_app_data:
        winget_packages_dir = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
        if winget_packages_dir.exists():
            for package_dir in sorted(winget_packages_dir.glob("Gyan.FFmpeg*"), reverse=True):
                candidate = package_dir / "ffmpeg-8.1.1-full_build" / "bin" / f"{binary_name}.exe"
                if candidate.exists():
                    return str(candidate)
                matches = list(package_dir.rglob(f"{binary_name}.exe"))
                if matches:
                    return str(matches[0])
    return binary_name


def _run_ffmpeg(args: list[str]) -> None:
    try:
        subprocess.run(
            [_resolve_media_binary("ffmpeg"), *args[1:]],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg is not installed or not available on PATH.") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr or "ffmpeg processing failed.") from exc


def transcode_video_to_mp4(input_path: str, output_path: str) -> None:
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "28",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-movflags",
            "+faststart",
            output_path,
        ]
    )


def generate_video_thumbnail(input_path: str, output_path: str) -> None:
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-vf",
            "thumbnail",
            "-frames:v",
            "1",
            output_path,
        ]
    )


def transcode_video_to_hls(input_path: str, output_manifest_path: str, output_segments_dir: str) -> None:
    os.makedirs(output_segments_dir, exist_ok=True)
    segment_pattern = str(Path(output_segments_dir) / "segment-%03d.ts")
    _run_ffmpeg(
        [
            "ffmpeg",
            "-y",
            "-i",
            input_path,
            "-c",
            "copy",
            "-start_number",
            "0",
            "-hls_time",
            "4",
            "-hls_list_size",
            "0",
            "-hls_segment_filename",
            segment_pattern,
            "-f",
            "hls",
            output_manifest_path,
        ]
    )


def probe_video_duration_seconds(input_path: str) -> float:
    try:
        result = subprocess.run(
            [
                _resolve_media_binary("ffprobe"),
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                input_path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads(str(result.stdout or "{}"))
        format_duration = str((payload.get("format") or {}).get("duration") or "").strip()
        if format_duration:
            return max(0.0, float(format_duration))
        for stream in payload.get("streams") or []:
            stream_duration = str((stream or {}).get("duration") or "").strip()
            if stream_duration:
                return max(0.0, float(stream_duration))
    except FileNotFoundError as exc:
        # Fallback for environments where ffmpeg exists but ffprobe is unavailable.
        try:
            fallback = subprocess.run(
                [_resolve_media_binary("ffmpeg"), "-i", input_path],
                check=False,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as fallback_exc:
            raise RuntimeError("ffprobe/ffmpeg is not installed or not available on PATH.") from fallback_exc
        duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", str(fallback.stderr or ""))
        if not duration_match:
            raise RuntimeError("Unable to determine video duration.")
        hours = float(duration_match.group(1))
        minutes = float(duration_match.group(2))
        seconds = float(duration_match.group(3))
        return max(0.0, hours * 3600 + minutes * 60 + seconds)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(exc.stderr or "ffprobe failed to inspect video.") from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError("Unable to determine video duration.") from exc
    raise RuntimeError("Unable to determine video duration.")
