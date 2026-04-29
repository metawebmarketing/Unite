<script setup lang="ts">
import { defineAsyncComponent, watch } from "vue";

import { useAuthStore } from "./stores/auth";
import { useNotificationsStore } from "./stores/notifications";

const GlobalRouteLoadingModal = defineAsyncComponent(() => import("./components/GlobalRouteLoadingModal.vue"));

const authStore = useAuthStore();
const notificationsStore = useNotificationsStore();

watch(
  () => authStore.isAuthenticated,
  (isAuthenticated) => {
    if (isAuthenticated) {
      notificationsStore.ensureRealtimeConnection();
      return;
    }
    notificationsStore.disconnectRealtime();
  },
  { immediate: true },
);
</script>

<template>
  <div>
    <RouterView />
    <GlobalRouteLoadingModal />
    <GlobalErrorModal />
  </div>
</template>
