# Performance Budgets

This document defines regression budgets for the integrated optimization rollout.

## Backend Query Budgets

- `GET /api/v1/feed/?mode=both&page_size=6`: <= 25 SQL queries on cold cache.
- `GET /api/v1/posts/{id}` (detail + replies): keep under existing baseline after ranking policy changes.
- `GET /api/v1/posts/user/{id}` (full profile): no hard limit truncation, but query count must remain stable via `select_related`/`prefetch_related`.

## Feed Candidate Policy Defaults

- `UNITE_FEED_FRESHNESS_WINDOW_HOURS=168`
- `UNITE_FEED_INTEREST_FRESHNESS_WINDOW_HOURS=336`
- `UNITE_FEED_MAX_CANDIDATES=250`
- `UNITE_FEED_MIN_RANK_SCORE=-250`

## API Cache Defaults

- Feed response cache TTL: `UNITE_FEED_CACHE_TTL_SECONDS=30`
- Shared cache backend toggle:
  - `UNITE_CACHE_BACKEND=locmem` (default)
  - `UNITE_CACHE_BACKEND=redis` with `UNITE_CACHE_REDIS_URL`

## Frontend Budgets

- Next-page prefetch should not trigger duplicate requests for the same cursor.
- Feed item rendering should use stable keys and precomputed metadata to avoid excess re-renders.
- Cached feed payload must invalidate on session or policy-version mismatch.
