import { defineStore } from "pinia";

import {
  createDMThread,
  fetchDMThreads,
  fetchThreadMessages,
  sendThreadMessage,
  type CreateDMMessageInput,
  type DMMessageRecord,
  type DMThreadListItem,
} from "../api/messages";
import { fetchProfile } from "../api/profile";

interface MessagesState {
  threads: DMThreadListItem[];
  threadsNextCursor: string | null;
  threadsHasMore: boolean;
  isLoadingThreads: boolean;
  messagesByThreadId: Record<number, DMMessageRecord[]>;
  messageNextCursorByThreadId: Record<number, string | null>;
  messageHasMoreByThreadId: Record<number, boolean>;
  messageLoadingByThreadId: Record<number, boolean>;
  currentUserId: number | null;
}

export const useMessagesStore = defineStore("messages", {
  state: (): MessagesState => ({
    threads: [],
    threadsNextCursor: null,
    threadsHasMore: true,
    isLoadingThreads: false,
    messagesByThreadId: {},
    messageNextCursorByThreadId: {},
    messageHasMoreByThreadId: {},
    messageLoadingByThreadId: {},
    currentUserId: null,
  }),
  actions: {
    async ensureCurrentUserId() {
      if (this.currentUserId) {
        return this.currentUserId;
      }
      const profile = await fetchProfile();
      this.currentUserId = profile.user_id;
      return this.currentUserId;
    },
    async loadThreads(
      reset = false,
      filters: { search?: string; fromProfile?: string; afterDate?: string; beforeDate?: string } = {},
    ) {
      if (this.isLoadingThreads) {
        return;
      }
      if (!reset && !this.threadsHasMore) {
        return;
      }
      this.isLoadingThreads = true;
      try {
        const page = await fetchDMThreads({
          cursor: reset ? null : this.threadsNextCursor,
          search: filters.search,
          fromProfile: filters.fromProfile,
          afterDate: filters.afterDate,
          beforeDate: filters.beforeDate,
          pageSize: 20,
        });
        this.threads = reset ? page.items : [...this.threads, ...page.items];
        this.threadsNextCursor = page.next_cursor;
        this.threadsHasMore = page.has_more;
      } finally {
        this.isLoadingThreads = false;
      }
    },
    async ensureThread(recipientId: number): Promise<number> {
      const response = await createDMThread({ recipient_id: recipientId });
      return response.thread_id;
    },
    async loadThreadMessages(threadId: number, reset = false) {
      if (this.messageLoadingByThreadId[threadId]) {
        return;
      }
      if (!reset && this.messageHasMoreByThreadId[threadId] === false) {
        return;
      }
      this.messageLoadingByThreadId = { ...this.messageLoadingByThreadId, [threadId]: true };
      try {
        const page = await fetchThreadMessages(threadId, {
          cursor: reset ? null : this.messageNextCursorByThreadId[threadId],
          pageSize: 30,
        });
        const previous = reset ? [] : this.messagesByThreadId[threadId] || [];
        this.messagesByThreadId = {
          ...this.messagesByThreadId,
          [threadId]: [...previous, ...page.items],
        };
        this.messageNextCursorByThreadId = {
          ...this.messageNextCursorByThreadId,
          [threadId]: page.next_cursor,
        };
        this.messageHasMoreByThreadId = {
          ...this.messageHasMoreByThreadId,
          [threadId]: page.has_more,
        };
      } finally {
        this.messageLoadingByThreadId = { ...this.messageLoadingByThreadId, [threadId]: false };
      }
    },
    async sendMessage(threadId: number, payload: CreateDMMessageInput): Promise<DMMessageRecord> {
      const idempotencyKey = `dm-${threadId}-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
      const message = await sendThreadMessage(threadId, payload, { idempotencyKey });
      const previous = this.messagesByThreadId[threadId] || [];
      this.messagesByThreadId = {
        ...this.messagesByThreadId,
        [threadId]: [message, ...previous],
      };
      this.threads = this.threads.map((thread) =>
        thread.thread_id === threadId
          ? {
              ...thread,
              latest_message_preview: message.content.slice(0, 160),
              latest_message_at: message.created_at,
            }
          : thread,
      );
      return message;
    },
  },
});
