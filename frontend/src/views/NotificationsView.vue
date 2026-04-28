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
      <svg viewBox="0 0 24 24" class="icon"><path d="M15 5 8 12l7 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
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
