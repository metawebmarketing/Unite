<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from "vue";
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
import {
  fetchPostsByUser,
  fetchSyncMetrics,
  togglePostPin,
  uploadPostImage,
  type PostRecord,
  type SyncMetrics,
} from "../api/posts";
import { blockUser, connectToUser, disconnectFromUser, fetchConnectionStatus, unblockUser } from "../api/connections";
import { reactToPost } from "../api/posts";
import { formatLocalizedPostDateTime } from "../utils/date-display";
import { useAuthStore } from "../stores/auth";
import { useErrorModalStore } from "../stores/error-modal";
import { useFeedStore } from "../stores/feed";
import { useNotificationsStore } from "../stores/notifications";
import { clearAllFeedCaches } from "../offline/feed-cache";
import MentionComposerInput from "../components/MentionComposerInput.vue";
import MentionTextContent from "../components/MentionTextContent.vue";
import { extractFirstHttpUrl } from "../utils/link-input";
import ComposeView from "./ComposeView.vue";
import ThemeStudioView from "./ThemeStudioView.vue";

const InAppBrowserModal = defineAsyncComponent(async () => {
  const componentModule = await import("../components/InAppBrowserModal.vue");
  return (componentModule as { default?: unknown }).default || componentModule;
});

const feedStore = useFeedStore();
const authStore = useAuthStore();
const notificationsStore = useNotificationsStore();
const errorModalStore = useErrorModalStore();
const route = useRoute();
const router = useRouter();
const activeModal = ref<"compose" | "theme-studio" | null>(null);
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
const relationshipStatusByUserId = ref<Record<number, string>>({});
const showReplyModal = ref(false);
const showShareModal = ref(false);
const replyDraft = ref("");
const replyLinkDraft = ref("");
const replyTargetPostId = ref<number | null>(null);
const replyAttachmentInputRef = ref<HTMLInputElement | null>(null);
const replyAttachments = ref<Array<{ media_type: "image"; media_url: string }>>([]);
const isReplyUploadingImage = ref(false);
const replyTaggedUserIds = ref<number[]>([]);
const shareDraft = ref("");
const shareLinkDraft = ref("");
const shareTargetPostId = ref<number | null>(null);
const shareAttachmentInputRef = ref<HTMLInputElement | null>(null);
const shareAttachments = ref<Array<{ media_type: "image"; media_url: string }>>([]);
const isShareUploadingImage = ref(false);
const shareTaggedUserIds = ref<number[]>([]);
const MAX_IMAGE_UPLOAD_BYTES = 5 * 1024 * 1024;
const showCopyLinkModal = ref(false);
const copyLinkFallbackValue = ref("");
const showInAppBrowser = ref(false);
const inAppBrowserUrl = ref("");
const feedOrdering = ref<"default" | "date_cluster">("default");
const notificationUnreadCount = computed(() => Math.max(0, Number(notificationsStore.unreadCount || 0)));

