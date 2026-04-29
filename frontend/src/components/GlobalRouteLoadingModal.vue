<script setup lang="ts">
import { computed } from "vue";

import { useRouteLoadingStore } from "../stores/route-loading";

const routeLoadingStore = useRouteLoadingStore();
const isOpen = computed(() => routeLoadingStore.isRouteChanging);
</script>

<template>
  <div v-if="isOpen" class="loading-overlay page-loading global-route-loading-overlay" aria-live="polite" aria-label="Loading view">
    <span class="spinner" />
  </div>
</template>

<script lang="ts">
export default {
  name: "GlobalRouteLoadingModal",
};
</script>
