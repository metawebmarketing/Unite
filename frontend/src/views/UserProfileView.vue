<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { blockUser, connectToUser, disconnectFromUser, fetchConnectionStatus, unblockUser } from "../api/connections";
import { fetchPostsByUser, reactToPost, togglePostPin, type PostRecord } from "../api/posts";
import { fetchPublicProfile, type PublicProfile } from "../api/profile";
import { useAuthStore } from "../stores/auth";
import { useErrorModalStore } from "../stores/error-modal";
import { formatLocalizedPostDateTime } from "../utils/date-display";
import { extractFirstHttpUrl } from "../utils/link-input";

const InAppBrowserModal = defineAsyncComponent(async () => {
  const componentModule = await import("../components/InAppBrowserModal.vue");
  return (componentModule as { default?: unknown }).default || componentModule;
});

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const errorModalStore = useErrorModalStore();
const profile = ref<PublicProfile | null>(null);
const posts = ref<PostRecord[]>([]);
const isLoading = ref(false);
const errorText = ref("");
const isOwnProfile = ref(false);
const isConnecting = ref(false);
const isConnected = ref(false);
const isBlocked = ref(false);
const relationshipStatus = ref<"self" | "none" | "connected" | "pending_outgoing" | "pending_incoming" | "blocked">("none");
const commonConnections = ref<Array<{ user_id: number; username: string; display_name: string; profile_image_url: string }>>([]);
const commonConnectionCount = ref(0);
const showInAppBrowser = ref(false);
const inAppBrowserUrl = ref("");
const pinnedPosts = computed(() => posts.value.filter((post) => Boolean(post.is_pinned)));
const regularPosts = computed(() => posts.value.filter((post) => !post.is_pinned));
const perActionRankRows = computed(() => {
  const rows: Array<{ action: string; sum: number; count: number; avg: number }> = [];
  const breakdown = profile.value?.rank_action_scores || {};
  for (const [action, data] of Object.entries(breakdown)) {
    rows.push({
      action,
      sum: Number(data?.sum || 0),
      count: Number(data?.count || 0),
      avg: Number(data?.avg || 0),
    });
  }
  return rows.sort((a, b) => Math.abs(b.sum) - Math.abs(a.sum));
});

function formatScore(value: unknown): string {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) {
    return "0.00";
  }
  return numeric.toFixed(2);
}

function formatCountLabel(count: unknown, singular: string, plural: string): string {
  return Number(count || 0) === 1 ? singular : plural;
}

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
    errorModalStore.showError("Invalid user.");
    profile.value = null;
    posts.value = [];
    return;
  }
  isLoading.value = true;
  errorText.value = "";
  try {
    const profileResult = await fetchPublicProfile(userId);
    profile.value = profileResult;
    if (profileResult.can_view_feed === false) {
      posts.value = [];
    } else {
      posts.value = await fetchPostsByUser(userId);
    }
    isOwnProfile.value = Boolean(authStore.username && profileResult.username === authStore.username);
    if (!isOwnProfile.value) {
      isConnected.value = false;
      isBlocked.value = false;
      relationshipStatus.value = "none";
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
          isBlocked.value = Boolean(status.is_blocked);
          relationshipStatus.value = status.relationship_status;
          commonConnections.value = status.common_connections || [];
          commonConnectionCount.value = Number(status.common_connection_count || 0);
        } catch {
          if (Number(route.params.userId) !== targetUserId) {
            return;
          }
          isConnected.value = false;
          isBlocked.value = false;
          relationshipStatus.value = "none";
          commonConnections.value = [];
          commonConnectionCount.value = 0;
        }
      })();
    } else {
      isConnected.value = false;
      isBlocked.value = false;
      relationshipStatus.value = "self";
      commonConnections.value = [];
      commonConnectionCount.value = 0;
    }
  } catch {
    errorText.value = "Unable to load profile.";
    errorModalStore.showError("Unable to load profile.");
    profile.value = null;
    posts.value = [];
  } finally {
    isLoading.value = false;
  }
}

