import { defineStore } from "pinia";

import { fetchNotifications, markAllNotificationsRead, type NotificationRecord } from "../api/notifications";
import type { InstallStatus } from "../api/install";
import { realtimeSocket, type RealtimeEvent } from "../services/realtime-socket";
import { useAuthStore } from "./auth";

interface NotificationsState {
  items: NotificationRecord[];
  unreadCount: number;
  nextCursor: string | null;
  hasMore: boolean;
  isLoading: boolean;
  isSocketConnected: boolean;
  installStatusRealtime: InstallStatus | null;
  profileGenerationStatus: string | null;
  initialized: boolean;
}

export const useNotificationsStore = defineStore("notifications", {
  state: (): NotificationsState => ({
    items: [],
    unreadCount: 0,
    nextCursor: null,
    hasMore: true,
    isLoading: false,
    isSocketConnected: false,
    installStatusRealtime: null,
    profileGenerationStatus: null,
    initialized: false,
  }),
  actions: {
    ensureRealtimeConnection() {
      const authStore = useAuthStore();
      if (!authStore.isAuthenticated) {
        realtimeSocket.disconnect();
        this.isSocketConnected = false;
        this.initialized = false;
        return;
      }
      if (this.initialized) {
        return;
      }
      this.initialized = true;
      realtimeSocket.connect({
        getToken: () => authStore.accessToken,
        onEvent: (event) => this.handleRealtimeEvent(event),
        onStateChange: (state) => {
          this.isSocketConnected = state === "connected";
        },
        onAuthFailure: async () => {
          const refreshedToken = await authStore.refreshAccessToken().catch(() => null);
          if (refreshedToken) {
            return true;
          }
          this.initialized = false;
          authStore.handleUnauthorized();
          return false;
        },
      });
    },
    disconnectRealtime() {
      this.initialized = false;
      this.isSocketConnected = false;
      realtimeSocket.disconnect();
    },
    async loadNotifications(reset = false) {
      if (this.isLoading) {
        return;
      }
      if (!reset && !this.hasMore) {
        return;
      }
      this.isLoading = true;
      try {
        const page = await fetchNotifications({
          cursor: reset ? null : this.nextCursor,
          pageSize: 30,
        });
        this.items = reset ? page.items : [...this.items, ...page.items];
        this.unreadCount = Number(page.unread_count || 0);
        this.nextCursor = page.next_cursor;
        this.hasMore = Boolean(page.has_more);
      } finally {
        this.isLoading = false;
      }
    },
    async markAllRead() {
      await markAllNotificationsRead();
      this.unreadCount = 0;
      this.items = this.items.map((item) => ({ ...item, is_read: true }));
    },
    handleRealtimeEvent(event: RealtimeEvent) {
      const eventType = String(event.event_type || "").trim();
      const payload = event.payload || {};
      if (!eventType) {
        return;
      }
      if (eventType === "notification.created") {
        const notification = payload.notification as NotificationRecord | undefined;
        if (notification && Number(notification.id)) {
          this.items = [notification, ...this.items];
        }
        this.unreadCount = Number(payload.unread_count || this.unreadCount || 0);
        return;
      }
      if (eventType === "notification.unread_count") {
        this.unreadCount = Number(payload.unread_count || 0);
        return;
      }
      if (eventType === "install.seed_status") {
        this.installStatusRealtime = payload as unknown as InstallStatus;
        return;
      }
      if (eventType === "profile.generation_status") {
        this.profileGenerationStatus = String(payload.status || "").trim() || null;
      }
    },
  },
});
