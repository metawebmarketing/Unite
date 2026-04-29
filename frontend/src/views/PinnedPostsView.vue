<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { fetchPinnedPosts, type PostRecord } from "../api/posts";
import { useAuthStore } from "../stores/auth";
import { useErrorModalStore } from "../stores/error-modal";
import { formatLocalizedPostDateTime } from "../utils/date-display";

const router = useRouter();
const authStore = useAuthStore();
const errorModalStore = useErrorModalStore();
const posts = ref<PostRecord[]>([]);
const isLoading = ref(false);
const errorText = ref("");

function formatScore(value: unknown): string {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) {
    return "0.00";
  }
  return numeric.toFixed(2);
}

function goBack() {
  void router.push({ name: "feed" });
}

function openPost(postId: number) {
  void router.push({ name: "post-detail", params: { postId } });
}

async function loadPinnedPosts() {
  isLoading.value = true;
  errorText.value = "";
  try {
    posts.value = await fetchPinnedPosts();
  } catch {
    posts.value = [];
    errorText.value = "Unable to load pinned conversations.";
    errorModalStore.showError("Unable to load pinned conversations.");
  } finally {
    isLoading.value = false;
  }
}

onMounted(() => {
  void loadPinnedPosts();
});
</script>

<template>
  <main class="post-detail-page">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 16 16" class="icon"><path d="M5 1H4L0 5L4 9H5V6H11C12.6569 6 14 7.34315 14 9C14 10.6569 12.6569 12 11 12H4V14H11C13.7614 14 16 11.7614 16 9C16 6.23858 13.7614 4 11 4H5V1Z" fill="currentColor"/></svg>
    </button>
    <h1 class="feed-title">Pinned Conversations</h1>
    <p v-if="isLoading">Loading pinned conversations...</p>
    <section v-else class="reply-list">
      <article v-for="post in posts" :key="post.id" class="feed-item clickable-post-card" @click="openPost(post.id)">
        <p>{{ post.content }}</p>
        <p class="suggestion-meta">
          {{ post.author_username }}
          <span v-if="authStore.isStaff"> · User {{ formatScore(post.author_profile_rank_score) }}</span>
          <span v-if="formatLocalizedPostDateTime(post.created_at)"> · {{ formatLocalizedPostDateTime(post.created_at) }}</span>
          <span v-if="authStore.isStaff"> · {{ String(post.sentiment_label || "neutral") }} {{ formatScore(post.sentiment_score) }}</span>
        </p>
      </article>
      <p v-if="posts.length === 0">No pinned conversations yet.</p>
    </section>
  </main>
</template>
