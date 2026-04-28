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
      <svg viewBox="0 0 24 24" class="icon"><path d="M15 5 8 12l7 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <ConnectionsListCard :user-id="userId" title="Connections" />
  </main>
</template>
