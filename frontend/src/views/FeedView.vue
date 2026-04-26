<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { RouterLink, useRoute, useRouter } from "vue-router";

import { sendAdEvent } from "../api/ads";
import { fetchInstallStatus, resetDemoData, type InstallStatus } from "../api/install";
import { fetchProfile } from "../api/profile";
import {
  fetchTopInterestPosts,
  fetchTopInterests,
  type InterestPost,
  type TopInterest,
} from "../api/interests";
import { fetchSyncMetrics, type SyncMetrics } from "../api/posts";
import { useAuthStore } from "../stores/auth";
import { useFeedStore } from "../stores/feed";
import ComposeView from "./ComposeView.vue";
import ProfileView from "./ProfileView.vue";
import ThemeStudioView from "./ThemeStudioView.vue";

const feedStore = useFeedStore();
const authStore = useAuthStore();
const route = useRoute();
const router = useRouter();
const activeModal = ref<"compose" | "profile" | "theme-studio" | null>(null);
const loadMoreAnchor = ref<HTMLElement | null>(null);
let observer: IntersectionObserver | null = null;
const topInterests = ref<TopInterest[]>([]);
const topInterestPosts = ref<InterestPost[]>([]);
const selectedInterestTag = ref("tech");
const syncMetrics = ref<SyncMetrics | null>(null);
const algorithmStatus = ref<string | null>(null);
const trackedAdImpressions = new Set<string>();
const demoActionStatus = ref("");
const isResettingDemo = ref(false);
const installSeedStatus = ref("");
const showDemoProgressModal = ref(false);
const demoProgressStatus = ref<InstallStatus | null>(null);
let demoProgressTimer: ReturnType<typeof setInterval> | null = null;
const isLocalDev = window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1";
const virtualWindowStart = ref(0);
const virtualWindowEnd = ref(0);
const estimatedItemHeightPx = 220;
let onlineHandler: (() => Promise<void>) | null = null;
let scrollHandler: (() => void) | null = null;
const isLoadingMoreFromFallback = ref(false);

onMounted(async () => {
  observer = new IntersectionObserver(
    async (entries) => {
      const entry = entries[0];
      if (entry?.isIntersecting && feedStore.hasMore && !feedStore.isLoading) {
        try {
          await feedStore.loadNextPage();
          await trackVisibleAdImpressions();
          updateVirtualWindow();
        } catch {
          // Keep observer alive even if a page request fails.
        }
      }
    },
    { threshold: 0.4 },
  );
  if (loadMoreAnchor.value) {
    observer.observe(loadMoreAnchor.value);
  }

  try {
    const profile = await fetchProfile();
    algorithmStatus.value = profile.algorithm_profile_status;
  } catch {
    algorithmStatus.value = null;
  }
  if (authStore.isStaff) {
    try {
      await feedStore.loadConfig();
    } catch {
      // Non-blocking for feed paging.
    }
    try {
      const installStatus = await fetchInstallStatus();
      installSeedStatus.value = installStatus.seed_status;
    } catch {
      installSeedStatus.value = "";
    }
  }
  try {
    await feedStore.loadFeed(true);
    await trackVisibleAdImpressions();
  } catch {
    // Initial load failures should not disable scrolling observers.
  }
  if (navigator.onLine) {
    try {
      await feedStore.flushQueuedActions();
    } catch {
      // Ignore replay failures for scroll setup.
    }
  }
  try {
    topInterests.value = await fetchTopInterests();
  } catch {
    topInterests.value = [];
  }
  try {
    topInterestPosts.value = await fetchTopInterestPosts(selectedInterestTag.value);
  } catch {
    topInterestPosts.value = [];
  }
  try {
    syncMetrics.value = await fetchSyncMetrics();
  } catch {
    syncMetrics.value = null;
  }
  onlineHandler = async () => {
    try {
      await feedStore.flushQueuedActions();
    } catch {
      // Ignore connectivity replay failures.
    }
  };
  scrollHandler = () => {
    updateVirtualWindow();
    void maybeLoadMoreFromScrollFallback();
  };
  window.addEventListener("scroll", scrollHandler, { passive: true });
  updateVirtualWindow();
  await maybeLoadMoreFromScrollFallback();
  window.addEventListener("online", onlineHandler);
  applyRouteModalState();
});

