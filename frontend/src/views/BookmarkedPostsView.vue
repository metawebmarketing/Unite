<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { fetchBookmarkedPosts, type PostRecord } from "../api/posts";

const router = useRouter();
const posts = ref<PostRecord[]>([]);
const isLoading = ref(false);
const errorText = ref("");

function goBack() {
  if (window.history.length > 1) {
    router.back();
    return;
  }
  void router.push({ name: "feed" });
}

function openPost(postId: number) {
  void router.push({ name: "post-detail", params: { postId } });
}

async function loadBookmarks() {
  isLoading.value = true;
  errorText.value = "";
  try {
    posts.value = await fetchBookmarkedPosts();
  } catch {
    errorText.value = "Unable to load bookmarks.";
    posts.value = [];
  } finally {
    isLoading.value = false;
  }
}

onMounted(() => {
  void loadBookmarks();
});
</script>

<template>
  <main class="post-detail-page">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 24 24" class="icon"><path d="M15 5 8 12l7 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <h1 class="feed-title">Bookmarked Posts</h1>
    <p v-if="isLoading">Loading bookmarks...</p>
    <p v-else-if="errorText">{{ errorText }}</p>
    <article v-for="post in posts" :key="post.id" class="feed-item clickable-post-card" @click="openPost(post.id)">
      <p>{{ post.content }}</p>
      <p class="suggestion-meta">@{{ post.author_username }}</p>
    </article>
    <p v-if="!isLoading && !errorText && posts.length === 0">No bookmarked posts yet.</p>
  </main>
</template>