function goBack() {
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

function openInAppBrowser(rawUrl: unknown) {
  const normalizedUrl = extractFirstHttpUrl(String(rawUrl || ""));
  if (!normalizedUrl) {
    return;
  }
  inAppBrowserUrl.value = normalizedUrl;
  showInAppBrowser.value = true;
}

async function onConnect() {
  if (!profile.value || isOwnProfile.value || isConnecting.value) {
    return;
  }
  isConnecting.value = true;
  try {
    if (relationshipStatus.value === "blocked") {
      return;
    }
    if (isConnected.value || relationshipStatus.value === "pending_outgoing") {
      await disconnectFromUser(profile.value.user_id);
      isConnected.value = false;
      relationshipStatus.value = "none";
      commonConnections.value = [];
      commonConnectionCount.value = 0;
    } else {
      const connection = await connectToUser(profile.value.user_id);
      const status = await fetchConnectionStatus(profile.value.user_id);
      isConnected.value = Boolean(status.is_connected);
      relationshipStatus.value = status.relationship_status;
      commonConnections.value = status.common_connections || [];
      commonConnectionCount.value = Number(status.common_connection_count || 0);
      if (connection.status === "pending") {
        isConnected.value = false;
      }
    }
  } catch {
    // Keep UI stable when connect fails.
  } finally {
    isConnecting.value = false;
  }
}

async function onToggleBlock() {
  if (!profile.value || isOwnProfile.value || isConnecting.value) {
    return;
  }
  isConnecting.value = true;
  try {
    if (isBlocked.value || relationshipStatus.value === "blocked") {
      await unblockUser(profile.value.user_id);
      isBlocked.value = false;
      relationshipStatus.value = "none";
    } else {
      await blockUser(profile.value.user_id);
      isBlocked.value = true;
      relationshipStatus.value = "blocked";
      isConnected.value = false;
      posts.value = [];
      commonConnections.value = [];
      commonConnectionCount.value = 0;
    }
  } catch {
    // Keep UI stable when block call fails.
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
      <svg viewBox="0 0 16 16" class="icon"><path d="M5 1H4L0 5L4 9H5V6H11C12.6569 6 14 7.34315 14 9C14 10.6569 12.6569 12 11 12H4V14H11C13.7614 14 16 11.7614 16 9C16 6.23858 13.7614 4 11 4H5V1Z" fill="currentColor"/></svg>
    </button>
    <p v-if="isLoading">Loading profile...</p>
    <section v-else-if="profile" class="feed-item profile-summary-card">
      <div class="profile-summary-header">
        <img
          :src="profile.profile_image_url || placeholderAvatar(profile.display_name || profile.username)"
          alt="Profile"
          class="profile-detail-avatar"
        />
        <div>
          <h1>{{ profile.display_name || profile.username }}</h1>
          <span v-if="!isOwnProfile && isConnected" class="ai-badge connected-badge">Connected</span>
          <div class="profile-link-inline">
            <button type="button" class="author-username-link profile-connections-link" @click="openConnections">
              {{ profile.connection_count }} {{ formatCountLabel(profile.connection_count, "connection", "connections") }}
            </button>
            <template v-if="profile.profile_link_url">
              <span class="profile-link-bullet">·</span>
              <button type="button" class="author-username-link" @click="openInAppBrowser(profile.profile_link_url)">
                {{ profile.profile_link_url }}
              </button>
            </template>
          </div>
          <p v-if="authStore.isStaff" class="suggestion-meta">
            Rank: {{ formatScore(profile.rank_overall_score) }} · Actions tracked:
            {{ Number(profile.rank_last_500_count || 0) }}
          </p>
          <p v-if="authStore.isStaff && profile.rank_provider" class="suggestion-meta">Provider: {{ profile.rank_provider }}</p>
          <div v-if="authStore.isStaff && perActionRankRows.length" class="suggestion-meta">
            <span v-for="row in perActionRankRows.slice(0, 4)" :key="row.action">
              {{ row.action }} {{ formatScore(row.sum) }} ({{ row.count }}) ·
            </span>
          </div>
          <p v-if="profile.bio" class="profile-bio-text">{{ profile.bio }}</p>
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
          <div v-if="!isOwnProfile" class="profile-relationship-actions">
            <button
              type="button"
              class="icon-action-button"
              :disabled="isConnecting"
              :title="isConnected ? 'Disconnect' : relationshipStatus === 'pending_outgoing' ? 'Cancel request' : 'Connect'"
              :aria-label="isConnected ? 'Disconnect' : relationshipStatus === 'pending_outgoing' ? 'Cancel request' : 'Connect'"
              @click="onConnect"
            >
              <svg viewBox="0 0 24 24" class="icon"><path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
              <span>
                {{
                  isConnecting
                    ? "..."
                    : isConnected
                      ? "Disconnect"
                      : relationshipStatus === "pending_outgoing"
                        ? "Requested"
                        : "Connect"
                }}
              </span>
            </button>
            <button
              type="button"
              class="icon-action-button"
              :disabled="isConnecting"
              @click="onToggleBlock"
            >
              <svg viewBox="0 0 24 24" class="icon">
                <circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="1.8"/>
                <path d="M7 17 17 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
              </svg>
              <span>{{ isBlocked || relationshipStatus === "blocked" ? "Unblock" : "Block" }}</span>
            </button>
          </div>
        </div>
      </div>
    </section>

    <section v-if="profile && profile.can_view_feed !== false" class="reply-list">
      <h2 v-if="pinnedPosts.length">Pinned Conversations</h2>
      <article v-for="post in pinnedPosts" :key="`pinned-${post.id}`" class="feed-item clickable-post-card" @click="openPost(post.id)">
        <p>{{ post.content }}</p>
        <p v-if="formatLocalizedPostDateTime(post.created_at)" class="suggestion-meta">
          {{ formatLocalizedPostDateTime(post.created_at) }}
        </p>
        <p v-if="authStore.isStaff" class="suggestion-meta">
          {{ String(post.sentiment_label || "neutral") }} · {{ formatScore(post.sentiment_score) }}
        </p>
        <div class="post-actions">
          <button
            v-if="isOwnProfile"
            type="button"
            class="icon-action-button"
            title="Pin conversation"
            aria-label="Pin conversation"
            @click.stop="onTogglePin(post)"
          >
            <svg viewBox="0 0 24 24" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M17.1218 1.87023C15.7573 0.505682 13.4779 0.76575 12.4558 2.40261L9.61062 6.95916C9.61033 6.95965 9.60913 6.96167 9.6038 6.96549C9.59728 6.97016 9.58336 6.97822 9.56001 6.9848C9.50899 6.99916 9.44234 6.99805 9.38281 6.97599C8.41173 6.61599 6.74483 6.22052 5.01389 6.87251C4.08132 7.22378 3.61596 8.03222 3.56525 8.85243C3.51687 9.63502 3.83293 10.4395 4.41425 11.0208L7.94975 14.5563L1.26973 21.2363C0.879206 21.6269 0.879206 22.26 1.26973 22.6506C1.66025 23.0411 2.29342 23.0411 2.68394 22.6506L9.36397 15.9705L12.8995 19.5061C13.4808 20.0874 14.2853 20.4035 15.0679 20.3551C15.8881 20.3044 16.6966 19.839 17.0478 18.9065C17.6998 17.1755 17.3043 15.5086 16.9444 14.5375C16.9223 14.478 16.9212 14.4114 16.9355 14.3603C16.9421 14.337 16.9502 14.3231 16.9549 14.3165C16.9587 14.3112 16.9606 14.31 16.9611 14.3098L21.5177 11.4645C23.1546 10.4424 23.4147 8.16307 22.0501 6.79853L17.1218 1.87023ZM14.1523 3.46191C14.493 2.91629 15.2528 2.8296 15.7076 3.28445L20.6359 8.21274C21.0907 8.66759 21.0041 9.42737 20.4584 9.76806L15.9019 12.6133C14.9572 13.2032 14.7469 14.3637 15.0691 15.2327C15.3549 16.0037 15.5829 17.1217 15.1762 18.2015C15.1484 18.2752 15.1175 18.3018 15.0985 18.3149C15.0743 18.3316 15.0266 18.3538 14.9445 18.3589C14.767 18.3699 14.5135 18.2916 14.3137 18.0919L5.82846 9.6066C5.62872 9.40686 5.55046 9.15333 5.56144 8.97583C5.56651 8.8937 5.58877 8.84605 5.60548 8.82181C5.61855 8.80285 5.64516 8.7719 5.71886 8.74414C6.79869 8.33741 7.91661 8.56545 8.68762 8.85128C9.55668 9.17345 10.7171 8.96318 11.3071 8.01845L14.1523 3.46191Z" fill="currentColor"/></svg>
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
          <button
            type="button"
            class="icon-action-button"
            :title="formatCountLabel(post.interaction_counts.like, 'Like', 'Likes')"
            :aria-label="formatCountLabel(post.interaction_counts.like, 'Like', 'Likes')"
            disabled
            @click.stop
          >
            <svg viewBox="0 0 24 24" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M12 6.00019C10.2006 3.90317 7.19377 3.2551 4.93923 5.17534C2.68468 7.09558 2.36727 10.3061 4.13778 12.5772C5.60984 14.4654 10.0648 18.4479 11.5249 19.7369C11.6882 19.8811 11.7699 19.9532 11.8652 19.9815C11.9483 20.0062 12.0393 20.0062 12.1225 19.9815C12.2178 19.9532 12.2994 19.8811 12.4628 19.7369C13.9229 18.4479 18.3778 14.4654 19.8499 12.5772C21.6204 10.3061 21.3417 7.07538 19.0484 5.17534C16.7551 3.2753 13.7994 3.90317 12 6.00019Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span>{{ post.interaction_counts.like }}</span>
          </button>
          <button
            type="button"
            class="icon-action-button"
            :title="formatCountLabel(post.interaction_counts.reply, 'Reply', 'Replies')"
            :aria-label="formatCountLabel(post.interaction_counts.reply, 'Reply', 'Replies')"
            disabled
            @click.stop
          >
            <svg viewBox="0 0 24 24" class="icon"><path d="M12 22C17.5228 22 22 17.5228 22 12C22 6.47715 17.5228 2 12 2C6.47715 2 2 6.47715 2 12C2 13.5997 2.37562 15.1116 3.04346 16.4525C3.22094 16.8088 3.28001 17.2161 3.17712 17.6006L2.58151 19.8267C2.32295 20.793 3.20701 21.677 4.17335 21.4185L6.39939 20.8229C6.78393 20.72 7.19121 20.7791 7.54753 20.9565C8.88837 21.6244 10.4003 22 12 22Z" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
            <span>{{ post.interaction_counts.reply }}</span>
          </button>
          <button
            type="button"
            class="icon-action-button"
            :title="formatCountLabel(post.interaction_counts.repost, 'Amplify', 'Amplifications')"
            :aria-label="formatCountLabel(post.interaction_counts.repost, 'Amplify', 'Amplifications')"
            disabled
            @click.stop
          >
            <svg viewBox="0 0 24 24" class="icon"><path d="M4.06189 13C4.02104 12.6724 4 12.3387 4 12C4 7.58172 7.58172 4 12 4C14.5006 4 16.7332 5.14727 18.2002 6.94416M19.9381 11C19.979 11.3276 20 11.6613 20 12C20 16.4183 16.4183 20 12 20C9.61061 20 7.46589 18.9525 6 17.2916M9 17H6V17.2916M18.2002 4V6.94416M18.2002 6.94416V6.99993L15.2002 7M6 20V17.2916" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span>{{ post.interaction_counts.repost }}</span>
          </button>
        </div>
      </article>
      <h2>Conversations</h2>
      <article v-for="post in regularPosts" :key="post.id" class="feed-item clickable-post-card" @click="openPost(post.id)">
        <p>{{ post.content }}</p>
        <p v-if="formatLocalizedPostDateTime(post.created_at)" class="suggestion-meta">
          {{ formatLocalizedPostDateTime(post.created_at) }}
        </p>
        <p v-if="authStore.isStaff" class="suggestion-meta">
          {{ String(post.sentiment_label || "neutral") }} · {{ formatScore(post.sentiment_score) }}
        </p>
        <div class="post-actions">
          <button
            v-if="isOwnProfile"
            type="button"
            class="icon-action-button"
            title="Pin conversation"
            aria-label="Pin conversation"
            @click.stop="onTogglePin(post)"
          >
            <svg viewBox="0 0 24 24" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M17.1218 1.87023C15.7573 0.505682 13.4779 0.76575 12.4558 2.40261L9.61062 6.95916C9.61033 6.95965 9.60913 6.96167 9.6038 6.96549C9.59728 6.97016 9.58336 6.97822 9.56001 6.9848C9.50899 6.99916 9.44234 6.99805 9.38281 6.97599C8.41173 6.61599 6.74483 6.22052 5.01389 6.87251C4.08132 7.22378 3.61596 8.03222 3.56525 8.85243C3.51687 9.63502 3.83293 10.4395 4.41425 11.0208L7.94975 14.5563L1.26973 21.2363C0.879206 21.6269 0.879206 22.26 1.26973 22.6506C1.66025 23.0411 2.29342 23.0411 2.68394 22.6506L9.36397 15.9705L12.8995 19.5061C13.4808 20.0874 14.2853 20.4035 15.0679 20.3551C15.8881 20.3044 16.6966 19.839 17.0478 18.9065C17.6998 17.1755 17.3043 15.5086 16.9444 14.5375C16.9223 14.478 16.9212 14.4114 16.9355 14.3603C16.9421 14.337 16.9502 14.3231 16.9549 14.3165C16.9587 14.3112 16.9606 14.31 16.9611 14.3098L21.5177 11.4645C23.1546 10.4424 23.4147 8.16307 22.0501 6.79853L17.1218 1.87023ZM14.1523 3.46191C14.493 2.91629 15.2528 2.8296 15.7076 3.28445L20.6359 8.21274C21.0907 8.66759 21.0041 9.42737 20.4584 9.76806L15.9019 12.6133C14.9572 13.2032 14.7469 14.3637 15.0691 15.2327C15.3549 16.0037 15.5829 17.1217 15.1762 18.2015C15.1484 18.2752 15.1175 18.3018 15.0985 18.3149C15.0743 18.3316 15.0266 18.3538 14.9445 18.3589C14.767 18.3699 14.5135 18.2916 14.3137 18.0919L5.82846 9.6066C5.62872 9.40686 5.55046 9.15333 5.56144 8.97583C5.56651 8.8937 5.58877 8.84605 5.60548 8.82181C5.61855 8.80285 5.64516 8.7719 5.71886 8.74414C6.79869 8.33741 7.91661 8.56545 8.68762 8.85128C9.55668 9.17345 10.7171 8.96318 11.3071 8.01845L14.1523 3.46191Z" fill="currentColor"/></svg>
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
          <button
            type="button"
            class="icon-action-button"
            :title="formatCountLabel(post.interaction_counts.like, 'Like', 'Likes')"
            :aria-label="formatCountLabel(post.interaction_counts.like, 'Like', 'Likes')"
            disabled
            @click.stop
          >
            <svg viewBox="0 0 24 24" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M12 6.00019C10.2006 3.90317 7.19377 3.2551 4.93923 5.17534C2.68468 7.09558 2.36727 10.3061 4.13778 12.5772C5.60984 14.4654 10.0648 18.4479 11.5249 19.7369C11.6882 19.8811 11.7699 19.9532 11.8652 19.9815C11.9483 20.0062 12.0393 20.0062 12.1225 19.9815C12.2178 19.9532 12.2994 19.8811 12.4628 19.7369C13.9229 18.4479 18.3778 14.4654 19.8499 12.5772C21.6204 10.3061 21.3417 7.07538 19.0484 5.17534C16.7551 3.2753 13.7994 3.90317 12 6.00019Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span>{{ post.interaction_counts.like }}</span>
          </button>
          <button
            type="button"
            class="icon-action-button"
            :title="formatCountLabel(post.interaction_counts.reply, 'Reply', 'Replies')"
            :aria-label="formatCountLabel(post.interaction_counts.reply, 'Reply', 'Replies')"
            disabled
            @click.stop
          >
            <svg viewBox="0 0 24 24" class="icon"><path d="M12 22C17.5228 22 22 17.5228 22 12C22 6.47715 17.5228 2 12 2C6.47715 2 2 6.47715 2 12C2 13.5997 2.37562 15.1116 3.04346 16.4525C3.22094 16.8088 3.28001 17.2161 3.17712 17.6006L2.58151 19.8267C2.32295 20.793 3.20701 21.677 4.17335 21.4185L6.39939 20.8229C6.78393 20.72 7.19121 20.7791 7.54753 20.9565C8.88837 21.6244 10.4003 22 12 22Z" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
            <span>{{ post.interaction_counts.reply }}</span>
          </button>
          <button
            type="button"
            class="icon-action-button"
            :title="formatCountLabel(post.interaction_counts.repost, 'Amplify', 'Amplifications')"
            :aria-label="formatCountLabel(post.interaction_counts.repost, 'Amplify', 'Amplifications')"
            disabled
            @click.stop
          >
            <svg viewBox="0 0 24 24" class="icon"><path d="M4.06189 13C4.02104 12.6724 4 12.3387 4 12C4 7.58172 7.58172 4 12 4C14.5006 4 16.7332 5.14727 18.2002 6.94416M19.9381 11C19.979 11.3276 20 11.6613 20 12C20 16.4183 16.4183 20 12 20C9.61061 20 7.46589 18.9525 6 17.2916M9 17H6V17.2916M18.2002 4V6.94416M18.2002 6.94416V6.99993L15.2002 7M6 20V17.2916" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span>{{ post.interaction_counts.repost }}</span>
          </button>
        </div>
      </article>
      <p v-if="posts.length === 0">No conversations yet.</p>
    </section>
    <section v-else-if="profile" class="reply-list">
      <p>This profile feed is private.</p>
    </section>
    <InAppBrowserModal
      v-model="showInAppBrowser"
      :initial-url="inAppBrowserUrl"
    />
  </main>
</template>
