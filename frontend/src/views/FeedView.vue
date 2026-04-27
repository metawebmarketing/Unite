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
import { fetchPostsByUser, fetchSyncMetrics, togglePostPin, type PostRecord, type SyncMetrics } from "../api/posts";
import { connectToUser, disconnectFromUser, fetchConnectionStatus } from "../api/connections";
import { reactToPost } from "../api/posts";
import { formatLocalizedPostDateTime } from "../utils/date-display";
import { useAuthStore } from "../stores/auth";
import { useFeedStore } from "../stores/feed";
import { clearAllFeedCaches } from "../offline/feed-cache";
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
const demoSeedTotalUsers = ref(1000);
const demoSeedPostsPerUser = ref(10);
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
const activePostMenuId = ref<number | null>(null);
const expandedSuggestionUserIds = ref<number[]>([]);
const suggestionPreviewPosts = ref<Record<number, PostRecord[]>>({});
const pendingConnectionUserIds = ref<number[]>([]);
const connectionStatusByUserId = ref<Record<number, boolean>>({});
const showReplyModal = ref(false);
const replyDraft = ref("");
const replyTargetPostId = ref<number | null>(null);
const showCopyLinkModal = ref(false);
const copyLinkFallbackValue = ref("");
const feedOrdering = ref<"default" | "date_cluster">("default");

