<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { connectToUser, disconnectFromUser, fetchConnectionStatus } from "../api/connections";
import { fetchPostsByUser, reactToPost, togglePostPin, type PostRecord } from "../api/posts";
import { fetchPublicProfile, type PublicProfile } from "../api/profile";
import { useAuthStore } from "../stores/auth";

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const profile = ref<PublicProfile | null>(null);
const posts = ref<PostRecord[]>([]);
const isLoading = ref(false);
const errorText = ref("");
const isOwnProfile = ref(false);
const isConnecting = ref(false);
const isConnected = ref(false);
const commonConnections = ref<Array<{ user_id: number; username: string; display_name: string; profile_image_url: string }>>([]);
const commonConnectionCount = ref(0);
const pinnedPosts = computed(() => posts.value.filter((post) => Boolean(post.is_pinned)));
const regularPosts = computed(() => posts.value.filter((post) => !post.is_pinned));

function placeholderAvatar(name: string) {
  const initial = (name || "U").trim().charAt(0).toUpperCase() || "U";
  return `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="96" height="96"><rect width="100%" height="100%" fill="#1c2440"/><text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" fill="#d8def9" font-size="32" font-family="Arial">${initial}</text></svg>`,
  )}`;
}

async function loadProfile() {
  const userId = Number(route.params.userId);
  if (!Number.isInteger(userId) || userId <= 0) {
    errorText.value = "Invalid user.";
    profile.value = null;
    posts.value = [];
    return;
  }
  isLoading.value = true;
  errorText.value = "";
  try {
    const [profileResult, postsResult] = await Promise.all([fetchPublicProfile(userId), fetchPostsByUser(userId)]);
    profile.value = profileResult;
    posts.value = postsResult;
    isOwnProfile.value = Boolean(authStore.username && profileResult.username === authStore.username);
    if (!isOwnProfile.value) {
      isConnected.value = false;
      commonConnections.value = [];
      commonConnectionCount.value = 0;
      const targetUserId = userId;
      void (async () => {
        try {
          const status = await fetchConnectionStatus(targetUserId);
          if (Number(route.params.userId) !== targetUserId) {
            return;
          }
          isConnected.value = Boolean(status.is_connected);
          commonConnections.value = status.common_connections || [];
          commonConnectionCount.value = Number(status.common_connection_count || 0);
        } catch {
          if (Number(route.params.userId) !== targetUserId) {
            return;
          }
          isConnected.value = false;
          commonConnections.value = [];
          commonConnectionCount.value = 0;
        }
      })();
    } else {
      isConnected.value = false;
      commonConnections.value = [];
      commonConnectionCount.value = 0;
    }
  } catch {
    errorText.value = "Unable to load profile.";
    profile.value = null;
    posts.value = [];
  } finally {
    isLoading.value = false;
  }
}

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

function openUserProfile(userId: number) {
  void router.push({ name: "user-profile", params: { userId } });
}

function openConnections() {
  if (!profile.value) {
    return;
  }
  void router.push({ name: "user-connections", params: { userId: profile.value.user_id } });
}

async function onConnect() {
  if (!profile.value || isOwnProfile.value || isConnecting.value) {
    return;
  }
  isConnecting.value = true;
  try {
    if (isConnected.value) {
      await disconnectFromUser(profile.value.user_id);
      isConnected.value = false;
      commonConnections.value = [];
      commonConnectionCount.value = 0;
    } else {
      await connectToUser(profile.value.user_id);
      const status = await fetchConnectionStatus(profile.value.user_id);
      isConnected.value = Boolean(status.is_connected);
      commonConnections.value = status.common_connections || [];
      commonConnectionCount.value = Number(status.common_connection_count || 0);
    }
  } catch {
    // Keep UI stable when connect fails.
  } finally {
    isConnecting.value = false;
  }
}

async function onTogglePin(post: PostRecord) {
  if (!isOwnProfile.value) {
    return;
  }
  try {
    const response = await togglePostPin(post.id);
    post.is_pinned = response.is_pinned;
    posts.value = [...posts.value].sort((a, b) => Number(Boolean(b.is_pinned)) - Number(Boolean(a.is_pinned)));
  } catch {
    // Keep existing state on failure.
  }
}

async function onBookmark(post: PostRecord) {
  try {
    await reactToPost(post.id, { action: "bookmark" });
    post.has_bookmarked = !Boolean(post.has_bookmarked);
  } catch {
    // Ignore transient bookmark errors.
  }
}

onMounted(() => {
  void loadProfile();
});

watch(
  () => route.params.userId,
  () => {
    void loadProfile();
  },
);
</script>

<template>
  <main class="profile-detail-page">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 24 24" class="icon"><path d="M15 5 8 12l7 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <p v-if="isLoading">Loading profile...</p>
    <p v-else-if="errorText">{{ errorText }}</p>
    <section v-else-if="profile" class="feed-item profile-summary-card">
      <div class="profile-summary-header">
        <img
          :src="profile.profile_image_url || placeholderAvatar(profile.display_name || profile.username)"
          alt="Profile"
          class="profile-detail-avatar"
        />
        <div>
          <h1>{{ profile.display_name || profile.username }}</h1>
          <p class="profile-username">@{{ profile.username }}</p>
          <span v-if="!isOwnProfile && isConnected" class="ai-badge connected-badge">Connected</span>
          <button type="button" class="author-username-link profile-connections-link" @click="openConnections">
            {{ profile.connection_count }} connections
          </button>
          <p v-if="profile.bio">{{ profile.bio }}</p>
          <div v-if="!isOwnProfile && commonConnectionCount > 0" class="common-connections-row">
            <span>Common connections: </span>
            <span v-for="(connection, index) in commonConnections.slice(0, 3)" :key="connection.user_id">
              <button type="button" class="author-username-link" @click="openUserProfile(connection.user_id)">
                {{ connection.display_name }}
              </button>
              <span v-if="index < Math.min(commonConnections.length, 3) - 1">, </span>
            </span>
            <span v-if="commonConnectionCount > 3">...</span>
          </div>
          <button
            v-if="!isOwnProfile"
            type="button"
            class="icon-action-button"
            :disabled="isConnecting"
            :title="isConnected ? 'Disconnect' : 'Connect'"
            :aria-label="isConnected ? 'Disconnect' : 'Connect'"
            @click="onConnect"
          >
            <svg viewBox="0 0 24 24" class="icon"><path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
            <span>{{ isConnecting ? "..." : isConnected ? "Disconnect" : "Connect" }}</span>
          </button>
        </div>
      </div>
    </section>

    <section v-if="profile" class="reply-list">
      <h2 v-if="pinnedPosts.length">Pinned Posts</h2>
      <article v-for="post in pinnedPosts" :key="`pinned-${post.id}`" class="feed-item clickable-post-card" @click="openPost(post.id)">
        <p>{{ post.content }}</p>
        <div class="post-actions">
          <button
            v-if="isOwnProfile"
            type="button"
            class="icon-action-button"
            title="Pin post"
            aria-label="Pin post"
            @click.stop="onTogglePin(post)"
          >
            <svg viewBox="0 0 24 24" class="icon"><path d="m8 3 8 8-2 2v6l-2-2-2 2v-6l-2-2 0 0Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span>{{ post.is_pinned ? 1 : 0 }}</span>
          </button>
          <button
            v-if="!isOwnProfile"
            type="button"
            class="icon-action-button"
            title="Bookmark"
            aria-label="Bookmark"
            @click.stop="onBookmark(post)"
          >
            <svg viewBox="0 0 24 24" class="icon"><path d="M6 4h12a1 1 0 0 1 1 1v15l-7-4-7 4V5a1 1 0 0 1 1-1Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span>{{ post.has_bookmarked ? 1 : 0 }}</span>
          </button>
          <span>{{ post.interaction_counts.like }} likes</span>
          <span>{{ post.interaction_counts.reply }} replies</span>
          <span>{{ post.interaction_counts.repost }} reposts</span>
        </div>
      </article>
      <h2>Posts</h2>
      <article v-for="post in regularPosts" :key="post.id" class="feed-item clickable-post-card" @click="openPost(post.id)">
        <p>{{ post.content }}</p>
        <div class="post-actions">
          <button
            v-if="isOwnProfile"
            type="button"
            class="icon-action-button"
            title="Pin post"
            aria-label="Pin post"
            @click.stop="onTogglePin(post)"
          >
            <svg viewBox="0 0 24 24" class="icon"><path d="m8 3 8 8-2 2v6l-2-2-2 2v-6l-2-2 0 0Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span>{{ post.is_pinned ? 1 : 0 }}</span>
          </button>
          <button
            v-if="!isOwnProfile"
            type="button"
            class="icon-action-button"
            title="Bookmark"
            aria-label="Bookmark"
            @click.stop="onBookmark(post)"
          >
            <svg viewBox="0 0 24 24" class="icon"><path d="M6 4h12a1 1 0 0 1 1 1v15l-7-4-7 4V5a1 1 0 0 1 1-1Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span>{{ post.has_bookmarked ? 1 : 0 }}</span>
          </button>
          <span>{{ post.interaction_counts.like }} likes</span>
          <span>{{ post.interaction_counts.reply }} replies</span>
          <span>{{ post.interaction_counts.repost }} reposts</span>
        </div>
      </article>
      <p v-if="posts.length === 0">No posts yet.</p>
    </section>
  </main>
</template>
