from __future__ import annotations

import json
import random
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus, urlparse

CORPUS_PATH = Path(__file__).resolve().parent / "data" / "demo_posts_10000.json"

SEARCH_ENGINE_LINK_PATTERNS = [
    "https://www.google.com/search?q={query}",
    "https://www.bing.com/search?q={query}",
    "https://search.yahoo.com/search?p={query}",
    "https://duckduckgo.com/?q={query}",
    "https://www.ecosia.org/search?q={query}",
]


def build_seed_mention_text(content: str) -> str:
    trimmed = str(content).strip()
    if not trimmed:
        return "Highlighting this update for @team."
    short = trimmed[:100].rstrip()
    return f"Highlighting this update for @team: {short}"


def map_to_search_engine_link(*, seed_text: str, source_url: str, rng: random.Random) -> tuple[str, str]:
    parsed = urlparse(source_url)
    path_tokens = [token for token in parsed.path.split("/") if token]
    slug_tokens = [token.replace("-", " ").replace("_", " ").strip() for token in path_tokens]
    query_text = " ".join(token for token in slug_tokens if token) or seed_text or "community updates"
    query = quote_plus(query_text[:120])
    pattern = rng.choice(SEARCH_ENGINE_LINK_PATTERNS)
    mapped_url = pattern.format(query=query)
    mapped_host = urlparse(mapped_url).netloc.lower()
    return mapped_url, mapped_host


@lru_cache(maxsize=1)
def load_demo_post_corpus() -> list[dict]:
    if not CORPUS_PATH.exists():
        return []
    with CORPUS_PATH.open("r", encoding="utf-8") as handle:
        parsed = json.load(handle)
    if not isinstance(parsed, list):
        return []
    cleaned: list[dict] = []
    rng = random.Random(20260428)
    for item in parsed:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        interest_tags = item.get("interest_tags", [])
        if not isinstance(interest_tags, list):
            interest_tags = []
        link_url = str(item.get("link_url", "")).strip()
        link_preview = item.get("link_preview", {}) if isinstance(item.get("link_preview", {}), dict) else {}
        parsed_link = urlparse(link_url) if link_url else None
        host = str(getattr(parsed_link, "netloc", "") or "").lower()
        if link_url and ("example.com" in host or "example.local" in host):
            mapped_url, mapped_host = map_to_search_engine_link(
                seed_text=content,
                source_url=link_url,
                rng=rng,
            )
            link_url = mapped_url
            link_preview = {
                **link_preview,
                "url": mapped_url,
                "host": mapped_host,
            }
        cleaned.append(
            {
                "content": content,
                "interest_tags": [str(tag).strip().lower() for tag in interest_tags if str(tag).strip()],
                "link_url": link_url,
                "link_preview": link_preview,
                "reply_positive": str(item.get("reply_positive", "")).strip(),
                "reply_negative": str(item.get("reply_negative", "")).strip(),
                "quote_commentary": str(item.get("quote_commentary", "")).strip(),
                "mention_text": build_seed_mention_text(content),
            }
        )
    return cleaned
