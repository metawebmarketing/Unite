import type { FeedItem } from "../api/feed";

interface CachedFeedPage {
  items: FeedItem[];
  nextCursor: string | null;
  hasMore: boolean;
  cachedAt: number;
}

const FEED_CACHE_PREFIX = "unite:feed-cache:";
const FEED_CACHE_TTL_MS = 60_000;

export function readCachedFeed(cacheKey: string): CachedFeedPage | null {
  try {
    const raw = localStorage.getItem(`${FEED_CACHE_PREFIX}${cacheKey}`);
    if (!raw) {
      return null;
    }
    const parsed = JSON.parse(raw) as CachedFeedPage;
    if (Date.now() - parsed.cachedAt > FEED_CACHE_TTL_MS) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function writeCachedFeed(cacheKey: string, payload: Omit<CachedFeedPage, "cachedAt">): void {
  try {
    localStorage.setItem(
      `${FEED_CACHE_PREFIX}${cacheKey}`,
      JSON.stringify({
        ...payload,
        cachedAt: Date.now(),
      } satisfies CachedFeedPage),
    );
  } catch {
    // ignore quota/storage errors in best-effort cache
  }
}
