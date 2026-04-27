from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

CORPUS_PATH = Path(__file__).resolve().parent / "data" / "demo_posts_10000.json"


@lru_cache(maxsize=1)
def load_demo_post_corpus() -> list[dict]:
    if not CORPUS_PATH.exists():
        return []
    with CORPUS_PATH.open("r", encoding="utf-8") as handle:
        parsed = json.load(handle)
    if not isinstance(parsed, list):
        return []
    cleaned: list[dict] = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        interest_tags = item.get("interest_tags", [])
        if not isinstance(interest_tags, list):
            interest_tags = []
        cleaned.append(
            {
                "content": content,
                "interest_tags": [str(tag).strip().lower() for tag in interest_tags if str(tag).strip()],
                "link_url": str(item.get("link_url", "")).strip(),
                "link_preview": item.get("link_preview", {}) if isinstance(item.get("link_preview", {}), dict) else {},
                "reply_positive": str(item.get("reply_positive", "")).strip(),
                "reply_negative": str(item.get("reply_negative", "")).strip(),
                "quote_commentary": str(item.get("quote_commentary", "")).strip(),
            }
        )
    return cleaned