onMounted(async () => {
  notificationsStore.ensureRealtimeConnection();
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

function openInAppBrowser(rawUrl: unknown) {
  const normalizedUrl = extractFirstHttpUrl(String(rawUrl || ""));
  if (!normalizedUrl) {
    return;
  }
  inAppBrowserUrl.value = normalizedUrl;
  showInAppBrowser.value = true;
}

function getPostAttachments(value: unknown): Array<{ media_type: "image"; media_url: string }> {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((item) => ({
      media_type: String((item as { media_type?: string }).media_type || "").trim().toLowerCase(),
      media_url: String((item as { media_url?: string }).media_url || "").trim(),
    }))
    .filter(
      (item): item is { media_type: "image"; media_url: string } =>
        Boolean(item.media_url) && item.media_type === "image",
    );
}

function resolveTaggedUserIds(value: unknown): number[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value
    .map((entry) => Number(entry || 0))
    .filter((entry) => Number.isInteger(entry) && entry > 0);
}

function resetReplyComposerState() {
  replyDraft.value = "";
  replyLinkDraft.value = "";
  replyAttachments.value = [];
  isReplyUploadingImage.value = false;
  replyTaggedUserIds.value = [];
}

function resetShareComposerState() {
  shareDraft.value = "";
  shareLinkDraft.value = "";
  shareAttachments.value = [];
  isShareUploadingImage.value = false;
  shareTaggedUserIds.value = [];
}

function openReplyImagePicker() {
  replyAttachmentInputRef.value?.click();
}

function openShareImagePicker() {
  shareAttachmentInputRef.value?.click();
}

async function onReplyImageSelected(event: Event) {
  const input = event.target as HTMLInputElement | null;
  const files = input?.files ? Array.from(input.files) : [];
  if (!files.length) {
    return;
  }
  if (!navigator.onLine) {
    errorModalStore.showError("Image upload requires an online connection.");
    if (input) {
      input.value = "";
    }
    return;
  }
  isReplyUploadingImage.value = true;
  try {
    const file = files[0];
    if (file && String(file.type || "").toLowerCase().startsWith("image/")) {
      if (Number(file.size || 0) > MAX_IMAGE_UPLOAD_BYTES) {
        errorModalStore.showError("Image is too large. Maximum size is 5 MB.");
        return;
      }
      const uploaded = await uploadPostImage(file);
      replyAttachments.value = [uploaded];
    }
  } catch {
    errorModalStore.showError("Unable to upload image. Please retry.");
  } finally {
    isReplyUploadingImage.value = false;
    if (input) {
      input.value = "";
    }
  }
}

async function onShareImageSelected(event: Event) {
  const input = event.target as HTMLInputElement | null;
  const files = input?.files ? Array.from(input.files) : [];
  if (!files.length) {
    return;
  }
  if (!navigator.onLine) {
    errorModalStore.showError("Image upload requires an online connection.");
    if (input) {
      input.value = "";
    }
    return;
  }
  isShareUploadingImage.value = true;
  try {
    const file = files[0];
    if (file && String(file.type || "").toLowerCase().startsWith("image/")) {
      if (Number(file.size || 0) > MAX_IMAGE_UPLOAD_BYTES) {
        errorModalStore.showError("Image is too large. Maximum size is 5 MB.");
        return;
      }
      const uploaded = await uploadPostImage(file);
      shareAttachments.value = [uploaded];
    }
  } catch {
    errorModalStore.showError("Unable to upload image. Please retry.");
  } finally {
    isShareUploadingImage.value = false;
    if (input) {
      input.value = "";
    }
  }
}

function removeReplyAttachment(index: number) {
  replyAttachments.value = replyAttachments.value.filter((_, currentIndex) => currentIndex !== index);
}

function removeShareAttachment(index: number) {
  shareAttachments.value = shareAttachments.value.filter((_, currentIndex) => currentIndex !== index);
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

async function onReply(postId: number) {
  replyTargetPostId.value = postId;
  resetReplyComposerState();
  showReplyModal.value = true;
}

async function onRepost(postId: number) {
  shareTargetPostId.value = postId;
  resetShareComposerState();
  showShareModal.value = true;
}

async function onBookmark(postId: number) {
  await feedStore.toggleReaction(postId, "bookmark");
}

async function submitReplyModal() {
  const postId = replyTargetPostId.value;
  const draft = replyDraft.value.trim();
  if (!postId || !draft || isReplyUploadingImage.value) {
    return;
  }
  if (replyAttachments.value.length && !navigator.onLine) {
    errorModalStore.showError("Image attachments require an online connection.");
    return;
  }
  await feedStore.replyToPost(postId, {
    content: draft,
    link_url: extractFirstHttpUrl(replyLinkDraft.value) || undefined,
    attachments: replyAttachments.value.length ? replyAttachments.value : undefined,
    tagged_user_ids: replyTaggedUserIds.value,
  });
  closeReplyModal();
}

async function submitShareModal() {
  const postId = shareTargetPostId.value;
  if (!postId || isShareUploadingImage.value) {
    return;
  }
  if (shareAttachments.value.length && !navigator.onLine) {
    errorModalStore.showError("Image attachments require an online connection.");
    return;
  }
  const payload = {
    content: shareDraft.value.trim(),
    link_url: extractFirstHttpUrl(shareLinkDraft.value) || undefined,
    attachments: shareAttachments.value.length ? shareAttachments.value : undefined,
    tagged_user_ids: shareTaggedUserIds.value,
  };
  const hasQuotePayload =
    Boolean(payload.content) ||
    Boolean(payload.link_url) ||
    Boolean((payload.attachments || []).length) ||
    Boolean(payload.tagged_user_ids.length);
  await reactToPost(postId, hasQuotePayload ? { action: "quote", ...payload } : { action: "repost" });
  closeShareModal();
}

function closeReplyModal() {
  showReplyModal.value = false;
  replyTargetPostId.value = null;
  resetReplyComposerState();
}

function closeShareModal() {
  showShareModal.value = false;
  shareTargetPostId.value = null;
  resetShareComposerState();
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

function isBlockedWithUser(userId: number): boolean {
  return relationshipStatusByUserId.value[userId] === "blocked";
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
    relationshipStatusByUserId.value = {
      ...relationshipStatusByUserId.value,
      [userId]: String(status.relationship_status || "none"),
    };
  } catch {
    connectionStatusByUserId.value = {
      ...connectionStatusByUserId.value,
      [userId]: false,
    };
    relationshipStatusByUserId.value = {
      ...relationshipStatusByUserId.value,
      [userId]: "none",
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
    if (isBlockedWithUser(userId)) {
      return;
    }
    const isConnected = isConnectedWithUser(userId);
    const relationshipStatus = String(relationshipStatusByUserId.value[userId] || "none");
    if (isConnected || relationshipStatus === "pending_outgoing") {
      await disconnectFromUser(userId);
      setConnectedStateForUser(userId, false);
      relationshipStatusByUserId.value = { ...relationshipStatusByUserId.value, [userId]: "none" };
    } else {
      const result = await connectToUser(userId);
      const nextStatus = result.status === "pending" ? "pending_outgoing" : "connected";
      relationshipStatusByUserId.value = { ...relationshipStatusByUserId.value, [userId]: nextStatus };
      setConnectedStateForUser(userId, result.status === "accepted");
    }
  } catch {
    // Keep UI stable on transient failures.
  } finally {
    pendingConnectionUserIds.value = pendingConnectionUserIds.value.filter((value) => value !== userId);
    closePostMenu();
  }
}

async function onToggleBlock(userId: number, event?: MouseEvent) {
  event?.stopPropagation();
  if (!Number.isInteger(userId) || userId <= 0 || isConnectedPending(userId)) {
    return;
  }
  pendingConnectionUserIds.value = [...pendingConnectionUserIds.value, userId];
  try {
    await ensureConnectionStatus(userId);
    if (isBlockedWithUser(userId)) {
      await unblockUser(userId);
      relationshipStatusByUserId.value = { ...relationshipStatusByUserId.value, [userId]: "none" };
      feedStore.unblockAuthor(userId);
    } else {
      await blockUser(userId);
      relationshipStatusByUserId.value = { ...relationshipStatusByUserId.value, [userId]: "blocked" };
      setConnectedStateForUser(userId, false);
      feedStore.blockAuthor(userId);
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
  shareTargetPostId.value = post.id;
  resetShareComposerState();
  showShareModal.value = true;
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
  if (modal === "compose" || modal === "theme-studio") {
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
    demoActionStatus.value = `Removed ${result.removed_users} demo users and ${result.removed_posts} conversations. Regeneration queued.`;
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
    notificationsStore.ensureRealtimeConnection();
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
  () => notificationsStore.installStatusRealtime,
  async (status) => {
    if (!status) {
      return;
    }
    installSeedStatus.value = status.seed_status;
    demoProgressStatus.value = status;
    if (showDemoProgressModal.value && !["queued", "running"].includes(status.seed_status)) {
      if (status.seed_status === "completed") {
        await clearAllFeedCaches();
        await feedStore.loadFeed(true, { force: true });
        await trackVisibleAdImpressions();
        updateVirtualWindow();
      }
      setTimeout(() => {
        showDemoProgressModal.value = false;
      }, 500);
    }
  },
  { deep: true },
);

watch(
  [activeModal, showDemoProgressModal, showReplyModal, showShareModal, showCopyLinkModal],
  ([modalValue, progressModalValue, replyModalValue, shareModalValue, copyModalValue]) => {
    document.body.style.overflow =
      modalValue || progressModalValue || replyModalValue || shareModalValue || copyModalValue ? "hidden" : "";
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
      <RouterLink to="/" class="nav-logo-link" title="Home" aria-label="Go to home">
        <img src="/src/images/logo.png" alt="Unite logo" class="nav-logo-image" />
      </RouterLink>
      <RouterLink to="/" class="nav-icon-link" title="Conversations" aria-label="Conversations">
        <svg viewBox="0 0 24 24" class="icon"><path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-5v-6H10v6H5a1 1 0 0 1-1-1v-9.5Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="nav-link-label">Conversations</span>
      </RouterLink>
      <RouterLink to="/search" class="nav-icon-link" title="Search" aria-label="Search">
        <svg viewBox="0 0 24 24" class="icon"><circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="m16 16 4 4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        <span class="nav-link-label">Search</span>
      </RouterLink>
      <RouterLink to="/connections" class="nav-icon-link" title="Connections" aria-label="Connections">
        <svg viewBox="0 0 24 24" class="icon"><path d="M7.5 11a3 3 0 1 0-3-3 3 3 0 0 0 3 3Zm9 0a3 3 0 1 0-3-3 3 3 0 0 0 3 3ZM2.5 20a5 5 0 0 1 10 0M11.5 20a5 5 0 0 1 10 0" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="nav-link-label">Connections</span>
      </RouterLink>
      <RouterLink to="/messages" class="nav-icon-link" title="Private Conversations" aria-label="Private Conversations">
        <svg viewBox="0 0 24 24" class="icon"><path d="M12 22C17.5228 22 22 17.5228 22 12C22 6.47715 17.5228 2 12 2C6.47715 2 2 6.47715 2 12C2 13.5997 2.37562 15.1116 3.04346 16.4525C3.22094 16.8088 3.28001 17.2161 3.17712 17.6006L2.58151 19.8267C2.32295 20.793 3.20701 21.677 4.17335 21.4185L6.39939 20.8229C6.78393 20.72 7.19121 20.7791 7.54753 20.9565C8.88837 21.6244 10.4003 22 12 22Z" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
        <span class="nav-link-label">Private Conversations</span>
      </RouterLink>
      <RouterLink to="/notifications" class="nav-icon-link" title="Notifications" aria-label="Notifications">
        <svg viewBox="0 0 24 24" class="icon"><path d="M12 4a5 5 0 0 0-5 5v2.8l-1.8 2.5a1 1 0 0 0 .8 1.7h12a1 1 0 0 0 .8-1.7L17 11.8V9a5 5 0 0 0-5-5Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><path d="M9.5 18a2.5 2.5 0 0 0 5 0" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        <span class="nav-link-label">Notifications</span>
        <span v-if="notificationUnreadCount > 0" class="nav-badge">{{ notificationUnreadCount }}</span>
      </RouterLink>
      <RouterLink :to="{ name: 'feed', query: { modal: 'compose' } }" class="nav-icon-link" title="Compose" aria-label="Compose">
        <svg viewBox="0 0 24 24" class="icon"><path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0 0-3L17.5 5a2.1 2.1 0 0 0-3 0L4 15.5V20Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="nav-link-label">Compose</span>
      </RouterLink>
      <RouterLink to="/profile" class="nav-icon-link" title="Profile" aria-label="Profile">
        <svg viewBox="0 0 24 24" class="icon"><path d="M12 12a4 4 0 1 0-4-4 4 4 0 0 0 4 4Zm0 2c-4 0-7 2.2-7 5v1h14v-1c0-2.8-3-5-7-5Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="nav-link-label">Profile</span>
      </RouterLink>
      <RouterLink :to="{ name: 'feed', query: { modal: 'theme-studio' } }" class="nav-icon-link" title="Theme Studio" aria-label="Theme Studio">
        <svg viewBox="0 0 50 50" class="icon"><path d="M21.211 6c-12.632 0-20.211 10.133-20.211 15.2s2.526 8.867 7.579 8.867 7.58 1.266 7.58 5.066c0 5.066 3.789 8.866 8.842 8.866 16.422 0 24-8.866 24-17.732-.001-15.2-12.635-20.267-27.79-20.267zm-3.158 5.067c1.744 0 3.158 1.418 3.158 3.166 0 1.75-1.414 3.167-3.158 3.167s-3.158-1.418-3.158-3.167c0-1.748 1.414-3.166 3.158-3.166zm10.104 0c1.744 0 3.158 1.418 3.158 3.166 0 1.75-1.414 3.167-3.158 3.167-1.743 0-3.157-1.418-3.157-3.167 0-1.748 1.414-3.166 3.157-3.166zm10.106 5.066c1.745 0 3.159 1.417 3.159 3.167 0 1.75-1.414 3.166-3.159 3.166-1.744 0-3.157-1.417-3.157-3.166-.001-1.749 1.413-3.167 3.157-3.167zm-29.052 2.534c1.744 0 3.157 1.417 3.157 3.165 0 1.75-1.414 3.167-3.157 3.167s-3.158-1.418-3.158-3.167c0-1.748 1.414-3.165 3.158-3.165zm15.789 12.666c2.093 0 3.789 1.7 3.789 3.801 0 2.098-1.696 3.799-3.789 3.799s-3.789-1.701-3.789-3.799c0-2.101 1.696-3.801 3.789-3.801z" fill="currentColor"/></svg>
        <span class="nav-link-label">Theme</span>
      </RouterLink>
      <RouterLink to="/bookmarks" class="nav-icon-link" title="Bookmarks" aria-label="Bookmarks">
        <svg viewBox="0 0 24 24" class="icon"><path d="M6 4h12a1 1 0 0 1 1 1v15l-7-4-7 4V5a1 1 0 0 1 1-1Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        <span class="nav-link-label">Bookmarks</span>
      </RouterLink>
      <RouterLink to="/pinned" class="nav-icon-link" title="Pinned conversations" aria-label="Pinned conversations">
        <svg viewBox="0 0 24 24" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M17.1218 1.87023C15.7573 0.505682 13.4779 0.76575 12.4558 2.40261L9.61062 6.95916C9.61033 6.95965 9.60913 6.96167 9.6038 6.96549C9.59728 6.97016 9.58336 6.97822 9.56001 6.9848C9.50899 6.99916 9.44234 6.99805 9.38281 6.97599C8.41173 6.61599 6.74483 6.22052 5.01389 6.87251C4.08132 7.22378 3.61596 8.03222 3.56525 8.85243C3.51687 9.63502 3.83293 10.4395 4.41425 11.0208L7.94975 14.5563L1.26973 21.2363C0.879206 21.6269 0.879206 22.26 1.26973 22.6506C1.66025 23.0411 2.29342 23.0411 2.68394 22.6506L9.36397 15.9705L12.8995 19.5061C13.4808 20.0874 14.2853 20.4035 15.0679 20.3551C15.8881 20.3044 16.6966 19.839 17.0478 18.9065C17.6998 17.1755 17.3043 15.5086 16.9444 14.5375C16.9223 14.478 16.9212 14.4114 16.9355 14.3603C16.9421 14.337 16.9502 14.3231 16.9549 14.3165C16.9587 14.3112 16.9606 14.31 16.9611 14.3098L21.5177 11.4645C23.1546 10.4424 23.4147 8.16307 22.0501 6.79853L17.1218 1.87023ZM14.1523 3.46191C14.493 2.91629 15.2528 2.8296 15.7076 3.28445L20.6359 8.21274C21.0907 8.66759 21.0041 9.42737 20.4584 9.76806L15.9019 12.6133C14.9572 13.2032 14.7469 14.3637 15.0691 15.2327C15.3549 16.0037 15.5829 17.1217 15.1762 18.2015C15.1484 18.2752 15.1175 18.3018 15.0985 18.3149C15.0743 18.3316 15.0266 18.3538 14.9445 18.3589C14.767 18.3699 14.5135 18.2916 14.3137 18.0919L5.82846 9.6066C5.62872 9.40686 5.55046 9.15333 5.56144 8.97583C5.56651 8.8937 5.58877 8.84605 5.60548 8.82181C5.61855 8.80285 5.64516 8.7719 5.71886 8.74414C6.79869 8.33741 7.91661 8.56545 8.68762 8.85128C9.55668 9.17345 10.7171 8.96318 11.3071 8.01845L14.1523 3.46191Z" fill="currentColor"/></svg>
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
        <h1 class="feed-title">Conversations</h1>
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
              <button type="button" class="post-menu-trigger" @click.stop="openPostMenu(Number(item.data.id || 0))" title="Conversation menu" aria-label="Conversation menu">
                <svg viewBox="0 0 24 24" class="icon"><circle cx="6" cy="12" r="1.8" fill="currentColor"/><circle cx="12" cy="12" r="1.8" fill="currentColor"/><circle cx="18" cy="12" r="1.8" fill="currentColor"/></svg>
              </button>
              <div v-if="activePostMenuId === Number(item.data.id || 0)" class="post-menu">
                <button type="button" @click.stop="copyPostLink(Number(item.data.id || 0))">Copy conversation link</button>
                <button
                  v-if="!isOwnUsername(String(item.data.author_username || ''))"
                  type="button"
                  @click.stop="onConnect(Number(item.data.author_id || 0), $event)"
                >
                  {{
                    relationshipStatusByUserId[Number(item.data.author_id || 0)] === "blocked"
                      ? "Blocked"
                      : resolveConnectedState(Number(item.data.author_id || 0), item.data.author_is_connected)
                        ? "Disconnect"
                        : relationshipStatusByUserId[Number(item.data.author_id || 0)] === "pending_outgoing"
                          ? "Requested"
                          : "Connect"
                  }}
                </button>
                <button type="button" @click.stop="onToggleBlock(Number(item.data.author_id || 0), $event)">
                  {{ relationshipStatusByUserId[Number(item.data.author_id || 0)] === "blocked" ? "Unblock" : "Block" }}
                </button>
              </div>
            </div>
          </h3>
          <MentionTextContent
            :content="String(item.data.content || '')"
            :tagged-user-ids="resolveTaggedUserIds(item.data.tagged_user_ids)"
            @mention-click="openAuthorProfile"
          />
          <div v-if="getPostAttachments(item.data.attachments).length" class="post-attachment-grid">
            <div
              v-for="(attachment, attachmentIndex) in getPostAttachments(item.data.attachments)"
              :key="`${attachment.media_url}-${attachmentIndex}`"
              class="post-attachment-card"
            >
              <img v-if="attachment.media_type === 'image'" :src="attachment.media_url" alt="Conversation attachment" />
              <img :src="attachment.media_url" alt="Conversation attachment" />
            </div>
          </div>
          <div
            v-if="hasLinkPreviewContent(item.data.link_preview)"
            class="link-preview clickable-post-card"
            @click.stop="openInAppBrowser(item.data.link_preview?.url)"
          >
            <strong>{{ item.data.link_preview?.title }}</strong>
            <p>{{ item.data.link_preview?.description }}</p>
            <small>{{ item.data.link_preview?.host }}</small>
          </div>
          <div class="post-actions">
            <button class="icon-action-button" @click.stop="feedStore.toggleLike(Number(item.data.id))" title="Like" aria-label="Like">
              <svg viewBox="0 0 24 24" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M12 6.00019C10.2006 3.90317 7.19377 3.2551 4.93923 5.17534C2.68468 7.09558 2.36727 10.3061 4.13778 12.5772C5.60984 14.4654 10.0648 18.4479 11.5249 19.7369C11.6882 19.8811 11.7699 19.9532 11.8652 19.9815C11.9483 20.0062 12.0393 20.0062 12.1225 19.9815C12.2178 19.9532 12.2994 19.8811 12.4628 19.7369C13.9229 18.4479 18.3778 14.4654 19.8499 12.5772C21.6204 10.3061 21.3417 7.07538 19.0484 5.17534C16.7551 3.2753 13.7994 3.90317 12 6.00019Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
              <span>{{ item.data.interaction_counts?.like ?? 0 }}</span>
            </button>
            <button class="icon-action-button" @click.stop="onReply(Number(item.data.id))" title="Reply" aria-label="Reply">
              <svg viewBox="0 0 24 24" class="icon"><path d="M12 22C17.5228 22 22 17.5228 22 12C22 6.47715 17.5228 2 12 2C6.47715 2 2 6.47715 2 12C2 13.5997 2.37562 15.1116 3.04346 16.4525C3.22094 16.8088 3.28001 17.2161 3.17712 17.6006L2.58151 19.8267C2.32295 20.793 3.20701 21.677 4.17335 21.4185L6.39939 20.8229C6.78393 20.72 7.19121 20.7791 7.54753 20.9565C8.88837 21.6244 10.4003 22 12 22Z" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
              <span>{{ item.data.interaction_counts?.reply ?? 0 }}</span>
            </button>
            <button class="icon-action-button" @click.stop="onRepost(Number(item.data.id))" title="Amplify" aria-label="Amplify">
              <svg viewBox="0 0 24 24" class="icon"><path d="M4.06189 13C4.02104 12.6724 4 12.3387 4 12C4 7.58172 7.58172 4 12 4C14.5006 4 16.7332 5.14727 18.2002 6.94416M19.9381 11C19.979 11.3276 20 11.6613 20 12C20 16.4183 16.4183 20 12 20C9.61061 20 7.46589 18.9525 6 17.2916M9 17H6V17.2916M18.2002 4V6.94416M18.2002 6.94416V6.99993L15.2002 7M6 20V17.2916" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
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
              title="Pin conversation"
              aria-label="Pin conversation"
            >
              <svg viewBox="0 0 24 24" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M17.1218 1.87023C15.7573 0.505682 13.4779 0.76575 12.4558 2.40261L9.61062 6.95916C9.61033 6.95965 9.60913 6.96167 9.6038 6.96549C9.59728 6.97016 9.58336 6.97822 9.56001 6.9848C9.50899 6.99916 9.44234 6.99805 9.38281 6.97599C8.41173 6.61599 6.74483 6.22052 5.01389 6.87251C4.08132 7.22378 3.61596 8.03222 3.56525 8.85243C3.51687 9.63502 3.83293 10.4395 4.41425 11.0208L7.94975 14.5563L1.26973 21.2363C0.879206 21.6269 0.879206 22.26 1.26973 22.6506C1.66025 23.0411 2.29342 23.0411 2.68394 22.6506L9.36397 15.9705L12.8995 19.5061C13.4808 20.0874 14.2853 20.4035 15.0679 20.3551C15.8881 20.3044 16.6966 19.839 17.0478 18.9065C17.6998 17.1755 17.3043 15.5086 16.9444 14.5375C16.9223 14.478 16.9212 14.4114 16.9355 14.3603C16.9421 14.337 16.9502 14.3231 16.9549 14.3165C16.9587 14.3112 16.9606 14.31 16.9611 14.3098L21.5177 11.4645C23.1546 10.4424 23.4147 8.16307 22.0501 6.79853L17.1218 1.87023ZM14.1523 3.46191C14.493 2.91629 15.2528 2.8296 15.7076 3.28445L20.6359 8.21274C21.0907 8.66759 21.0041 9.42737 20.4584 9.76806L15.9019 12.6133C14.9572 13.2032 14.7469 14.3637 15.0691 15.2327C15.3549 16.0037 15.5829 17.1217 15.1762 18.2015C15.1484 18.2752 15.1175 18.3018 15.0985 18.3149C15.0743 18.3316 15.0266 18.3538 14.9445 18.3589C14.767 18.3699 14.5135 18.2916 14.3137 18.0919L5.82846 9.6066C5.62872 9.40686 5.55046 9.15333 5.56144 8.97583C5.56651 8.8937 5.58877 8.84605 5.60548 8.82181C5.61855 8.80285 5.64516 8.7719 5.71886 8.74414C6.79869 8.33741 7.91661 8.56545 8.68762 8.85128C9.55668 9.17345 10.7171 8.96318 11.3071 8.01845L14.1523 3.46191Z" fill="currentColor"/></svg>
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
              title="Show latest conversations"
              aria-label="Show latest conversations"
            >
              <svg viewBox="0 0 16 16" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M0 8L3.07945 4.30466C4.29638 2.84434 6.09909 2 8 2C9.90091 2 11.7036 2.84434 12.9206 4.30466L16 8L12.9206 11.6953C11.7036 13.1557 9.90091 14 8 14C6.09909 14 4.29638 13.1557 3.07945 11.6953L0 8ZM8 11C9.65685 11 11 9.65685 11 8C11 6.34315 9.65685 5 8 5C6.34315 5 5 6.34315 5 8C5 9.65685 6.34315 11 8 11Z" fill="currentColor"/></svg>
            </button>
          </div>
          <div v-if="isSuggestionExpanded(Number(item.data.user_id || 0))" class="suggestion-post-preview">
            <h4>Latest conversations</h4>
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
              <MentionTextContent
                :content="post.content"
                :tagged-user-ids="post.tagged_user_ids || []"
                @mention-click="openAuthorProfile"
              />
              <div v-if="getPostAttachments(post.attachments).length" class="post-attachment-grid">
                <div
                  v-for="(attachment, attachmentIndex) in getPostAttachments(post.attachments)"
                  :key="`${attachment.media_url}-${attachmentIndex}`"
                  class="post-attachment-card"
                >
                  <img v-if="attachment.media_type === 'image'" :src="attachment.media_url" alt="Conversation attachment" />
                  <img :src="attachment.media_url" alt="Conversation attachment" />
                </div>
              </div>
              <div
                v-if="hasLinkPreviewContent(post.link_preview)"
                class="link-preview clickable-post-card"
                @click.stop="openInAppBrowser(post.link_preview?.url)"
              >
                <strong>{{ post.link_preview?.title }}</strong>
                <p>{{ post.link_preview?.description }}</p>
                <small>{{ post.link_preview?.host }}</small>
              </div>
              <div class="post-actions">
                <button class="icon-action-button" @click.stop="onPreviewLike(post)" title="Like" aria-label="Like">
                  <svg viewBox="0 0 24 24" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M12 6.00019C10.2006 3.90317 7.19377 3.2551 4.93923 5.17534C2.68468 7.09558 2.36727 10.3061 4.13778 12.5772C5.60984 14.4654 10.0648 18.4479 11.5249 19.7369C11.6882 19.8811 11.7699 19.9532 11.8652 19.9815C11.9483 20.0062 12.0393 20.0062 12.1225 19.9815C12.2178 19.9532 12.2994 19.8811 12.4628 19.7369C13.9229 18.4479 18.3778 14.4654 19.8499 12.5772C21.6204 10.3061 21.3417 7.07538 19.0484 5.17534C16.7551 3.2753 13.7994 3.90317 12 6.00019Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                  <span>{{ post.interaction_counts.like }}</span>
                </button>
                <button class="icon-action-button" @click.stop="onPreviewReply(post)" title="Reply" aria-label="Reply">
                  <svg viewBox="0 0 24 24" class="icon"><path d="M12 22C17.5228 22 22 17.5228 22 12C22 6.47715 17.5228 2 12 2C6.47715 2 2 6.47715 2 12C2 13.5997 2.37562 15.1116 3.04346 16.4525C3.22094 16.8088 3.28001 17.2161 3.17712 17.6006L2.58151 19.8267C2.32295 20.793 3.20701 21.677 4.17335 21.4185L6.39939 20.8229C6.78393 20.72 7.19121 20.7791 7.54753 20.9565C8.88837 21.6244 10.4003 22 12 22Z" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
                  <span>{{ post.interaction_counts.reply }}</span>
                </button>
                <button class="icon-action-button" @click.stop="onPreviewRepost(post)" title="Amplify" aria-label="Amplify">
                  <svg viewBox="0 0 24 24" class="icon"><path d="M4.06189 13C4.02104 12.6724 4 12.3387 4 12C4 7.58172 7.58172 4 12 4C14.5006 4 16.7332 5.14727 18.2002 6.94416M19.9381 11C19.979 11.3276 20 11.6613 20 12C20 16.4183 16.4183 20 12 20C9.61061 20 7.46589 18.9525 6 17.2916M9 17H6V17.2916M18.2002 4V6.94416M18.2002 6.94416V6.99993L15.2002 7M6 20V17.2916" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
                  <span>{{ post.interaction_counts.repost }}</span>
                </button>
                <button class="icon-action-button" @click.stop="onPreviewBookmark(post)" title="Bookmark" aria-label="Bookmark">
                  <svg viewBox="0 0 24 24" class="icon"><path d="M6 4h12a1 1 0 0 1 1 1v15l-7-4-7 4V5a1 1 0 0 1 1-1Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
                  <span>{{ post.has_bookmarked ? 1 : 0 }}</span>
                </button>
              </div>
            </article>
            <p v-if="(suggestionPreviewPosts[Number(item.data.user_id || 0)] || []).length === 0">No recent conversations.</p>
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
          placeholder="Conversations per user"
        />
          <p>Estimated total conversations: {{ Math.max(1, Math.min(200000, Math.trunc(Number(demoSeedTotalUsers) || 1) * Math.trunc(Number(demoSeedPostsPerUser) || 1))) }}</p>
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
      <h2>Top Conversations: #{{ selectedInterestTag }}</h2>
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
    <ThemeStudioView v-if="activeModal === 'theme-studio'" embedded @close="closeModal" />
    <div v-if="showReplyModal" class="modal-overlay" @click.self="closeReplyModal">
      <section class="auth-card modal-card mention-host-card">
        <h2>Reply</h2>
        <MentionComposerInput
          v-model="replyDraft"
          :tagged-user-ids="replyTaggedUserIds"
          :required="true"
          placeholder="Write your reply"
          @update:tagged-user-ids="replyTaggedUserIds = $event"
        />
        <div class="composer-attachment-tools">
          <button
            type="button"
            class="icon-action-button"
            title="Add image"
            aria-label="Add image"
            @click="openReplyImagePicker"
          >
            <svg viewBox="0 0 24 24" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M23 4C23 2.34315 21.6569 1 20 1H4C2.34315 1 1 2.34315 1 4V20C1 21.6569 2.34315 23 4 23H20C21.6569 23 23 21.6569 23 20V4ZM21 4C21 3.44772 20.5523 3 20 3H4C3.44772 3 3 3.44772 3 4V20C3 20.5523 3.44772 21 4 21H20C20.5523 21 21 20.5523 21 20V4Z" fill="currentColor"/><path d="M4.80665 17.5211L9.1221 9.60947C9.50112 8.91461 10.4989 8.91461 10.8779 9.60947L14.0465 15.4186L15.1318 13.5194C15.5157 12.8476 16.4843 12.8476 16.8682 13.5194L19.1451 17.5039C19.526 18.1705 19.0446 19 18.2768 19H5.68454C4.92548 19 4.44317 18.1875 4.80665 17.5211Z" fill="currentColor"/><path d="M18 8C18 9.10457 17.1046 10 16 10C14.8954 10 14 9.10457 14 8C14 6.89543 14.8954 6 16 6C17.1046 6 18 6.89543 18 8Z" fill="currentColor"/></svg>
          </button>
          <input
            ref="replyAttachmentInputRef"
            type="file"
            accept="image/*"
            class="hidden-file-input"
            @change="onReplyImageSelected"
          />
        </div>
        <div v-if="replyAttachments.length" class="post-attachment-grid">
          <div
            v-for="(attachment, attachmentIndex) in replyAttachments"
            :key="`reply-attachment-${attachment.media_url}-${attachmentIndex}`"
            class="post-attachment-card"
          >
            <button type="button" class="post-attachment-remove" @click="removeReplyAttachment(attachmentIndex)">x</button>
            <img :src="attachment.media_url" alt="Reply attachment" />
          </div>
        </div>
        <p v-if="isReplyUploadingImage">Uploading image...</p>
        <input v-model="replyLinkDraft" placeholder="Optional link URL" />
        <div class="modal-actions">
          <button type="button" @click="closeReplyModal">Cancel</button>
          <button type="button" :disabled="!replyDraft.trim() || isReplyUploadingImage" @click="submitReplyModal">
            Reply
          </button>
        </div>
      </section>
    </div>
    <div v-if="showShareModal" class="modal-overlay" @click.self="closeShareModal">
      <section class="auth-card modal-card mention-host-card">
        <h2>Amplify</h2>
        <MentionComposerInput
          v-model="shareDraft"
          :tagged-user-ids="shareTaggedUserIds"
          placeholder="Add your amplify text (optional)"
          @update:tagged-user-ids="shareTaggedUserIds = $event"
        />
        <div class="composer-attachment-tools">
          <button
            type="button"
            class="icon-action-button"
            title="Add image"
            aria-label="Add image"
            @click="openShareImagePicker"
          >
            <svg viewBox="0 0 24 24" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M23 4C23 2.34315 21.6569 1 20 1H4C2.34315 1 1 2.34315 1 4V20C1 21.6569 2.34315 23 4 23H20C21.6569 23 23 21.6569 23 20V4ZM21 4C21 3.44772 20.5523 3 20 3H4C3.44772 3 3 3.44772 3 4V20C3 20.5523 3.44772 21 4 21H20C20.5523 21 21 20.5523 21 20V4Z" fill="currentColor"/><path d="M4.80665 17.5211L9.1221 9.60947C9.50112 8.91461 10.4989 8.91461 10.8779 9.60947L14.0465 15.4186L15.1318 13.5194C15.5157 12.8476 16.4843 12.8476 16.8682 13.5194L19.1451 17.5039C19.526 18.1705 19.0446 19 18.2768 19H5.68454C4.92548 19 4.44317 18.1875 4.80665 17.5211Z" fill="currentColor"/><path d="M18 8C18 9.10457 17.1046 10 16 10C14.8954 10 14 9.10457 14 8C14 6.89543 14.8954 6 16 6C17.1046 6 18 6.89543 18 8Z" fill="currentColor"/></svg>
          </button>
          <input
            ref="shareAttachmentInputRef"
            type="file"
            accept="image/*"
            class="hidden-file-input"
            @change="onShareImageSelected"
          />
        </div>
        <div v-if="shareAttachments.length" class="post-attachment-grid">
          <div
            v-for="(attachment, attachmentIndex) in shareAttachments"
            :key="`share-attachment-${attachment.media_url}-${attachmentIndex}`"
            class="post-attachment-card"
          >
            <button type="button" class="post-attachment-remove" @click="removeShareAttachment(attachmentIndex)">x</button>
            <img :src="attachment.media_url" alt="Amplify attachment" />
          </div>
        </div>
        <p v-if="isShareUploadingImage">Uploading image...</p>
        <input v-model="shareLinkDraft" placeholder="Optional link URL" />
        <div class="modal-actions">
          <button type="button" @click="closeShareModal">Cancel</button>
          <button type="button" :disabled="isShareUploadingImage" @click="submitShareModal">Amplify</button>
        </div>
      </section>
    </div>
    <div v-if="showCopyLinkModal" class="modal-overlay" @click.self="closeCopyLinkModal">
      <section class="auth-card modal-card">
        <h2>Copy conversation link</h2>
        <input :value="copyLinkFallbackValue" readonly />
        <div class="modal-actions">
          <button type="button" @click="closeCopyLinkModal">Close</button>
        </div>
      </section>
    </div>
    <InAppBrowserModal
      v-model="showInAppBrowser"
      :initial-url="inAppBrowserUrl"
    />
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
          Accounts: {{ demoProgressStatus.seed_created_users }} / {{ demoProgressStatus.seed_total_users }} · Conversations:
          {{ demoProgressStatus.seed_created_posts }} / {{ demoProgressStatus.seed_total_posts }}
        </p>
        <p v-if="demoProgressStatus.seed_last_message">{{ demoProgressStatus.seed_last_message }}</p>
        <div class="spinner" />
      </section>
    </div>
  </div>
</template>
