<script setup lang="ts">
import { computed } from "vue";
import { useRoute, useRouter } from "vue-router";

import ConnectionsListCard from "../components/ConnectionsListCard.vue";

const route = useRoute();
const router = useRouter();
const userId = computed(() => {
  const value = Number(route.params.userId);
  return Number.isInteger(value) && value > 0 ? value : null;
});

function goBack() {
  if (route.name === "user-connections" && userId.value) {
    void router.push({ name: "user-profile", params: { userId: userId.value } });
    return;
  }
  void router.push({ name: "feed" });
}
</script>

<template>
  <main class="profile-detail-page">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 16 16" class="icon"><path d="M5 1H4L0 5L4 9H5V6H11C12.6569 6 14 7.34315 14 9C14 10.6569 12.6569 12 11 12H4V14H11C13.7614 14 16 11.7614 16 9C16 6.23858 13.7614 4 11 4H5V1Z" fill="currentColor"/></svg>
    </button>
    <ConnectionsListCard :user-id="userId" title="Connections" />
  </main>
</template>
