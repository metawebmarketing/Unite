<script setup lang="ts">
import { computed, onMounted } from "vue";
import { useRouter } from "vue-router";

import { useNotificationsStore } from "../stores/notifications";
import { formatLocalizedPostDateTime } from "../utils/date-display";

const notificationsStore = useNotificationsStore();
const router = useRouter();
const items = computed(() => notificationsStore.items);

function goBack() {
  void router.push({ name: "feed" });
}

onMounted(async () => {
  notificationsStore.ensureRealtimeConnection();
  await notificationsStore.loadNotifications(true);
  await notificationsStore.markAllRead();
});
</script>

<template>
  <main class="post-detail-page notifications-page">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 16 16" class="icon"><path d="M5 1H4L0 5L4 9H5V6H11C12.6569 6 14 7.34315 14 9C14 10.6569 12.6569 12 11 12H4V14H11C13.7614 14 16 11.7614 16 9C16 6.23858 13.7614 4 11 4H5V1Z" fill="currentColor"/></svg>
    </button>
    <h1 class="feed-title">Notifications</h1>
    <section v-if="!items.length" class="feed-item">
      <p>No notifications yet.</p>
    </section>
    <section class="stack">
      <article v-for="item in items" :key="item.id" class="feed-item">
        <p><strong>{{ item.title || item.event_type }}</strong></p>
        <p>{{ item.message || "New activity" }}</p>
        <small class="suggestion-meta">{{ formatLocalizedPostDateTime(item.created_at) }}</small>
      </article>
    </section>
    <button v-if="notificationsStore.hasMore" :disabled="notificationsStore.isLoading" @click="notificationsStore.loadNotifications()">
      {{ notificationsStore.isLoading ? "Loading..." : "Load more" }}
    </button>
  </main>
</template>
