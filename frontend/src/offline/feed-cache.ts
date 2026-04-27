import type { FeedItem } from "../api/feed";

interface CachedFeedPage {
  items: FeedItem[];
  nextCursor: string | null;
  hasMore: boolean;
  cachedAt: number;
}

const FEED_CACHE_PREFIX = "unite:feed-cache:";
const FEED_CACHE_TTL_MS = 60_000;
const FEED_SW_CACHE_NAMES = ["unite-feed-v1", "unite-feed-v2"];

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

export function clearLocalFeedCache(): void {
  try {
    const keysToDelete: string[] = [];
    for (let index = 0; index < localStorage.length; index += 1) {
      const key = localStorage.key(index);
      if (key && key.startsWith(FEED_CACHE_PREFIX)) {
        keysToDelete.push(key);
      }
    }
    for (const key of keysToDelete) {
      localStorage.removeItem(key);
    }
  } catch {
    // ignore storage access errors
  }
}

export async function clearServiceWorkerFeedCache(): Promise<void> {
  try {
    if (!("caches" in window)) {
      return;
    }
    for (const cacheName of FEED_SW_CACHE_NAMES) {
      await window.caches.delete(cacheName);
    }
  } catch {
    // ignore cache storage errors
  }
}

export async function clearAllFeedCaches(): Promise<void> {
  clearLocalFeedCache();
  await clearServiceWorkerFeedCache();
}
