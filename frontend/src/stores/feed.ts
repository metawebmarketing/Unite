import { defineStore } from "pinia";
import axios from "axios";

import { fetchFeed, fetchFeedConfig, type FeedConfig, type FeedItem } from "../api/feed";
import { enqueueReactPost, flushOfflineQueue } from "../offline/action-queue";
import { readCachedFeed, writeCachedFeed } from "../offline/feed-cache";
import { reactToPost } from "../api/posts";

type FeedMode = "connections" | "suggestions" | "both" | "interest";

interface FeedState {
  mode: FeedMode;
  interestTag: string | null;
  items: FeedItem[];
  config: FeedConfig | null;
  isLoading: boolean;
  nextCursor: string | null;
  hasMore: boolean;
}

export const useFeedStore = defineStore("feed", {
  state: (): FeedState => ({
    mode: "both",
    interestTag: null,
    items: [],
    config: null,
    isLoading: false,
    nextCursor: null,
    hasMore: true,
  }),
  actions: {
    buildFeedCacheKey(): string {
      return `${this.mode}:${this.interestTag || "none"}`;
    },
    async loadConfig() {
      this.config = await fetchFeedConfig();
    },
    async loadFeed(reset = true) {
      if (this.isLoading) {
        return;
      }
      if (!reset && !this.hasMore) {
        return;
      }
      this.isLoading = true;
      let hasCachedFallback = false;
      try {
        if (reset) {
          const cached = readCachedFeed(this.buildFeedCacheKey());
          if (cached) {
            this.items = cached.items;
            this.nextCursor = cached.nextCursor;
            this.hasMore = cached.hasMore;
            hasCachedFallback = true;
          }
        }
        const cursor = reset ? null : this.nextCursor;
        const response = await fetchFeed(this.mode, cursor, this.interestTag);
        this.items = reset ? response.items : [...this.items, ...response.items];
        this.nextCursor = response.next_cursor;
        this.hasMore = response.has_more;
        if (reset) {
          writeCachedFeed(this.buildFeedCacheKey(), {
            items: this.items,
            nextCursor: this.nextCursor,
            hasMore: this.hasMore,
          });
        }
      } catch (error: unknown) {
        if (axios.isAxiosError(error) && Number(error.response?.status || 0) === 401) {
          this.hasMore = false;
          this.nextCursor = null;
        }
        if (!hasCachedFallback) {
          throw new Error("Unable to load feed.");
        }
      } finally {
        this.isLoading = false;
      }
    },
    async setMode(mode: FeedMode) {
      this.mode = mode;
      this.nextCursor = null;
      this.hasMore = true;
      await this.loadFeed(true);
    },
    async setInterestMode(tag: string) {
      this.interestTag = tag;
      this.mode = "interest";
      this.nextCursor = null;
      this.hasMore = true;
      await this.loadFeed(true);
    },
    async loadNextPage() {
      await this.loadFeed(false);
    },
    async toggleLike(postId: number) {
      const target = this.items.find((item) => item.item_type === "post" && item.data.id === postId);
      if (!target) {
        return;
      }
      const counts = target.data.interaction_counts ?? { like: 0, reply: 0, repost: 0, quote: 0 };
      const previousLiked = Boolean(target.data.has_liked);
      target.data.has_liked = !previousLiked;
      target.data.interaction_counts = {
        ...counts,
        like: previousLiked ? Math.max(0, counts.like - 1) : counts.like + 1,
      };
      try {
        await reactToPost(postId, { action: "like" });
      } catch {
        if (!navigator.onLine) {
          await enqueueReactPost(postId, { action: "like" });
        } else {
          target.data.has_liked = previousLiked;
          target.data.interaction_counts = counts;
        }
      }
    },
    async flushQueuedActions() {
      await flushOfflineQueue();
      await this.loadFeed(true);
    },
  },
});