onUnmounted(() => {
  if (observer) {
    observer.disconnect();
  }
  if (onlineHandler) {
    window.removeEventListener("online", onlineHandler);
  }
  if (scrollHandler) {
    window.removeEventListener("scroll", scrollHandler);
  }
  if (demoProgressTimer) {
    clearInterval(demoProgressTimer);
    demoProgressTimer = null;
  }
  document.body.style.overflow = "";
});

async function loadInterestPosts(tag: string) {
  selectedInterestTag.value = tag;
  topInterestPosts.value = await fetchTopInterestPosts(tag);
  await feedStore.setInterestMode(tag);
  await trackVisibleAdImpressions();
  updateVirtualWindow();
}

async function setFeedMode(mode: "connections" | "suggestions" | "both") {
  await feedStore.setMode(mode);
  await trackVisibleAdImpressions();
  updateVirtualWindow();
  await maybeLoadMoreFromScrollFallback();
}

async function setInterestModeFromSelection() {
  await feedStore.setInterestMode(selectedInterestTag.value);
  await trackVisibleAdImpressions();
  updateVirtualWindow();
  await maybeLoadMoreFromScrollFallback();
}

function algorithmStatusMessage(status: string | null): string {
  if (status === "processing") {
    return "Personalized ranking profile is processing. Feed is running with fallback ranking.";
  }
  if (status === "not_started") {
    return "Personalized ranking profile has not started yet. Feed is running with fallback ranking.";
  }
  if (status === "failed") {
    return "Personalized ranking profile failed to refresh. Feed is running with fallback ranking.";
  }
  return "";
}

async function trackVisibleAdImpressions() {
  for (const item of feedStore.items) {
    if (item.item_type !== "ad") {
      continue;
    }
    const adEventKey = String(item.data.ad_event_key || "");
    if (!adEventKey || trackedAdImpressions.has(adEventKey)) {
      continue;
    }
    trackedAdImpressions.add(adEventKey);
    try {
      await sendAdEvent({
        event_type: "impression",
        ad_event_key: adEventKey,
        placement: String(item.data.placement || "feed"),
      });
    } catch {
      trackedAdImpressions.delete(adEventKey);
    }
  }
}

function updateVirtualWindow() {
  if (!isVirtualized.value) {
    virtualWindowStart.value = 0;
    virtualWindowEnd.value = feedStore.items.length;
    return;
  }
  const scrollTop = window.scrollY || window.pageYOffset || 0;
  const viewportHeight = window.innerHeight || 900;
  const firstVisibleIndex = Math.max(0, Math.floor(scrollTop / estimatedItemHeightPx) - 10);
  const visibleCount = Math.ceil(viewportHeight / estimatedItemHeightPx) + 24;
  virtualWindowStart.value = firstVisibleIndex;
  virtualWindowEnd.value = Math.min(feedStore.items.length, firstVisibleIndex + visibleCount);
}

