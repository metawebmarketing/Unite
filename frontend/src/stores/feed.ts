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
  blockedAuthorIds: number[];
  pendingActionKeys: string[];
}

interface LoadFeedOptions {
  force?: boolean;
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
    blockedAuthorIds: [],
    pendingActionKeys: [],
  }),
  actions: {
    isActionPending(key: string): boolean {
      return this.pendingActionKeys.includes(key);
    },
    beginAction(key: string) {
      if (this.pendingActionKeys.includes(key)) {
        return;
      }
      this.pendingActionKeys = [...this.pendingActionKeys, key];
    },
    endAction(key: string) {
      this.pendingActionKeys = this.pendingActionKeys.filter((value) => value !== key);
    },
    hydrateBlockedUsers() {
      if (typeof window === "undefined") {
        return;
      }
      try {
        const raw = window.localStorage.getItem("unite.blockedAuthorIds");
        if (!raw) {
          this.blockedAuthorIds = [];
          return;
        }
        const parsed = JSON.parse(raw);
        if (Array.isArray(parsed)) {
          this.blockedAuthorIds = parsed
            .map((value) => Number(value))
            .filter((value) => Number.isInteger(value) && value > 0);
        } else {
          this.blockedAuthorIds = [];
        }
      } catch {
        this.blockedAuthorIds = [];
      }
    },
    persistBlockedUsers() {
      if (typeof window === "undefined") {
        return;
      }
      window.localStorage.setItem("unite.blockedAuthorIds", JSON.stringify(this.blockedAuthorIds));
    },
    blockAuthor(authorId: number) {
      if (!Number.isInteger(authorId) || authorId <= 0 || this.blockedAuthorIds.includes(authorId)) {
        return;
      }
      this.blockedAuthorIds = [...this.blockedAuthorIds, authorId];
      this.persistBlockedUsers();
    },
    isAuthorBlocked(authorId: number): boolean {
      return this.blockedAuthorIds.includes(authorId);
    },
    buildFeedCacheKey(): string {
      return `${this.mode}:${this.interestTag || "none"}`;
    },
    async loadConfig() {
      this.config = await fetchFeedConfig();
    },
    async loadFeed(reset = true, options?: LoadFeedOptions) {
      if (this.isLoading) {
        if (!(options?.force && reset)) {
          return;
        }
        // Wait for the in-flight request so forced refresh cannot be skipped.
        while (this.isLoading) {
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
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
      const actionKey = `like:${postId}`;
      if (this.isActionPending(actionKey)) {
        return;
      }
      this.beginAction(actionKey);
      const target = this.items.find((item) => item.item_type === "post" && item.data.id === postId);
      if (!target) {
        this.endAction(actionKey);
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
      } finally {
        this.endAction(actionKey);
      }
    },
    async toggleReaction(postId: number, action: "repost" | "bookmark") {
      const actionKey = `${action}:${postId}`;
      if (this.isActionPending(actionKey)) {
        return;
      }
      this.beginAction(actionKey);
      const target = this.items.find((item) => item.item_type === "post" && item.data.id === postId);
      if (!target) {
        this.endAction(actionKey);
        return;
      }
      const counts = target.data.interaction_counts ?? { like: 0, reply: 0, repost: 0, quote: 0 };
      const isRepost = action === "repost";
      const isBookmark = action === "bookmark";
      const previousCount = isRepost ? counts.repost : 0;
      const previousBookmarked = Boolean(target.data.has_bookmarked);
      if (isRepost) {
        target.data.interaction_counts = {
          ...counts,
          repost: previousCount > 0 ? Math.max(0, previousCount - 1) : previousCount + 1,
        };
      }
      if (isBookmark) {
        target.data.has_bookmarked = !previousBookmarked;
      }
      try {
        await reactToPost(postId, { action });
      } catch {
        if (!navigator.onLine) {
          await enqueueReactPost(postId, { action });
        } else {
          if (isRepost) {
            target.data.interaction_counts = counts;
          }
          if (isBookmark) {
            target.data.has_bookmarked = previousBookmarked;
          }
        }
      } finally {
        this.endAction(actionKey);
      }
    },
    async replyToPost(postId: number, content: string) {
      const actionKey = `reply:${postId}`;
      if (this.isActionPending(actionKey)) {
        return;
      }
      const trimmed = content.trim();
      if (!trimmed) {
        return;
      }
      this.beginAction(actionKey);
      const target = this.items.find((item) => item.item_type === "post" && item.data.id === postId);
      if (target) {
        const counts = target.data.interaction_counts ?? { like: 0, reply: 0, repost: 0, quote: 0 };
        target.data.interaction_counts = { ...counts, reply: counts.reply + 1 };
      }
      try {
        await reactToPost(postId, { action: "reply", content: trimmed });
      } catch {
        // Ignore local rollback to avoid jumping counts during temporary failures.
      } finally {
        this.endAction(actionKey);
      }
    },
    async flushQueuedActions() {
      await flushOfflineQueue();
      await this.loadFeed(true);
    },
  },
});
