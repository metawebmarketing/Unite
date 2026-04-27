from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
import re
from typing import Protocol

from django.conf import settings


@dataclass(frozen=True)
class SentimentResult:
    label: str
    score: float
    confidence: float
    needs_rescore: bool = False


class SentimentProvider(Protocol):
    def analyze_text(self, text: str) -> SentimentResult:
        ...


class NeutralRescoreSentimentProvider:
    """Returns neutral and signals that content should be rescored later."""

    def analyze_text(self, text: str) -> SentimentResult:
        _ = text
        return SentimentResult(label="neutral", score=0.0, confidence=0.0, needs_rescore=True)


class CardiffLocalSentimentProvider:
    HOSTILE_TOKENS = {
        "idiot",
        "moron",
        "stupid",
        "dumb",
        "loser",
        "pathetic",
        "worthless",
        "incompetent",
        "liar",
        "fraud",
        "bitch",
        "asshole",
        "shit",
        "fuck",
    }
    HOSTILE_PHRASES = {
        "go die",
        "kill yourself",
        "shut up",
        "you are an idiot",
        "you're an idiot",
        "you are stupid",
        "you're stupid",
    }

    def __init__(self, model_name: str, model_path: str, local_files_only: bool = False):
        self.model_name = model_name
        self.model_path = model_path
        self.local_files_only = bool(local_files_only)
        self._pipeline = None

    def _get_pipeline(self):
        if self._pipeline is not None:
            return self._pipeline
        if self.local_files_only:
            os.environ["HF_HUB_OFFLINE"] = "1"
            os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from transformers import pipeline  # type: ignore

        self._pipeline = pipeline(
            "sentiment-analysis",
            model=self.model_path or self.model_name,
            tokenizer=self.model_path or self.model_name,
            local_files_only=self.local_files_only,
        )
        return self._pipeline

    def _is_hostile_text(self, text: str) -> bool:
        lowered = text.lower()
        if any(phrase in lowered for phrase in self.HOSTILE_PHRASES):
            return True
        tokens = [token.strip(".,!?;:\"'()[]{}") for token in lowered.split()]
        if any(token in self.HOSTILE_TOKENS for token in tokens):
            return True
        return bool(
            re.search(
                r"\byou(?:'re| are)\s+(?:an?\s+)?(idiot|moron|stupid|dumb|liar|fraud|pathetic|worthless)\b",
                lowered,
            )
        )

    def analyze_text(self, text: str) -> SentimentResult:
        normalized = (text or "").strip()
        if not normalized:
            return SentimentResult(label="neutral", score=0.0, confidence=0.5)
        predictor = self._get_pipeline()
        prediction = predictor(normalized, truncation=True, max_length=512)[0]
        raw_label = str(prediction.get("label", "neutral")).strip().lower()
        confidence = float(prediction.get("score", 0.5))
        if "positive" in raw_label:
            return SentimentResult(label="positive", score=round(confidence, 4), confidence=confidence)
        if "negative" in raw_label:
            # Keep productive disagreement neutral; reserve negative for hostility/insults.
            if not self._is_hostile_text(normalized):
                return SentimentResult(label="neutral", score=0.0, confidence=confidence)
            return SentimentResult(label="negative", score=round(-confidence, 4), confidence=confidence)
        return SentimentResult(label="neutral", score=0.0, confidence=confidence)


@lru_cache(maxsize=1)
def get_sentiment_provider() -> SentimentProvider:
    provider_name = str(getattr(settings, "UNITE_SENTIMENT_RANKING_PROVIDER", "cardiff_local")).strip().lower()
    model_name = str(
        getattr(settings, "UNITE_SENTIMENT_MODEL_NAME", "cardiffnlp/twitter-xlm-roberta-base-sentiment")
    ).strip()
    model_path = str(getattr(settings, "UNITE_SENTIMENT_MODEL_PATH", "")).strip() or model_name
    local_files_only = bool(getattr(settings, "UNITE_SENTIMENT_LOCAL_FILES_ONLY", False))
    if provider_name == "cardiff_local":
        try:
            return CardiffLocalSentimentProvider(
                model_name=model_name,
                model_path=model_path,
                local_files_only=local_files_only,
            )
        except Exception:
            return NeutralRescoreSentimentProvider()
    return NeutralRescoreSentimentProvider()


def score_sentiment_text(text: str) -> SentimentResult:
    provider = get_sentiment_provider()
    try:
        return provider.analyze_text(text=text)
    except Exception:
        return SentimentResult(label="neutral", score=0.0, confidence=0.0, needs_rescore=True)
