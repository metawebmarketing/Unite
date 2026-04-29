<script setup lang="ts">
import { useRouter } from "vue-router";

import ConnectionsListCard from "../components/ConnectionsListCard.vue";

const router = useRouter();

function goBack() {
  void router.push({ name: "feed" });
}
</script>

<template>
  <main class="profile-detail-page">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 16 16" class="icon"><path d="M5 1H4L0 5L4 9H5V6H11C12.6569 6 14 7.34315 14 9C14 10.6569 12.6569 12 11 12H4V14H11C13.7614 14 16 11.7614 16 9C16 6.23858 13.7614 4 11 4H5V1Z" fill="currentColor"/></svg>
    </button>
    <h1 class="feed-title search-page-title">Search</h1>
    <ConnectionsListCard :user-id="null" mode="users" title="" />
  </main>
</template>