function placeholderAvatar(name: string) {
  const initial = (name || "U").trim().charAt(0).toUpperCase() || "U";
  return `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><rect width="100%" height="100%" fill="#1c2440"/><text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" fill="#d8def9" font-size="22" font-family="Arial">${initial}</text></svg>`,
  )}`;
}

function closeModal() {
  activeModal.value = null;
  if (route.query.modal) {
    void router.replace({ name: "feed", query: {} });
  }
}

function applyRouteModalState() {
  const modal = String(route.query.modal || "");
  if (modal === "compose" || modal === "profile" || modal === "theme-studio") {
    activeModal.value = modal;
  }
}

const demoRecordProgressPercent = computed(() => {
  const status = demoProgressStatus.value;
  if (!status) {
    return 0;
  }
  const total = status.seed_total_users + status.seed_total_posts;
  const created = status.seed_created_users + status.seed_created_posts;
  if (!total) {
    return 0;
  }
  return Math.min(100, Math.round((created / total) * 100));
});

const demoCreatedRecordCount = computed(
  () => (demoProgressStatus.value?.seed_created_users || 0) + (demoProgressStatus.value?.seed_created_posts || 0),
);
const demoTotalRecordCount = computed(
  () => (demoProgressStatus.value?.seed_total_users || 0) + (demoProgressStatus.value?.seed_total_posts || 0),
);

function startDemoProgressPolling() {
  if (demoProgressTimer) {
    return;
  }
  demoProgressTimer = setInterval(async () => {
    try {
      const status = await fetchInstallStatus();
      demoProgressStatus.value = status;
      installSeedStatus.value = status.seed_status;
      if (!["queued", "running"].includes(status.seed_status)) {
        if (demoProgressTimer) {
          clearInterval(demoProgressTimer);
          demoProgressTimer = null;
        }
        setTimeout(() => {
          showDemoProgressModal.value = false;
        }, 500);
      }
    } catch {
      if (demoProgressStatus.value) {
        demoProgressStatus.value = {
          ...demoProgressStatus.value,
          seed_last_message: "Waiting for progress update...",
        };
      }
    }
  }, 900);
}

async function maybeLoadMoreFromScrollFallback() {
  if (isLoadingMoreFromFallback.value || feedStore.isLoading || !feedStore.hasMore) {
    return;
  }
  const anchor = loadMoreAnchor.value;
  if (!anchor) {
    return;
  }
  isLoadingMoreFromFallback.value = true;
  try {
    const viewportHeight = window.innerHeight || 900;
    let guard = 0;
    while (feedStore.hasMore && guard < 6) {
      const rect = anchor.getBoundingClientRect();
      const nearViewport = rect.top <= viewportHeight + 240;
      if (!nearViewport) {
        break;
      }
      await feedStore.loadNextPage();
      await trackVisibleAdImpressions();
      updateVirtualWindow();
      guard += 1;
    }
  } catch {
    // Keep fallback available after transient request failures.
  } finally {
    isLoadingMoreFromFallback.value = false;
  }
}

async function resetAndRegenerateDemo() {
  demoActionStatus.value = "";
  isResettingDemo.value = true;
  try {
    const result = await resetDemoData();
    installSeedStatus.value = result.seed_status;
    demoActionStatus.value = `Removed ${result.removed_users} demo users and ${result.removed_posts} posts. Regeneration queued.`;
    try {
      demoProgressStatus.value = await fetchInstallStatus();
    } catch {
      demoProgressStatus.value = {
        installed: true,
        installed_at: null,
        seed_requested: true,
        seed_status: result.seed_status || "queued",
        seed_task_id: result.seed_task_id || "",
        seed_total_users: 1000,
        seed_total_posts: 10000,
        seed_created_users: 0,
        seed_created_posts: 0,
        seed_last_message: "Regeneration queued.",
      };
    }
    showDemoProgressModal.value = true;
    startDemoProgressPolling();
  } catch (error: unknown) {
    const response = (error as { response?: { status?: number; data?: { detail?: string } } }).response;
    if (response?.status === 403) {
      demoActionStatus.value = "Unable to reset demo data: admin access is required.";
    } else if (response?.status === 404) {
      demoActionStatus.value = "Unable to reset demo data: local reset is disabled for this backend environment.";
    } else if (response?.status === 500) {
      const detail = response.data?.detail ? ` (${response.data.detail})` : "";
      demoActionStatus.value = `Unable to reset demo data: backend error${detail}.`;
    } else {
      demoActionStatus.value = "Unable to reset demo data due to a network or server error.";
    }
  } finally {
    isResettingDemo.value = false;
  }
}

watch(
  () => route.query.modal,
  () => {
    applyRouteModalState();
  },
);

watch(
  [activeModal, showDemoProgressModal],
  ([modalValue, progressModalValue]) => {
    document.body.style.overflow = modalValue || progressModalValue ? "hidden" : "";
  },
  { immediate: true },
);

const isVirtualized = computed(() => feedStore.items.length > 40);
const visibleFeedEntries = computed(() => {
  if (!isVirtualized.value) {
    return feedStore.items.map((item, index) => ({ item, index }));
  }
  return feedStore.items
    .slice(virtualWindowStart.value, virtualWindowEnd.value)
    .map((item, offset) => ({ item, index: virtualWindowStart.value + offset }));
});
const virtualTopSpacerPx = computed(() =>
  isVirtualized.value ? virtualWindowStart.value * estimatedItemHeightPx : 0,
);
const virtualBottomSpacerPx = computed(() =>
  isVirtualized.value ? (feedStore.items.length - virtualWindowEnd.value) * estimatedItemHeightPx : 0,
);

async function onAdClick(item: { data: Record<string, unknown> }) {
  const adEventKey = String(item.data.ad_event_key || "");
  if (!adEventKey) {
    return;
  }
  try {
    await sendAdEvent({
      event_type: "click",
      ad_event_key: adEventKey,
      placement: String(item.data.placement || "feed"),
    });
  } catch {
    // Ignore click telemetry failures.
  }
}
</script>

<template>
  <div class="layout">
    <aside class="left-nav">
      <RouterLink to="/">Home</RouterLink>
      <RouterLink :to="{ name: 'feed', query: { modal: 'compose' } }">Compose</RouterLink>
      <RouterLink :to="{ name: 'feed', query: { modal: 'profile' } }">Profile</RouterLink>
      <RouterLink :to="{ name: 'feed', query: { modal: 'theme-studio' } }">Theme Studio</RouterLink>
      <RouterLink v-if="authStore.isStaff" to="/policy-lab">Policy Lab</RouterLink>
      <RouterLink v-if="authStore.isStaff" to="/ads-lab">Ads Lab</RouterLink>
      <RouterLink v-if="authStore.isStaff" to="/ai-audit">AI Audit</RouterLink>
    </aside>

    <main class="feed">
      <header class="feed-header">
        <h1>Home</h1>
        <div class="tabs">
          <button @click="setFeedMode('connections')">Connections</button>
          <button @click="setFeedMode('suggestions')">Suggestions</button>
          <button @click="setFeedMode('both')">Both</button>
          <button @click="setInterestModeFromSelection">Interest</button>
        </div>
      </header>
      <div
        v-if="algorithmStatus && algorithmStatus !== 'ready'"
        class="algorithm-status"
      >
        {{ algorithmStatusMessage(algorithmStatus) }}
      </div>

      <div v-if="virtualTopSpacerPx > 0" :style="{ height: `${virtualTopSpacerPx}px` }" />
      <article
        v-for="{ item, index } in visibleFeedEntries"
        :key="`${item.item_type}-${index}`"
        class="feed-item"
      >
        <template v-if="item.item_type === 'post'">
          <h3 class="post-header">
            <img
              :src="
                String(item.data.author_profile_image_url || '') ||
                placeholderAvatar(String(item.data.author_display_name || 'User'))
              "
              alt="Profile"
              class="feed-avatar"
            />
            <span>
              {{ item.data.author_display_name || "User" }}
            </span>
            <span
              v-if="item.data.author_is_ai && item.data.author_ai_badge_enabled"
              class="ai-badge"
            >
              AI
            </span>
          </h3>
          <p>{{ item.data.content }}</p>
          <div v-if="item.data.link_preview" class="link-preview">
            <strong>{{ item.data.link_preview.title }}</strong>
            <p>{{ item.data.link_preview.description }}</p>
            <small>{{ item.data.link_preview.host }}</small>
          </div>
          <div class="post-actions">
            <button @click="feedStore.toggleLike(Number(item.data.id))">
              {{ item.data.has_liked ? "Unlike" : "Like" }} ({{ item.data.interaction_counts?.like ?? 0 }})
            </button>
            <span>Rank: {{ item.data.rank_score ?? 0 }}</span>
          </div>
        </template>
        <template v-else-if="item.item_type === 'suggestion'">
          <h3>Suggestion</h3>
          <p>{{ item.data.title }}</p>
          <p v-if="item.data.display_name">
            {{ item.data.display_name }}
            <span v-if="typeof item.data.shared_interest_count === 'number'">
              · Shared interests: {{ item.data.shared_interest_count }}
            </span>
          </p>
        </template>
        <template v-else>
          <h3>Ad</h3>
          <p>{{ item.data.title }}</p>
          <button @click="onAdClick(item)">Learn more</button>
        </template>
      </article>
      <div v-if="virtualBottomSpacerPx > 0" :style="{ height: `${virtualBottomSpacerPx}px` }" />

      <div ref="loadMoreAnchor" class="feed-status">
        <p v-if="feedStore.isLoading">Loading more...</p>
        <p v-else-if="feedStore.hasMore">Scroll to load more</p>
        <p v-else>End of feed</p>
      </div>
    </main>

    <aside class="right-card">
      <template v-if="authStore.isStaff">
        <h2>Feed Config</h2>
        <p>Suggestion interval: {{ feedStore.config?.suggestion_interval ?? 3 }}</p>
        <p>Ad interval: {{ feedStore.config?.ad_interval ?? 0 }}</p>
        <p>Max injection ratio: {{ feedStore.config?.max_injection_ratio ?? 0.5 }}</p>
        <template v-if="isLocalDev">
          <button @click="resetAndRegenerateDemo" :disabled="isResettingDemo">
            {{ isResettingDemo ? "Resetting demo data..." : "Reset & regenerate demo data" }}
          </button>
          <p v-if="installSeedStatus">Seed status: {{ installSeedStatus }}</p>
          <p v-if="demoActionStatus">{{ demoActionStatus }}</p>
        </template>
      </template>
      <h2>Top Interests</h2>
      <ul class="interest-list">
        <li v-for="interest in topInterests" :key="interest.tag">
          <button @click="loadInterestPosts(interest.tag)" class="interest-button">
            #{{ interest.tag }} ({{ interest.count }})
          </button>
        </li>
      </ul>
      <h2>Top Posts: #{{ selectedInterestTag }}</h2>
      <ul class="interest-list">
        <li v-for="post in topInterestPosts" :key="post.id">
          {{ post.content }}
        </li>
      </ul>
      <h2>Sync Metrics</h2>
      <p>Active idempotency records: {{ syncMetrics?.active_idempotency_records ?? 0 }}</p>
      <p>Replays: {{ syncMetrics?.replay_total ?? 0 }}</p>
      <p>Conflicts: {{ syncMetrics?.conflict_total ?? 0 }}</p>
      <p>Sync success: {{ syncMetrics?.sync_events?.success ?? 0 }}</p>
      <p>Sync dropped: {{ syncMetrics?.sync_events?.dropped ?? 0 }}</p>
      <p>Sync retry: {{ syncMetrics?.sync_events?.retry ?? 0 }}</p>
    </aside>

    <ComposeView v-if="activeModal === 'compose'" embedded @close="closeModal" />
    <ProfileView v-if="activeModal === 'profile'" embedded @close="closeModal" />
    <ThemeStudioView v-if="activeModal === 'theme-studio'" embedded @close="closeModal" />
    <div v-if="feedStore.isLoading && !feedStore.items.length" class="loading-overlay page-loading">
      <div class="spinner" />
    </div>
    <div v-if="showDemoProgressModal && demoProgressStatus" class="modal-overlay cropper-overlay">
      <section class="auth-card modal-card">
        <h2>Regenerating demo data</h2>
        <p>Seed status: {{ demoProgressStatus.seed_status }}</p>
        <div class="progress-track">
          <div class="progress-fill" :style="{ width: `${demoRecordProgressPercent}%` }" />
        </div>
        <p><strong>Record {{ demoCreatedRecordCount }} / {{ demoTotalRecordCount }}</strong></p>
        <p>
          Records: {{ demoCreatedRecordCount }} / {{ demoTotalRecordCount }}
        </p>
        <p>
          Accounts: {{ demoProgressStatus.seed_created_users }} / {{ demoProgressStatus.seed_total_users }} · Posts:
          {{ demoProgressStatus.seed_created_posts }} / {{ demoProgressStatus.seed_total_posts }}
        </p>
        <p v-if="demoProgressStatus.seed_last_message">{{ demoProgressStatus.seed_last_message }}</p>
        <div class="spinner" />
      </section>
    </div>
  </div>
</template>
