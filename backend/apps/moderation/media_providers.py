from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
import re
from typing import Protocol

from django.conf import settings


@dataclass(frozen=True)
class MediaAnalysisResult:
    actionable_terms: list[str]
    category_scores: dict[str, float]
    metadata: dict[str, object]


class MediaProvider(Protocol):
    def analyze_image(self, image_path: str) -> MediaAnalysisResult:
        ...

    def analyze_video(self, video_path: str) -> MediaAnalysisResult:
        ...


def _normalize_terms(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = str(value).strip().lower()
        if not token:
            continue
        compact = re.sub(r"[^a-z0-9_ -]+", " ", token)
        compact = re.sub(r"\s+", " ", compact).strip()
        if not compact or compact in seen:
            continue
        seen.add(compact)
        normalized.append(compact)
    return normalized


def _filename_terms(path: str) -> list[str]:
    basename = os.path.basename(str(path or "")).strip().lower()
    if not basename:
        return []
    tokens = re.split(r"[^a-z0-9]+", basename)
    return _normalize_terms([token for token in tokens if len(token) >= 3])


class FallbackMediaProvider:
    def analyze_image(self, image_path: str) -> MediaAnalysisResult:
        terms = _filename_terms(image_path)
        return MediaAnalysisResult(
            actionable_terms=terms,
            category_scores={},
            metadata={"provider": "fallback", "model": "filename-heuristic", "mode": "image"},
        )

    def analyze_video(self, video_path: str) -> MediaAnalysisResult:
        terms = _filename_terms(video_path)
        return MediaAnalysisResult(
            actionable_terms=terms,
            category_scores={},
            metadata={"provider": "fallback", "model": "filename-heuristic", "mode": "video"},
        )


class Siglip2ImageProvider(FallbackMediaProvider):
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._pipeline = None

    def _get_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        from transformers import pipeline  # type: ignore

        self._pipeline = pipeline(
            "zero-shot-image-classification",
            model=self.model_name,
            local_files_only=bool(getattr(settings, "UNITE_MEDIA_LOCAL_FILES_ONLY", False)),
        )
        return self._pipeline

    def analyze_image(self, image_path: str) -> MediaAnalysisResult:
        if not bool(getattr(settings, "UNITE_MEDIA_ENABLE_MODEL_INFERENCE", True)):
            return super().analyze_image(image_path)
        labels = list(getattr(settings, "UNITE_MEDIA_IMAGE_CANDIDATE_LABELS", []))
        if not labels:
            return super().analyze_image(image_path)
        try:
            predictor = self._get_pipeline()
            raw_predictions = predictor(image_path, candidate_labels=labels)
            terms: list[str] = []
            scores: dict[str, float] = {}
            for prediction in raw_predictions[:20]:
                label = str(prediction.get("label", "")).strip().lower()
                if not label:
                    continue
                score = float(prediction.get("score", 0.0) or 0.0)
                terms.append(label)
                scores[label] = max(scores.get(label, 0.0), score)
            return MediaAnalysisResult(
                actionable_terms=_normalize_terms(terms),
                category_scores=scores,
                metadata={"provider": "siglip2", "model": self.model_name, "mode": "image"},
            )
        except Exception:
            return super().analyze_image(image_path)


class VideoMaeVideoProvider(FallbackMediaProvider):
    def __init__(self, model_name: str):
        self.model_name = model_name
        self._pipeline = None

    def _get_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        from transformers import pipeline  # type: ignore

        self._pipeline = pipeline(
            "video-classification",
            model=self.model_name,
            local_files_only=bool(getattr(settings, "UNITE_MEDIA_LOCAL_FILES_ONLY", False)),
        )
        return self._pipeline

    def analyze_video(self, video_path: str) -> MediaAnalysisResult:
        if not bool(getattr(settings, "UNITE_MEDIA_ENABLE_MODEL_INFERENCE", True)):
            return super().analyze_video(video_path)
        try:
            predictor = self._get_pipeline()
            raw_predictions = predictor(video_path)
            terms: list[str] = []
            scores: dict[str, float] = {}
            for prediction in raw_predictions[:20]:
                label = str(prediction.get("label", "")).strip().lower()
                if not label:
                    continue
                score = float(prediction.get("score", 0.0) or 0.0)
                terms.append(label)
                scores[label] = max(scores.get(label, 0.0), score)
            return MediaAnalysisResult(
                actionable_terms=_normalize_terms(terms),
                category_scores=scores,
                metadata={"provider": "videomae", "model": self.model_name, "mode": "video"},
            )
        except Exception:
            return super().analyze_video(video_path)


@lru_cache(maxsize=1)
def _build_providers() -> dict[str, MediaProvider]:
    image_provider_name = str(getattr(settings, "UNITE_MEDIA_IMAGE_PROVIDER", "siglip2")).strip().lower()
    video_provider_name = str(getattr(settings, "UNITE_MEDIA_VIDEO_PROVIDER", "videomae")).strip().lower()
    image_model_name = str(
        getattr(settings, "UNITE_MEDIA_IMAGE_MODEL_NAME", "google/siglip2-base-patch16-224")
    ).strip()
    video_model_name = str(
        getattr(settings, "UNITE_MEDIA_VIDEO_MODEL_NAME", "MCG-NJU/videomae-base-finetuned-kinetics")
    ).strip()
    providers: dict[str, MediaProvider] = {
        "image": FallbackMediaProvider(),
        "video": FallbackMediaProvider(),
    }
    if image_provider_name == "siglip2":
        providers["image"] = Siglip2ImageProvider(image_model_name)
    if video_provider_name == "videomae":
        providers["video"] = VideoMaeVideoProvider(video_model_name)
    return providers


def get_media_provider(media_type: str) -> MediaProvider:
    normalized = str(media_type or "").strip().lower()
    providers = _build_providers()
    if normalized in providers:
        return providers[normalized]
    return FallbackMediaProvider()

