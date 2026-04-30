<script setup lang="ts">
import { defineAsyncComponent, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { blockUser, connectToUser, disconnectFromUser, fetchConnectionStatus, unblockUser } from "../api/connections";
import { fetchPostDetail, reactToPost, togglePostPin, uploadPostImage, type PostDetailResponse } from "../api/posts";
import { useAuthStore } from "../stores/auth";
import { useErrorModalStore } from "../stores/error-modal";
import { useFeedStore } from "../stores/feed";
import { formatLocalizedPostDateTime } from "../utils/date-display";
import { extractFirstHttpUrl } from "../utils/link-input";

const MentionComposerInput = defineAsyncComponent(async () => {
  const componentModule = await import("../components/MentionComposerInput.vue");
  return (componentModule as { default?: unknown }).default || componentModule;
});

const MentionTextContent = defineAsyncComponent(async () => {
  const componentModule = await import("../components/MentionTextContent.vue");
  return (componentModule as { default?: unknown }).default || componentModule;
});

const InAppBrowserModal = defineAsyncComponent(async () => {
  const componentModule = await import("../components/InAppBrowserModal.vue");
  return (componentModule as { default?: unknown }).default || componentModule;
});

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const errorModalStore = useErrorModalStore();
const feedStore = useFeedStore();
const detail = ref<PostDetailResponse | null>(null);
const isLoading = ref(false);
const errorText = ref("");
const activeMenuPostId = ref<number | null>(null);
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
const connectionStatusByAuthorId = ref<Record<number, boolean>>({});
const relationshipStatusByAuthorId = ref<Record<number, string>>({});
const pendingConnectionUserIds = ref<number[]>([]);

function formatScore(value: unknown): string {
  const numeric = Number(value || 0);
  if (!Number.isFinite(numeric)) {
    return "0.00";
  }
  return numeric.toFixed(2);
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
  const preview = linkPreview as { title?: string; description?: string; host?: string; url?: string; image_url?: string };
  return Boolean(preview.title || preview.description || preview.host || preview.url || preview.image_url);
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

async function loadPost() {
  const postId = Number(route.params.postId);
  if (!Number.isInteger(postId) || postId <= 0) {
    errorText.value = "Invalid conversation.";
    errorModalStore.showError("Invalid conversation.");
    detail.value = null;
    return;
  }
  isLoading.value = true;
  errorText.value = "";
  try {
    detail.value = await fetchPostDetail(postId);
    activeMenuPostId.value = null;
    if (detail.value) {
      const merged = { ...connectionStatusByAuthorId.value };
      merged[detail.value.post.author_id] = Boolean(detail.value.post.author_is_connected);
      for (const reply of detail.value.replies) {
        merged[reply.author_id] = Boolean(reply.author_is_connected);
      }
      connectionStatusByAuthorId.value = merged;
    }
  } catch (error: unknown) {
    const status = Number((error as { response?: { status?: number } })?.response?.status || 0);
    if (status === 429) {
      errorText.value = "Rate limited while loading this conversation. Please wait a few seconds and retry.";
      errorModalStore.showError("Rate limited while loading this conversation. Please wait a few seconds and retry.");
    } else {
      errorText.value = "Unable to load this conversation. If this keeps happening, refresh and retry.";
      errorModalStore.showError("Unable to load this conversation. If this keeps happening, refresh and retry.");
    }
    detail.value = null;
  } finally {
    isLoading.value = false;
  }
}

function goBack() {
  void router.push({ name: "feed" });
}

function openAuthorProfile(authorId: number) {
  void router.push({ name: "user-profile", params: { userId: authorId } });
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
  activeMenuPostId.value = null;
}

function isOwnPostRecord(post: { author_username: string }): boolean {
  return Boolean(post.author_username && authStore.username === post.author_username);
}

function isConnectedWithAuthor(authorId: number, fallback = false): boolean {
  if (Object.prototype.hasOwnProperty.call(connectionStatusByAuthorId.value, authorId)) {
    return Boolean(connectionStatusByAuthorId.value[authorId]);
  }
  return Boolean(fallback);
}

function isBlockedWithAuthor(authorId: number): boolean {
  return relationshipStatusByAuthorId.value[authorId] === "blocked";
}

function isConnectPending(authorId: number): boolean {
  return pendingConnectionUserIds.value.includes(authorId);
}

function setConnectedForAuthor(authorId: number, isConnected: boolean) {
  connectionStatusByAuthorId.value = { ...connectionStatusByAuthorId.value, [authorId]: isConnected };
  if (detail.value?.post.author_id === authorId) {
    detail.value.post.author_is_connected = isConnected;
  }
  if (detail.value) {
    detail.value.replies = detail.value.replies.map((reply) =>
      reply.author_id === authorId ? { ...reply, author_is_connected: isConnected } : reply,
    );
  }
}

function openPost(postId: number) {
  const currentPostId = Number(route.params.postId);
  if (currentPostId === postId) {
    return;
  }
  void router.push({ name: "post-detail", params: { postId } });
}

function onReplyCardClick(reply: PostDetailResponse["replies"][number], event: MouseEvent) {
  const target = event.target as HTMLElement | null;
  if (target?.closest("button, a, input, textarea, select, label, .post-actions, .post-menu, .post-menu-wrap")) {
    return;
  }
  openPost(reply.id);
}

function togglePostMenu(postId: number) {
  activeMenuPostId.value = activeMenuPostId.value === postId ? null : postId;
}

async function onConnect(post: PostDetailResponse["post"] | PostDetailResponse["replies"][number], event?: MouseEvent) {
  event?.stopPropagation();
  if (isOwnPostRecord(post) || isConnectPending(post.author_id)) {
    return;
  }
  pendingConnectionUserIds.value = [...pendingConnectionUserIds.value, post.author_id];
  try {
    const status = await fetchConnectionStatus(post.author_id);
    relationshipStatusByAuthorId.value = {
      ...relationshipStatusByAuthorId.value,
      [post.author_id]: String(status.relationship_status || "none"),
    };
    if (isBlockedWithAuthor(post.author_id)) {
      return;
    }
    if (
      isConnectedWithAuthor(post.author_id, Boolean(post.author_is_connected))
      || relationshipStatusByAuthorId.value[post.author_id] === "pending_outgoing"
    ) {
      await disconnectFromUser(post.author_id);
      setConnectedForAuthor(post.author_id, false);
      relationshipStatusByAuthorId.value = { ...relationshipStatusByAuthorId.value, [post.author_id]: "none" };
    } else {
      const result = await connectToUser(post.author_id);
      relationshipStatusByAuthorId.value = {
        ...relationshipStatusByAuthorId.value,
        [post.author_id]: result.status === "pending" ? "pending_outgoing" : "connected",
      };
      setConnectedForAuthor(post.author_id, result.status === "accepted");
    }
  } catch {
    // Ignore connection failures for now.
  } finally {
    pendingConnectionUserIds.value = pendingConnectionUserIds.value.filter((value) => value !== post.author_id);
    activeMenuPostId.value = null;
  }
}

async function onToggleBlock(authorId: number) {
  if (!Number.isInteger(authorId) || authorId <= 0 || pendingConnectionUserIds.value.includes(authorId)) {
    return;
  }
  pendingConnectionUserIds.value = [...pendingConnectionUserIds.value, authorId];
  try {
    const status = await fetchConnectionStatus(authorId);
    const relationship = String(status.relationship_status || "none");
    if (relationship === "blocked") {
      await unblockUser(authorId);
      relationshipStatusByAuthorId.value = { ...relationshipStatusByAuthorId.value, [authorId]: "none" };
      feedStore.unblockAuthor(authorId);
    } else {
      await blockUser(authorId);
      relationshipStatusByAuthorId.value = { ...relationshipStatusByAuthorId.value, [authorId]: "blocked" };
      setConnectedForAuthor(authorId, false);
      feedStore.blockAuthor(authorId);
      void router.push({ name: "feed" });
    }
  } catch {
    // Ignore transient block failures.
  } finally {
    pendingConnectionUserIds.value = pendingConnectionUserIds.value.filter((item) => item !== authorId);
    activeMenuPostId.value = null;
  }
}

async function onLike(target: PostDetailResponse["post"] | PostDetailResponse["replies"][number]) {
  const previous = target.has_liked;
  const previousCount = target.interaction_counts.like;
  target.has_liked = !previous;
  target.interaction_counts.like = previous ? Math.max(0, previousCount - 1) : previousCount + 1;
  try {
    await reactToPost(target.id, { action: "like" });
  } catch {
    target.has_liked = previous;
    target.interaction_counts.like = previousCount;
  }
}

async function onRepost(target: PostDetailResponse["post"] | PostDetailResponse["replies"][number]) {
  shareTargetPostId.value = target.id;
  resetShareComposerState();
  showShareModal.value = true;
}

async function onBookmark(target: PostDetailResponse["post"] | PostDetailResponse["replies"][number]) {
  const previous = Boolean(target.has_bookmarked);
  target.has_bookmarked = !previous;
  try {
    await reactToPost(target.id, { action: "bookmark" });
  } catch {
    target.has_bookmarked = previous;
  }
}

async function onTogglePin(target: PostDetailResponse["post"] | PostDetailResponse["replies"][number]) {
  if (!isOwnPostRecord(target) || target.id !== detail.value?.post.id) {
    return;
  }
  try {
    const response = await togglePostPin(target.id);
    target.is_pinned = response.is_pinned;
  } catch {
    // Keep existing state on pin failure.
  }
}

async function onReply(target: PostDetailResponse["post"] | PostDetailResponse["replies"][number]) {
  replyTargetPostId.value = target.id;
  resetReplyComposerState();
  showReplyModal.value = true;
}

async function submitReplyModal() {
  const postId = replyTargetPostId.value;
  if (!postId || !replyDraft.value.trim() || isReplyUploadingImage.value) {
    return;
  }
  if (replyAttachments.value.length && !navigator.onLine) {
    errorModalStore.showError("Image attachments require an online connection.");
    return;
  }
  try {
    await reactToPost(postId, {
      action: "reply",
      content: replyDraft.value.trim(),
      link_url: extractFirstHttpUrl(replyLinkDraft.value) || undefined,
      attachments: replyAttachments.value.length ? replyAttachments.value : undefined,
      tagged_user_ids: replyTaggedUserIds.value,
    });
    closeReplyModal();
    await loadPost();
  } catch {
    // Keep current state untouched when reply fails.
  }
}

function closeReplyModal() {
  showReplyModal.value = false;
  replyTargetPostId.value = null;
  resetReplyComposerState();
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
  await loadPost();
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

onMounted(() => {
  feedStore.hydrateBlockedUsers();
  void loadPost();
});

onUnmounted(() => {
  document.body.style.overflow = "";
});

watch(
  () => route.params.postId,
  () => {
    void loadPost();
  },
);

watch(
  [showReplyModal, showShareModal, showCopyLinkModal, showInAppBrowser],
  ([replyModalValue, shareModalValue, copyModalValue, inAppBrowserValue]) => {
    document.body.style.overflow =
      replyModalValue || shareModalValue || copyModalValue || inAppBrowserValue ? "hidden" : "";
  },
  { immediate: true },
);
</script>

<template>
  <main class="post-detail-page">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 16 16" class="icon"><path d="M5 1H4L0 5L4 9H5V6H11C12.6569 6 14 7.34315 14 9C14 10.6569 12.6569 12 11 12H4V14H11C13.7614 14 16 11.7614 16 9C16 6.23858 13.7614 4 11 4H5V1Z" fill="currentColor"/></svg>
    </button>
    <p v-if="isLoading">Loading conversation...</p>
    <article v-else-if="detail" class="feed-item">
      <header class="post-header">
        <button type="button" class="author-link feed-avatar-button" @click="openAuthorProfile(detail.post.author_id)">
          <img
            :src="detail.post.author_profile_image_url || placeholderAvatar(detail.post.author_display_name)"
            alt="Profile"
            class="feed-avatar"
          />
        </button>
        <span class="post-header-main">
          <button type="button" class="author-link" @click="openAuthorProfile(detail.post.author_id)">
            {{ detail.post.author_display_name }}
          </button>
          <span v-if="authStore.isStaff" class="suggestion-meta">
            User {{ formatScore(detail.post.author_profile_rank_score) }}
          </span>
          <span v-if="formatLocalizedPostDateTime(detail.post.created_at)" class="suggestion-meta">
            {{ formatLocalizedPostDateTime(detail.post.created_at) }}
          </span>
          <span v-if="authStore.isStaff" class="suggestion-meta">
            {{ String(detail.post.sentiment_label || "neutral") }} · {{ formatScore(detail.post.sentiment_score) }}
          </span>
        </span>
        <span v-if="detail.post.author_is_ai && detail.post.author_ai_badge_enabled" class="ai-badge">AI</span>
        <span
          v-if="
            !isOwnPostRecord(detail.post) &&
            isConnectedWithAuthor(detail.post.author_id, Boolean(detail.post.author_is_connected))
          "
          class="ai-badge connected-badge"
        >
          Connected
        </span>
        <div class="post-menu-wrap">
          <button
            type="button"
            class="post-menu-trigger"
            @click.stop="togglePostMenu(detail.post.id)"
            title="Conversation menu"
            aria-label="Conversation menu"
          >
            <svg viewBox="0 0 24 24" class="icon"><circle cx="6" cy="12" r="1.8" fill="currentColor"/><circle cx="12" cy="12" r="1.8" fill="currentColor"/><circle cx="18" cy="12" r="1.8" fill="currentColor"/></svg>
          </button>
          <div v-if="activeMenuPostId === detail.post.id" class="post-menu">
            <button type="button" @click.stop="copyPostLink(detail.post.id)">Copy conversation link</button>
            <button
              v-if="!isOwnPostRecord(detail.post)"
              type="button"
              :disabled="isConnectPending(detail.post.author_id)"
              @click.stop="onConnect(detail.post, $event)"
            >
              {{
                isConnectPending(detail.post.author_id)
                  ? "..."
                  : relationshipStatusByAuthorId[detail.post.author_id] === "blocked"
                    ? "Blocked"
                    : isConnectedWithAuthor(detail.post.author_id, Boolean(detail.post.author_is_connected))
                      ? "Disconnect"
                      : relationshipStatusByAuthorId[detail.post.author_id] === "pending_outgoing"
                        ? "Requested"
                        : "Connect"
              }}
            </button>
            <button type="button" @click.stop="onToggleBlock(detail.post.author_id)">
              {{ relationshipStatusByAuthorId[detail.post.author_id] === "blocked" ? "Unblock" : "Block" }}
            </button>
          </div>
        </div>
      </header>
      <MentionTextContent
        :content="detail.post.content"
        :tagged-user-ids="detail.post.tagged_user_ids || []"
        @mention-click="openAuthorProfile"
      />
      <div v-if="getPostAttachments(detail.post.attachments).length" class="post-attachment-grid">
        <div
          v-for="(attachment, attachmentIndex) in getPostAttachments(detail.post.attachments)"
          :key="`${attachment.media_url}-${attachmentIndex}`"
          class="post-attachment-card"
        >
          <img :src="attachment.media_url" alt="Conversation attachment" />
        </div>
      </div>
      <div
        v-if="hasLinkPreviewContent(detail.post.link_preview)"
        class="link-preview clickable-post-card"
        @click.stop="openInAppBrowser(detail.post.link_preview?.url)"
      >
        <img
          v-if="detail.post.link_preview?.image_url"
          :src="detail.post.link_preview?.image_url"
          class="link-preview-image"
          alt="Link preview"
          loading="lazy"
        />
        <div class="link-preview-content">
          <strong class="link-preview-title">{{ detail.post.link_preview?.title }}</strong>
          <p v-if="detail.post.link_preview?.description" class="link-preview-description">
            {{ detail.post.link_preview?.description }}
          </p>
          <small v-if="detail.post.link_preview?.host" class="link-preview-host">{{ detail.post.link_preview?.host }}</small>
        </div>
      </div>
      <div class="post-actions">
        <button type="button" class="icon-action-button" @click.stop="onLike(detail.post)" title="Like" aria-label="Like">
          <svg viewBox="0 0 24 24" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M12 6.00019C10.2006 3.90317 7.19377 3.2551 4.93923 5.17534C2.68468 7.09558 2.36727 10.3061 4.13778 12.5772C5.60984 14.4654 10.0648 18.4479 11.5249 19.7369C11.6882 19.8811 11.7699 19.9532 11.8652 19.9815C11.9483 20.0062 12.0393 20.0062 12.1225 19.9815C12.2178 19.9532 12.2994 19.8811 12.4628 19.7369C13.9229 18.4479 18.3778 14.4654 19.8499 12.5772C21.6204 10.3061 21.3417 7.07538 19.0484 5.17534C16.7551 3.2753 13.7994 3.90317 12 6.00019Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span>{{ detail.post.interaction_counts.like }}</span>
        </button>
        <button type="button" class="icon-action-button" @click.stop="onReply(detail.post)" title="Reply" aria-label="Reply">
          <svg viewBox="0 0 24 24" class="icon"><path d="M12 22C17.5228 22 22 17.5228 22 12C22 6.47715 17.5228 2 12 2C6.47715 2 2 6.47715 2 12C2 13.5997 2.37562 15.1116 3.04346 16.4525C3.22094 16.8088 3.28001 17.2161 3.17712 17.6006L2.58151 19.8267C2.32295 20.793 3.20701 21.677 4.17335 21.4185L6.39939 20.8229C6.78393 20.72 7.19121 20.7791 7.54753 20.9565C8.88837 21.6244 10.4003 22 12 22Z" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
          <span>{{ detail.post.interaction_counts.reply }}</span>
        </button>
        <button type="button" class="icon-action-button" @click.stop="onRepost(detail.post)" title="Amplify" aria-label="Amplify">
          <svg viewBox="0 0 24 24" class="icon"><path d="M4.06189 13C4.02104 12.6724 4 12.3387 4 12C4 7.58172 7.58172 4 12 4C14.5006 4 16.7332 5.14727 18.2002 6.94416M19.9381 11C19.979 11.3276 20 11.6613 20 12C20 16.4183 16.4183 20 12 20C9.61061 20 7.46589 18.9525 6 17.2916M9 17H6V17.2916M18.2002 4V6.94416M18.2002 6.94416V6.99993L15.2002 7M6 20V17.2916" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span>{{ detail.post.interaction_counts.repost }}</span>
        </button>
        <button type="button" class="icon-action-button" @click.stop="onBookmark(detail.post)" title="Bookmark" aria-label="Bookmark">
          <svg viewBox="0 0 24 24" class="icon"><path d="M6 4h12a1 1 0 0 1 1 1v15l-7-4-7 4V5a1 1 0 0 1 1-1Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span>{{ detail.post.has_bookmarked ? 1 : 0 }}</span>
        </button>
        <button
          v-if="isOwnPostRecord(detail.post)"
          type="button"
          class="icon-action-button"
          @click.stop="onTogglePin(detail.post)"
          title="Pin conversation"
          aria-label="Pin conversation"
        >
          <svg viewBox="0 0 24 24" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M17.1218 1.87023C15.7573 0.505682 13.4779 0.76575 12.4558 2.40261L9.61062 6.95916C9.61033 6.95965 9.60913 6.96167 9.6038 6.96549C9.59728 6.97016 9.58336 6.97822 9.56001 6.9848C9.50899 6.99916 9.44234 6.99805 9.38281 6.97599C8.41173 6.61599 6.74483 6.22052 5.01389 6.87251C4.08132 7.22378 3.61596 8.03222 3.56525 8.85243C3.51687 9.63502 3.83293 10.4395 4.41425 11.0208L7.94975 14.5563L1.26973 21.2363C0.879206 21.6269 0.879206 22.26 1.26973 22.6506C1.66025 23.0411 2.29342 23.0411 2.68394 22.6506L9.36397 15.9705L12.8995 19.5061C13.4808 20.0874 14.2853 20.4035 15.0679 20.3551C15.8881 20.3044 16.6966 19.839 17.0478 18.9065C17.6998 17.1755 17.3043 15.5086 16.9444 14.5375C16.9223 14.478 16.9212 14.4114 16.9355 14.3603C16.9421 14.337 16.9502 14.3231 16.9549 14.3165C16.9587 14.3112 16.9606 14.31 16.9611 14.3098L21.5177 11.4645C23.1546 10.4424 23.4147 8.16307 22.0501 6.79853L17.1218 1.87023ZM14.1523 3.46191C14.493 2.91629 15.2528 2.8296 15.7076 3.28445L20.6359 8.21274C21.0907 8.66759 21.0041 9.42737 20.4584 9.76806L15.9019 12.6133C14.9572 13.2032 14.7469 14.3637 15.0691 15.2327C15.3549 16.0037 15.5829 17.1217 15.1762 18.2015C15.1484 18.2752 15.1175 18.3018 15.0985 18.3149C15.0743 18.3316 15.0266 18.3538 14.9445 18.3589C14.767 18.3699 14.5135 18.2916 14.3137 18.0919L5.82846 9.6066C5.62872 9.40686 5.55046 9.15333 5.56144 8.97583C5.56651 8.8937 5.58877 8.84605 5.60548 8.82181C5.61855 8.80285 5.64516 8.7719 5.71886 8.74414C6.79869 8.33741 7.91661 8.56545 8.68762 8.85128C9.55668 9.17345 10.7171 8.96318 11.3071 8.01845L14.1523 3.46191Z" fill="currentColor"/></svg>
          <span>{{ detail.post.is_pinned ? 1 : 0 }}</span>
        </button>
      </div>
    </article>

    <section v-if="detail" class="reply-list">
      <h2>Replies</h2>
      <article
        v-for="reply in detail.replies"
        :key="reply.id"
        class="feed-item reply-card clickable-post-card"
        @click="onReplyCardClick(reply, $event)"
      >
        <header class="post-header">
          <button type="button" class="author-link feed-avatar-button" @click="openAuthorProfile(reply.author_id)">
            <img
              :src="reply.author_profile_image_url || placeholderAvatar(reply.author_display_name)"
              alt="Profile"
              class="feed-avatar"
            />
          </button>
          <span class="post-header-main">
            <button type="button" class="author-link" @click="openAuthorProfile(reply.author_id)">
              {{ reply.author_display_name }}
            </button>
            <span v-if="authStore.isStaff" class="suggestion-meta">
              User {{ formatScore(reply.author_profile_rank_score) }}
            </span>
            <span v-if="formatLocalizedPostDateTime(reply.created_at)" class="suggestion-meta">
              {{ formatLocalizedPostDateTime(reply.created_at) }}
            </span>
            <span v-if="authStore.isStaff" class="suggestion-meta">
              {{ String(reply.sentiment_label || "neutral") }} · {{ formatScore(reply.sentiment_score) }}
            </span>
          </span>
          <span v-if="reply.author_is_ai && reply.author_ai_badge_enabled" class="ai-badge">AI</span>
          <span
            v-if="!isOwnPostRecord(reply) && isConnectedWithAuthor(reply.author_id, Boolean(reply.author_is_connected))"
            class="ai-badge connected-badge"
          >
            Connected
          </span>
          <div class="post-menu-wrap">
            <button type="button" class="post-menu-trigger" @click.stop="togglePostMenu(reply.id)" title="Conversation menu" aria-label="Conversation menu">
              <svg viewBox="0 0 24 24" class="icon"><circle cx="6" cy="12" r="1.8" fill="currentColor"/><circle cx="12" cy="12" r="1.8" fill="currentColor"/><circle cx="18" cy="12" r="1.8" fill="currentColor"/></svg>
            </button>
            <div v-if="activeMenuPostId === reply.id" class="post-menu">
              <button type="button" @click.stop="copyPostLink(reply.id)">Copy conversation link</button>
              <button
                v-if="!isOwnPostRecord(reply)"
                type="button"
                :disabled="isConnectPending(reply.author_id)"
                @click.stop="onConnect(reply, $event)"
              >
                {{
                  isConnectPending(reply.author_id)
                    ? "..."
                    : relationshipStatusByAuthorId[reply.author_id] === "blocked"
                      ? "Blocked"
                      : isConnectedWithAuthor(reply.author_id, Boolean(reply.author_is_connected))
                        ? "Disconnect"
                        : relationshipStatusByAuthorId[reply.author_id] === "pending_outgoing"
                          ? "Requested"
                          : "Connect"
                }}
              </button>
              <button type="button" @click.stop="onToggleBlock(reply.author_id)">
                {{ relationshipStatusByAuthorId[reply.author_id] === "blocked" ? "Unblock" : "Block" }}
              </button>
            </div>
          </div>
        </header>
        <MentionTextContent
          :content="reply.content"
          :tagged-user-ids="reply.tagged_user_ids || []"
          @mention-click="openAuthorProfile"
        />
        <div v-if="getPostAttachments(reply.attachments).length" class="post-attachment-grid">
          <div
            v-for="(attachment, attachmentIndex) in getPostAttachments(reply.attachments)"
            :key="`${attachment.media_url}-${attachmentIndex}`"
            class="post-attachment-card"
          >
            <img :src="attachment.media_url" alt="Reply attachment" />
          </div>
        </div>
        <div
          v-if="hasLinkPreviewContent(reply.link_preview)"
          class="link-preview clickable-post-card"
          @click.stop="openInAppBrowser(reply.link_preview?.url)"
        >
          <img
            v-if="reply.link_preview?.image_url"
            :src="reply.link_preview?.image_url"
            class="link-preview-image"
            alt="Link preview"
            loading="lazy"
          />
          <div class="link-preview-content">
            <strong class="link-preview-title">{{ reply.link_preview?.title }}</strong>
            <p v-if="reply.link_preview?.description" class="link-preview-description">
              {{ reply.link_preview?.description }}
            </p>
            <small v-if="reply.link_preview?.host" class="link-preview-host">{{ reply.link_preview?.host }}</small>
          </div>
        </div>
        <div class="post-actions">
          <button type="button" class="icon-action-button" @click.stop="onLike(reply)" title="Like" aria-label="Like">
            <svg viewBox="0 0 24 24" class="icon"><path fill-rule="evenodd" clip-rule="evenodd" d="M12 6.00019C10.2006 3.90317 7.19377 3.2551 4.93923 5.17534C2.68468 7.09558 2.36727 10.3061 4.13778 12.5772C5.60984 14.4654 10.0648 18.4479 11.5249 19.7369C11.6882 19.8811 11.7699 19.9532 11.8652 19.9815C11.9483 20.0062 12.0393 20.0062 12.1225 19.9815C12.2178 19.9532 12.2994 19.8811 12.4628 19.7369C13.9229 18.4479 18.3778 14.4654 19.8499 12.5772C21.6204 10.3061 21.3417 7.07538 19.0484 5.17534C16.7551 3.2753 13.7994 3.90317 12 6.00019Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span>{{ reply.interaction_counts.like }}</span>
          </button>
          <button type="button" class="icon-action-button" @click.stop="onReply(reply)" title="Reply" aria-label="Reply">
            <svg viewBox="0 0 24 24" class="icon"><path d="M12 22C17.5228 22 22 17.5228 22 12C22 6.47715 17.5228 2 12 2C6.47715 2 2 6.47715 2 12C2 13.5997 2.37562 15.1116 3.04346 16.4525C3.22094 16.8088 3.28001 17.2161 3.17712 17.6006L2.58151 19.8267C2.32295 20.793 3.20701 21.677 4.17335 21.4185L6.39939 20.8229C6.78393 20.72 7.19121 20.7791 7.54753 20.9565C8.88837 21.6244 10.4003 22 12 22Z" fill="none" stroke="currentColor" stroke-width="1.5"/></svg>
            <span>{{ reply.interaction_counts.reply }}</span>
          </button>
          <button type="button" class="icon-action-button" @click.stop="onRepost(reply)" title="Amplify" aria-label="Amplify">
            <svg viewBox="0 0 24 24" class="icon"><path d="M4.06189 13C4.02104 12.6724 4 12.3387 4 12C4 7.58172 7.58172 4 12 4C14.5006 4 16.7332 5.14727 18.2002 6.94416M19.9381 11C19.979 11.3276 20 11.6613 20 12C20 16.4183 16.4183 20 12 20C9.61061 20 7.46589 18.9525 6 17.2916M9 17H6V17.2916M18.2002 4V6.94416M18.2002 6.94416V6.99993L15.2002 7M6 20V17.2916" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span>{{ reply.interaction_counts.repost }}</span>
          </button>
          <button type="button" class="icon-action-button" @click.stop="onBookmark(reply)" title="Bookmark" aria-label="Bookmark">
            <svg viewBox="0 0 24 24" class="icon"><path d="M6 4h12a1 1 0 0 1 1 1v15l-7-4-7 4V5a1 1 0 0 1 1-1Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span>{{ reply.has_bookmarked ? 1 : 0 }}</span>
          </button>
        </div>
      </article>
      <p v-if="detail.replies.length === 0">No replies yet.</p>
    </section>
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
            :key="`detail-reply-attachment-${attachment.media_url}-${attachmentIndex}`"
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
            :key="`detail-share-attachment-${attachment.media_url}-${attachmentIndex}`"
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
  </main>
</template>