onMounted(async () => {
  feedStore.hydrateBlockedUsers();
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
      demoSeedTotalUsers.value = installStatus.seed_total_users || 1000;
      const seededPosts = Math.max(1, installStatus.seed_total_posts || 10000);
      demoSeedPostsPerUser.value = Math.max(1, Math.round(seededPosts / Math.max(1, demoSeedTotalUsers.value)));
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

function isModeActive(mode: "connections" | "suggestions" | "both" | "interest"): boolean {
  return feedStore.mode === mode;
}

function dateClusterTimestamp(value: unknown): number {
  if (typeof value !== "string" && !(value instanceof Date)) {
    return Number.NEGATIVE_INFINITY;
  }
  const parsed = value instanceof Date ? value : new Date(value);
  const timestamp = parsed.getTime();
  if (Number.isNaN(timestamp)) {
    return Number.NEGATIVE_INFINITY;
  }
  parsed.setHours(0, 0, 0, 0);
  return parsed.getTime();
}

function createdAtTimestamp(value: unknown): number {
  if (typeof value !== "string" && !(value instanceof Date)) {
    return Number.NEGATIVE_INFINITY;
  }
  const parsed = value instanceof Date ? value : new Date(value);
  const timestamp = parsed.getTime();
  if (Number.isNaN(timestamp)) {
    return Number.NEGATIVE_INFINITY;
  }
  return timestamp;
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

function formatScore(value: unknown): string {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) {
    return "0.00";
  }
  return numeric.toFixed(2);
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
    virtualWindowEnd.value = displayFeedItems.value.length;
    return;
  }
  const scrollTop = window.scrollY || window.pageYOffset || 0;
  const viewportHeight = window.innerHeight || 900;
  const firstVisibleIndex = Math.max(0, Math.floor(scrollTop / estimatedItemHeightPx) - 10);
  const visibleCount = Math.ceil(viewportHeight / estimatedItemHeightPx) + 24;
  virtualWindowStart.value = firstVisibleIndex;
  virtualWindowEnd.value = Math.min(displayFeedItems.value.length, firstVisibleIndex + visibleCount);
}

function placeholderAvatar(name: string) {
  const initial = (name || "U").trim().charAt(0).toUpperCase() || "U";
  return `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><rect width="100%" height="100%" fill="#1c2440"/><text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" fill="#d8def9" font-size="22" font-family="Arial">${initial}</text></svg>`,
  )}`;
}

function hasLinkPreviewContent(linkPreview: unknown): boolean {
  if (!linkPreview || typeof linkPreview !== "object") {
    return false;
  }
  const preview = linkPreview as { title?: string; description?: string; host?: string; url?: string };
  return Boolean(preview.title || preview.description || preview.host || preview.url);
}

function closeModal() {
  activeModal.value = null;
  if (route.query.modal) {
    void router.replace({ name: "feed", query: {} });
  }
}

function openPostMenu(postId: number) {
  activePostMenuId.value = activePostMenuId.value === postId ? null : postId;
}

function closePostMenu() {
  activePostMenuId.value = null;
}

async function copyPostLink(postId: number) {
  const postPath = router.resolve({ name: "post-detail", params: { postId } }).href;
  const postUrl = new URL(postPath, window.location.origin).toString();
  try {
    await navigator.clipboard.writeText(postUrl);
  } catch {
    copyLinkFallbackValue.value = postUrl;
    showCopyLinkModal.value = true;
  }
  closePostMenu();
}

function openAuthorProfile(authorId: number) {
  void router.push({ name: "user-profile", params: { userId: authorId } });
}

function openPost(postId: number) {
  void router.push({ name: "post-detail", params: { postId } });
}

function blockAuthor(authorId: number) {
  feedStore.blockAuthor(authorId);
  closePostMenu();
}

async function onReply(postId: number) {
  replyTargetPostId.value = postId;
  replyDraft.value = "";
  showReplyModal.value = true;
}

async function onRepost(postId: number) {
  await feedStore.toggleReaction(postId, "repost");
}

async function onBookmark(postId: number) {
  await feedStore.toggleReaction(postId, "bookmark");
}

async function submitReplyModal() {
  const postId = replyTargetPostId.value;
  const draft = replyDraft.value.trim();
  if (!postId || !draft) {
    return;
  }
  await feedStore.replyToPost(postId, draft);
  showReplyModal.value = false;
  replyDraft.value = "";
  replyTargetPostId.value = null;
}

function closeReplyModal() {
  showReplyModal.value = false;
  replyDraft.value = "";
  replyTargetPostId.value = null;
}

function closeCopyLinkModal() {
  showCopyLinkModal.value = false;
  copyLinkFallbackValue.value = "";
}

function isOwnUsername(username: string | null | undefined): boolean {
  return Boolean(username && authStore.username && username === authStore.username);
}

function isOwnPost(item: { data: Record<string, unknown> }): boolean {
  return isOwnUsername(String(item.data.author_username || ""));
}

function isConnectedPending(userId: number): boolean {
  return pendingConnectionUserIds.value.includes(userId);
}

function isConnectedWithUser(userId: number): boolean {
  return Boolean(connectionStatusByUserId.value[userId]);
}

function resolveConnectedState(userId: number, fallback: unknown = false): boolean {
  if (Object.prototype.hasOwnProperty.call(connectionStatusByUserId.value, userId)) {
    return Boolean(connectionStatusByUserId.value[userId]);
  }
  return Boolean(fallback);
}

function setConnectedStateForUser(userId: number, isConnected: boolean) {
  connectionStatusByUserId.value = { ...connectionStatusByUserId.value, [userId]: isConnected };
  for (const item of feedStore.items) {
    if (item.item_type === "post" && Number(item.data.author_id || 0) === userId) {
      item.data.author_is_connected = isConnected;
    }
    if (item.item_type === "suggestion" && Number(item.data.user_id || 0) === userId) {
      item.data.is_connected = isConnected;
    }
  }
  for (const posts of Object.values(suggestionPreviewPosts.value)) {
    for (const post of posts) {
      if (post.author_id === userId) {
        post.author_is_connected = isConnected;
      }
    }
  }
}

async function ensureConnectionStatus(userId: number) {
  if (!Number.isInteger(userId) || userId <= 0) {
    return;
  }
  if (Object.prototype.hasOwnProperty.call(connectionStatusByUserId.value, userId)) {
    return;
  }
  try {
    const status = await fetchConnectionStatus(userId);
    connectionStatusByUserId.value = {
      ...connectionStatusByUserId.value,
      [userId]: Boolean(status.is_connected),
    };
  } catch {
    connectionStatusByUserId.value = {
      ...connectionStatusByUserId.value,
      [userId]: false,
    };
  }
}

async function onConnect(userId: number, event?: MouseEvent) {
  event?.stopPropagation();
  if (!Number.isInteger(userId) || userId <= 0 || isConnectedPending(userId)) {
    return;
  }
  pendingConnectionUserIds.value = [...pendingConnectionUserIds.value, userId];
  try {
    await ensureConnectionStatus(userId);
    const isConnected = isConnectedWithUser(userId);
    if (isConnected) {
      await disconnectFromUser(userId);
      setConnectedStateForUser(userId, false);
    } else {
      await connectToUser(userId);
      setConnectedStateForUser(userId, true);
    }
  } catch {
    // Keep UI stable on transient failures.
  } finally {
    pendingConnectionUserIds.value = pendingConnectionUserIds.value.filter((value) => value !== userId);
    closePostMenu();
  }
}

async function onTogglePin(postId: number, item: { data: Record<string, unknown> }) {
  if (!isOwnPost(item)) {
    return;
  }
  try {
    const response = await togglePostPin(postId);
    item.data.is_pinned = response.is_pinned;
  } catch {
    // Keep prior pin state when request fails.
  }
}

async function toggleSuggestionPreview(userId: number) {
  if (!Number.isInteger(userId) || userId <= 0) {
    return;
  }
  const isExpanded = expandedSuggestionUserIds.value.includes(userId);
  if (isExpanded) {
    expandedSuggestionUserIds.value = expandedSuggestionUserIds.value.filter((value) => value !== userId);
    return;
  }
  if (!suggestionPreviewPosts.value[userId]) {
    try {
      const posts = await fetchPostsByUser(userId);
      suggestionPreviewPosts.value[userId] = posts.slice(0, 3);
    } catch {
      suggestionPreviewPosts.value[userId] = [];
    }
  }
  expandedSuggestionUserIds.value = [...expandedSuggestionUserIds.value, userId];
}

function isSuggestionExpanded(userId: number): boolean {
  return expandedSuggestionUserIds.value.includes(userId);
}

async function onPreviewLike(post: PostRecord) {
  const previousLiked = Boolean(post.has_liked);
  const previousCount = Number(post.interaction_counts?.like || 0);
  post.has_liked = !previousLiked;
  post.interaction_counts = {
    ...post.interaction_counts,
    like: previousLiked ? Math.max(0, previousCount - 1) : previousCount + 1,
  };
  try {
    await reactToPost(post.id, { action: "like" });
  } catch {
    post.has_liked = previousLiked;
    post.interaction_counts = {
      ...post.interaction_counts,
      like: previousCount,
    };
  }
}

async function onPreviewReply(post: PostRecord) {
  replyTargetPostId.value = post.id;
  replyDraft.value = "";
  showReplyModal.value = true;
}

async function onPreviewRepost(post: PostRecord) {
  const previousCount = Number(post.interaction_counts?.repost || 0);
  post.interaction_counts = {
    ...post.interaction_counts,
    repost: previousCount > 0 ? Math.max(0, previousCount - 1) : previousCount + 1,
  };
  try {
    await reactToPost(post.id, { action: "repost" });
  } catch {
    post.interaction_counts = {
      ...post.interaction_counts,
      repost: previousCount,
    };
  }
}

async function onPreviewBookmark(post: PostRecord) {
  const previous = Boolean(post.has_bookmarked);
  post.has_bookmarked = !previous;
  try {
    await reactToPost(post.id, { action: "bookmark" });
  } catch {
    post.has_bookmarked = previous;
  }
}

function onSuggestionPreviewPostClick(post: PostRecord, event: MouseEvent) {
  const target = event.target as HTMLElement | null;
  if (target?.closest("button, a, input, textarea, select, label, .post-actions, .post-menu, .post-menu-wrap")) {
    return;
  }
  openPost(post.id);
}

function onFeedItemClick(
  item: { item_type: string; data: Record<string, unknown> },
  event: MouseEvent,
) {
  if (item.item_type !== "post") {
    return;
  }
  const target = event.target as HTMLElement | null;
  if (target?.closest("button, a, input, textarea, select, label, .post-actions, .post-menu, .post-menu-wrap")) {
    return;
  }
  openPost(Number(item.data.id || 0));
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
        if (status.seed_status === "completed") {
          await clearAllFeedCaches();
          await feedStore.loadFeed(true, { force: true });
          await trackVisibleAdImpressions();
          updateVirtualWindow();
        }
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
    await clearAllFeedCaches();
    const normalizedUsers = Math.max(1, Math.trunc(Number(demoSeedTotalUsers.value) || 0));
    const normalizedPostsPerUser = Math.max(1, Math.trunc(Number(demoSeedPostsPerUser.value) || 0));
    const normalizedTotalPosts = Math.max(1, Math.min(200000, normalizedUsers * normalizedPostsPerUser));
    const result = await resetDemoData({
      seed_total_users: normalizedUsers,
      seed_total_posts: normalizedTotalPosts,
    });
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
        seed_total_users: normalizedUsers,
        seed_total_posts: normalizedTotalPosts,
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
  [activeModal, showDemoProgressModal, showReplyModal, showCopyLinkModal],
  ([modalValue, progressModalValue, replyModalValue, copyModalValue]) => {
    document.body.style.overflow = modalValue || progressModalValue || replyModalValue || copyModalValue ? "hidden" : "";
  },
  { immediate: true },
);

const filteredFeedItems = computed(() =>
  feedStore.items.filter((item) => {
    if (item.item_type !== "post") {
      return true;
    }
    const authorId = Number(item.data.author_id || 0);
    return !feedStore.isAuthorBlocked(authorId);
  }),
);
const displayFeedItems = computed(() => {
  const items = filteredFeedItems.value;
  if (feedOrdering.value !== "date_cluster") {
    return items;
  }
  return items
    .map((item, index) => ({
      item,
      index,
      cluster: dateClusterTimestamp(item.data.created_at),
      createdAt: createdAtTimestamp(item.data.created_at),
    }))
    .sort((left, right) => {
      if (left.cluster !== right.cluster) {
        return right.cluster - left.cluster;
      }
      if (left.createdAt !== right.createdAt) {
        return right.createdAt - left.createdAt;
      }
      return left.index - right.index;
    })
    .map((entry) => entry.item);
});
const isVirtualized = computed(() => displayFeedItems.value.length > 40);
const visibleFeedEntries = computed(() => {
  if (!isVirtualized.value) {
    return displayFeedItems.value.map((item, index) => ({ item, index }));
  }
  return displayFeedItems.value
    .slice(virtualWindowStart.value, virtualWindowEnd.value)
    .map((item, offset) => ({ item, index: virtualWindowStart.value + offset }));
});
const virtualTopSpacerPx = computed(() =>
  isVirtualized.value ? virtualWindowStart.value * estimatedItemHeightPx : 0,
);
const virtualBottomSpacerPx = computed(() =>
  isVirtualized.value ? (displayFeedItems.value.length - virtualWindowEnd.value) * estimatedItemHeightPx : 0,
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

function onLogout() {
  authStore.logout();
  void router.push("/login");
}
</script>

<template>
  <div class="layout">
    <aside class="left-nav">
      <RouterLink to="/" class="nav-icon-link" title="Home" aria-label="Home">
        <svg viewBox="0 0 24 24" class="icon"><path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1v-9.5Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="nav-link-label">Home</span>
      </RouterLink>
      <RouterLink to="/search" class="nav-icon-link" title="Search" aria-label="Search">
        <svg viewBox="0 0 24 24" class="icon"><circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="m16 16 4 4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        <span class="nav-link-label">Search</span>
      </RouterLink>
      <RouterLink to="/connections" class="nav-icon-link" title="Connections" aria-label="Connections">
        <svg viewBox="0 0 24 24" class="icon"><path d="M7.5 11a3 3 0 1 0-3-3 3 3 0 0 0 3 3Zm9 0a3 3 0 1 0-3-3 3 3 0 0 0 3 3ZM2.5 20a5 5 0 0 1 10 0M11.5 20a5 5 0 0 1 10 0" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="nav-link-label">Connections</span>
      </RouterLink>
      <RouterLink :to="{ name: 'feed', query: { modal: 'compose' } }" class="nav-icon-link" title="Compose" aria-label="Compose">
        <svg viewBox="0 0 24 24" class="icon"><path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0 0-3L17.5 5a2.1 2.1 0 0 0-3 0L4 15.5V20Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="nav-link-label">Compose</span>
      </RouterLink>
      <RouterLink :to="{ name: 'feed', query: { modal: 'profile' } }" class="nav-icon-link" title="Profile" aria-label="Profile">
        <svg viewBox="0 0 24 24" class="icon"><path d="M12 12a4 4 0 1 0-4-4 4 4 0 0 0 4 4Zm0 2c-4 0-7 2.2-7 5v1h14v-1c0-2.8-3-5-7-5Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="nav-link-label">Profile</span>
      </RouterLink>
      <RouterLink :to="{ name: 'feed', query: { modal: 'theme-studio' } }" class="nav-icon-link" title="Theme Studio" aria-label="Theme Studio">
        <svg viewBox="0 0 24 24" class="icon"><path d="M12 4a8 8 0 1 0 0 16h1.5a2.5 2.5 0 0 0 0-5H12a2 2 0 0 1 0-4h7a7 7 0 0 0-7-7Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="nav-link-label">Theme</span>
      </RouterLink>
      <RouterLink to="/bookmarks" class="nav-icon-link" title="Bookmarks" aria-label="Bookmarks">
        <svg viewBox="0 0 24 24" class="icon"><path d="M6 4h12a1 1 0 0 1 1 1v15l-7-4-7 4V5a1 1 0 0 1 1-1Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="nav-link-label">Bookmarks</span>
      </RouterLink>
      <RouterLink to="/pinned" class="nav-icon-link" title="Pinned posts" aria-label="Pinned posts">
        <svg viewBox="0 0 24 24" class="icon"><path d="m8 3 8 8-2 2v6l-2-2-2 2v-6l-2-2 0 0Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="nav-link-label">Pinned</span>
      </RouterLink>
      <RouterLink v-if="authStore.isStaff" to="/policy-lab" class="nav-icon-link" title="Policy Lab" aria-label="Policy Lab">
        <svg viewBox="0 0 24 24" class="icon"><path d="m12 3 7 3v5c0 5-3 8-7 10-4-2-7-5-7-10V6l7-3Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="nav-link-label">Policy</span>
      </RouterLink>
      <RouterLink v-if="authStore.isStaff" to="/ads-lab" class="nav-icon-link" title="Ads Lab" aria-label="Ads Lab">
        <svg viewBox="0 0 24 24" class="icon"><path d="M4 14v4h3l5 3V3l-5 3H4v4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M15 9a4 4 0 0 1 0 6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        <span class="nav-link-label">Ads</span>
      </RouterLink>
      <RouterLink v-if="authStore.isStaff" to="/ai-audit" class="nav-icon-link" title="AI Audit" aria-label="AI Audit">
        <svg viewBox="0 0 24 24" class="icon"><rect x="6" y="7" width="12" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="10" cy="12" r="1" fill="currentColor"/><circle cx="14" cy="12" r="1" fill="currentColor"/><path d="M12 7V4M9 17h6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        <span class="nav-link-label">AI Audit</span>
      </RouterLink>
      <button
        v-if="authStore.isAuthenticated"
        type="button"
        class="nav-icon-link nav-menu-button"
        title="Logout"
        aria-label="Logout"
        @click="onLogout"
      >
        <svg viewBox="0 0 24 24" class="icon"><path d="M9 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h4M14 8l5 4-5 4M19 12H9" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="nav-link-label">Logout</span>
      </button>
    </aside>

    <main class="feed">
      <header class="feed-header">
        <h1 class="feed-title">Home</h1>
        <div class="tabs mode-tabs">
          <button
            type="button"
            class="tab-icon-button"
            :class="{ active: isModeActive('connections') }"
            title="Connections"
            aria-label="Connections"
            @click="setFeedMode('connections')"
          >
            <svg viewBox="0 0 24 24" class="icon"><path d="M7.5 11a3 3 0 1 0-3-3 3 3 0 0 0 3 3Zm9 0a3 3 0 1 0-3-3 3 3 0 0 0 3 3ZM2.5 20a5 5 0 0 1 10 0M11.5 20a5 5 0 0 1 10 0" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <button
            type="button"
            class="tab-icon-button"
            :class="{ active: isModeActive('suggestions') }"
            title="Suggestions"
            aria-label="Suggestions"
            @click="setFeedMode('suggestions')"
          >
            <svg viewBox="0 0 24 24" class="icon"><path d="M12 3a6 6 0 0 0-3.6 10.8V17a1 1 0 0 0 1 1h5.2a1 1 0 0 0 1-1v-3.2A6 6 0 0 0 12 3Zm-2.2 16h4.4M10.5 21h3" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          </button>
          <button
            type="button"
            class="tab-icon-button"
            :class="{ active: isModeActive('both') }"
            title="Both"
            aria-label="Both"
            @click="setFeedMode('both')"
          >
            <svg viewBox="0 0 24 24" class="icon"><path d="M5 12h14M12 5v14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/><circle cx="12" cy="12" r="8" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>
          </button>
          <button
            type="button"
            class="tab-icon-button"
            :class="{ active: isModeActive('interest') }"
            title="Interest"
            aria-label="Interest"
            @click="setInterestModeFromSelection"
          >
            <svg viewBox="0 0 24 24" class="icon"><path d="M12 21c4-2 7-5 7-9a7 7 0 1 0-14 0c0 4 3 7 7 9Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><circle cx="12" cy="11" r="2.2" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>
          </button>
        </div>
        <button
          type="button"
          class="tab-icon-button"
          :class="{ active: feedOrdering === 'date_cluster' }"
          title="Group by date"
          aria-label="Group by date"
          @click="feedOrdering = feedOrdering === 'default' ? 'date_cluster' : 'default'"
        >
          <svg viewBox="0 0 24 24" class="icon">
            <rect x="4" y="5" width="16" height="15" rx="2" fill="none" stroke="currentColor" stroke-width="1.8" />
            <path d="M4 9h16M8 3v4M16 3v4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
          </svg>
        </button>
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
        :class="{ 'clickable-post-card': item.item_type === 'post' }"
        @click="onFeedItemClick(item, $event)"
      >
        <template v-if="item.item_type === 'post'">
          <h3 class="post-header">
            <button
              type="button"
              class="author-link feed-avatar-button"
              @click.stop="openAuthorProfile(Number(item.data.author_id || 0))"
            >
              <img
                :src="
                  String(item.data.author_profile_image_url || '') ||
                  placeholderAvatar(String(item.data.author_display_name || 'User'))
                "
                alt="Profile"
                class="feed-avatar"
              />
            </button>
            <span class="post-header-main">
              <button
                type="button"
                class="author-link"
                @click.stop="openAuthorProfile(Number(item.data.author_id || 0))"
              >
                {{ item.data.author_display_name || "User" }}
              </button>
              <span v-if="authStore.isStaff" class="suggestion-meta">
                User {{ formatScore(item.data.author_profile_rank_score) }}
              </span>
              <span v-if="formatLocalizedPostDateTime(String(item.data.created_at || ''))" class="suggestion-meta">
                {{ formatLocalizedPostDateTime(String(item.data.created_at || "")) }}
              </span>
              <span v-if="authStore.isStaff" class="suggestion-meta">
                {{ String(item.data.sentiment_label || "neutral") }} · {{ formatScore(item.data.sentiment_score) }}
              </span>
            </span>
            <span
              v-if="item.data.author_is_ai && item.data.author_ai_badge_enabled"
              class="ai-badge"
            >
              AI
            </span>
            <span
              v-if="
                !isOwnUsername(String(item.data.author_username || '')) &&
                resolveConnectedState(Number(item.data.author_id || 0), item.data.author_is_connected)
              "
              class="ai-badge connected-badge"
            >
              Connected
            </span>
            <div class="post-menu-wrap">
              <button type="button" class="post-menu-trigger" @click.stop="openPostMenu(Number(item.data.id || 0))" title="Post menu" aria-label="Post menu">
                <svg viewBox="0 0 24 24" class="icon"><circle cx="6" cy="12" r="1.8" fill="currentColor"/><circle cx="12" cy="12" r="1.8" fill="currentColor"/><circle cx="18" cy="12" r="1.8" fill="currentColor"/></svg>
              </button>
              <div v-if="activePostMenuId === Number(item.data.id || 0)" class="post-menu">
                <button type="button" @click.stop="copyPostLink(Number(item.data.id || 0))">Copy post link</button>
                <button
                  v-if="!isOwnUsername(String(item.data.author_username || ''))"
                  type="button"
                  @click.stop="onConnect(Number(item.data.author_id || 0), $event)"
                >
                  {{
                    resolveConnectedState(Number(item.data.author_id || 0), item.data.author_is_connected)
                      ? "Disconnect"
                      : "Connect"
                  }}
                </button>
                <button type="button" @click.stop="blockAuthor(Number(item.data.author_id || 0))">Block user</button>
              </div>
            </div>
          </h3>
          <p class="post-content-link">{{ item.data.content }}</p>
          <div v-if="hasLinkPreviewContent(item.data.link_preview)" class="link-preview">
            <strong>{{ item.data.link_preview?.title }}</strong>
            <p>{{ item.data.link_preview?.description }}</p>
            <small>{{ item.data.link_preview?.host }}</small>
          </div>
          <div class="post-actions">
            <button class="icon-action-button" @click.stop="feedStore.toggleLike(Number(item.data.id))" title="Like" aria-label="Like">
              <svg viewBox="0 0 24 24" class="icon"><path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
              <span>{{ item.data.interaction_counts?.like ?? 0 }}</span>
            </button>
            <button class="icon-action-button" @click.stop="onReply(Number(item.data.id))" title="Reply" aria-label="Reply">
              <svg viewBox="0 0 24 24" class="icon"><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H7l-4 3V12a8.5 8.5 0 1 1 18 0Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
              <span>{{ item.data.interaction_counts?.reply ?? 0 }}</span>
            </button>
            <button class="icon-action-button" @click.stop="onRepost(Number(item.data.id))" title="Repost" aria-label="Repost">
              <svg viewBox="0 0 24 24" class="icon"><path d="M7 7h11l-2.5-2.5M17 17H6l2.5 2.5M18 7v6M6 17v-6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
              <span>{{ item.data.interaction_counts?.repost ?? 0 }}</span>
            </button>
            <button class="icon-action-button" @click.stop="onBookmark(Number(item.data.id))" title="Bookmark" aria-label="Bookmark">
              <svg viewBox="0 0 24 24" class="icon"><path d="M6 4h12a1 1 0 0 1 1 1v15l-7-4-7 4V5a1 1 0 0 1 1-1Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
              <span>{{ item.data.has_bookmarked ? 1 : 0 }}</span>
            </button>
            <button
              v-if="isOwnPost(item)"
              class="icon-action-button"
              @click.stop="onTogglePin(Number(item.data.id), item)"
              title="Pin post"
              aria-label="Pin post"
            >
              <svg viewBox="0 0 24 24" class="icon"><path d="m8 3 8 8-2 2v6l-2-2-2 2v-6l-2-2 0 0Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
              <span>{{ item.data.is_pinned ? 1 : 0 }}</span>
            </button>
            <span v-if="authStore.isStaff" class="rank-pill">Score: {{ item.data.rank_score ?? 0 }}</span>
          </div>
        </template>
        <template v-else-if="item.item_type === 'suggestion'">
          <h3 class="post-header">
            <button
              type="button"
              class="author-link feed-avatar-button"
              @click.stop="openAuthorProfile(Number(item.data.user_id || 0))"
            >
              <img
                :src="String(item.data.profile_image_url || '') || placeholderAvatar(String(item.data.display_name || 'User'))"
                alt="Profile"
                class="feed-avatar"
              />
            </button>
            <span class="post-header-main">
              <span class="suggestion-meta">Suggested Profile</span>
              <button type="button" class="author-link" @click.stop="openAuthorProfile(Number(item.data.user_id || 0))">
                {{ item.data.display_name || "Suggested account" }}
              </button>
            </span>
            <span v-if="item.data.is_ai_account && item.data.ai_badge_enabled" class="ai-badge">AI</span>
            <span
              v-if="
                !isOwnUsername(String(item.data.username || '')) &&
                resolveConnectedState(Number(item.data.user_id || 0), item.data.is_connected)
              "
              class="ai-badge connected-badge"
            >
              Connected
            </span>
          </h3>
          <p v-if="item.data.bio">{{ item.data.bio }}</p>
          <p v-if="typeof item.data.shared_interest_count === 'number'" class="suggestion-meta">
            Shared interests: {{ item.data.shared_interest_count }}
          </p>
          <div class="post-actions">
            <button
              class="icon-action-button"
              :disabled="isConnectedPending(Number(item.data.user_id || 0))"
              @click.stop="onConnect(Number(item.data.user_id || 0), $event)"
              :title="
                resolveConnectedState(Number(item.data.user_id || 0), item.data.is_connected)
                  ? 'Disconnect'
                  : 'Connect'
              "
              :aria-label="
                resolveConnectedState(Number(item.data.user_id || 0), item.data.is_connected)
                  ? 'Disconnect'
                  : 'Connect'
              "
            >
              <svg viewBox="0 0 24 24" class="icon"><path d="M12 5v14M5 12h14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
              <span>
                {{
                  isConnectedPending(Number(item.data.user_id || 0))
                    ? "..."
                    : resolveConnectedState(Number(item.data.user_id || 0), item.data.is_connected)
                      ? "Disconnect"
                      : "Connect"
                }}
              </span>
            </button>
            <button
              class="icon-action-button"
              @click.stop="toggleSuggestionPreview(Number(item.data.user_id || 0))"
              title="Show latest posts"
              aria-label="Show latest posts"
            >
              <svg viewBox="0 0 24 24" class="icon"><path d="M3 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6-10-6-10-6Z" fill="none" stroke="currentColor" stroke-width="1.8"/><circle cx="12" cy="12" r="2.5" fill="none" stroke="currentColor" stroke-width="1.8"/></svg>
              <span>{{ isSuggestionExpanded(Number(item.data.user_id || 0)) ? 1 : 0 }}</span>
            </button>
          </div>
          <div v-if="isSuggestionExpanded(Number(item.data.user_id || 0))" class="suggestion-post-preview">
            <h4>Latest posts</h4>
            <article
              v-for="post in suggestionPreviewPosts[Number(item.data.user_id || 0)] || []"
              :key="post.id"
              class="feed-item clickable-post-card suggestion-preview-post"
              @click.stop="onSuggestionPreviewPostClick(post, $event)"
            >
              <h3 class="post-header">
                <button
                  type="button"
                  class="author-link feed-avatar-button"
                  @click.stop="openAuthorProfile(post.author_id)"
                >
                  <img
                    :src="post.author_profile_image_url || placeholderAvatar(post.author_display_name)"
                    alt="Profile"
                    class="feed-avatar"
                  />
                </button>
                <span class="post-header-main">
                  <button type="button" class="author-link" @click.stop="openAuthorProfile(post.author_id)">
                    {{ post.author_display_name }}
                  </button>
                  <span v-if="authStore.isStaff" class="suggestion-meta">
                    User {{ formatScore(post.author_profile_rank_score) }}
                  </span>
                  <span v-if="formatLocalizedPostDateTime(post.created_at)" class="suggestion-meta">
                    {{ formatLocalizedPostDateTime(post.created_at) }}
                  </span>
                  <span v-if="authStore.isStaff" class="suggestion-meta">
                    {{ String(post.sentiment_label || "neutral") }} · {{ formatScore(post.sentiment_score) }}
                  </span>
                </span>
                <span v-if="post.author_is_ai && post.author_ai_badge_enabled" class="ai-badge">AI</span>
                <span
                  v-if="!isOwnUsername(post.author_username) && resolveConnectedState(post.author_id, post.author_is_connected)"
                  class="ai-badge connected-badge"
                >
                  Connected
                </span>
              </h3>
              <p class="post-content-link">{{ post.content }}</p>
              <div v-if="hasLinkPreviewContent(post.link_preview)" class="link-preview">
                <strong>{{ post.link_preview?.title }}</strong>
                <p>{{ post.link_preview?.description }}</p>
                <small>{{ post.link_preview?.host }}</small>
              </div>
              <div class="post-actions">
                <button class="icon-action-button" @click.stop="onPreviewLike(post)" title="Like" aria-label="Like">
                  <svg viewBox="0 0 24 24" class="icon"><path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
                  <span>{{ post.interaction_counts.like }}</span>
                </button>
                <button class="icon-action-button" @click.stop="onPreviewReply(post)" title="Reply" aria-label="Reply">
                  <svg viewBox="0 0 24 24" class="icon"><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H7l-4 3V12a8.5 8.5 0 1 1 18 0Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
                  <span>{{ post.interaction_counts.reply }}</span>
                </button>
                <button class="icon-action-button" @click.stop="onPreviewRepost(post)" title="Repost" aria-label="Repost">
                  <svg viewBox="0 0 24 24" class="icon"><path d="M7 7h11l-2.5-2.5M17 17H6l2.5 2.5M18 7v6M6 17v-6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
                  <span>{{ post.interaction_counts.repost }}</span>
                </button>
                <button class="icon-action-button" @click.stop="onPreviewBookmark(post)" title="Bookmark" aria-label="Bookmark">
                  <svg viewBox="0 0 24 24" class="icon"><path d="M6 4h12a1 1 0 0 1 1 1v15l-7-4-7 4V5a1 1 0 0 1 1-1Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
                  <span>{{ post.has_bookmarked ? 1 : 0 }}</span>
                </button>
              </div>
            </article>
            <p v-if="(suggestionPreviewPosts[Number(item.data.user_id || 0)] || []).length === 0">No recent posts.</p>
          </div>
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
        <input
          v-model.number="demoSeedTotalUsers"
          type="number"
          min="1"
          max="10000"
          step="1"
          placeholder="Demo users"
        />
        <input
          v-model.number="demoSeedPostsPerUser"
          type="number"
          min="1"
          max="5000"
          step="1"
          placeholder="Posts per user"
        />
          <p>Estimated total posts: {{ Math.max(1, Math.min(200000, Math.trunc(Number(demoSeedTotalUsers) || 1) * Math.trunc(Number(demoSeedPostsPerUser) || 1))) }}</p>
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
    <div v-if="showReplyModal" class="modal-overlay">
      <section class="auth-card modal-card">
        <h2>Reply</h2>
        <textarea v-model="replyDraft" rows="4" placeholder="Write your reply" />
        <div class="modal-actions">
          <button type="button" @click="closeReplyModal">Cancel</button>
          <button type="button" :disabled="!replyDraft.trim()" @click="submitReplyModal">Post reply</button>
        </div>
      </section>
    </div>
    <div v-if="showCopyLinkModal" class="modal-overlay">
      <section class="auth-card modal-card">
        <h2>Copy post link</h2>
        <input :value="copyLinkFallbackValue" readonly />
        <div class="modal-actions">
          <button type="button" @click="closeCopyLinkModal">Close</button>
        </div>
      </section>
    </div>
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
