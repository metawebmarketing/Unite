<script setup lang="ts">
import { useRouter } from "vue-router";

import ConnectionsListCard from "../components/ConnectionsListCard.vue";

const router = useRouter();

function goBack() {
  if (window.history.length > 1) {
    router.back();
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
    <h1 class="feed-title search-page-title">Search</h1>
    <ConnectionsListCard :user-id="null" mode="users" title="" />
  </main>
</template>
