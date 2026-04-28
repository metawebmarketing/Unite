<script setup lang="ts">
import { watch } from "vue";

import { useAuthStore } from "./stores/auth";
import { useNotificationsStore } from "./stores/notifications";

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
    <GlobalErrorModal />
  </div>
</template>
