<script setup lang="ts">
import { defineAsyncComponent, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { connectToUser, disconnectFromUser } from "../api/connections";
import { fetchPostDetail, reactToPost, togglePostPin, uploadPostImage, type PostDetailResponse } from "../api/posts";
import { useAuthStore } from "../stores/auth";
import { useErrorModalStore } from "../stores/error-modal";
import { useFeedStore } from "../stores/feed";
import { formatLocalizedPostDateTime } from "../utils/date-display";

const MentionComposerInput = defineAsyncComponent(async () => {
  const componentModule = await import("../components/MentionComposerInput.vue");
  return (componentModule as { default?: unknown }).default || componentModule;
});

const MentionTextContent = defineAsyncComponent(async () => {
  const componentModule = await import("../components/MentionTextContent.vue");
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
const connectionStatusByAuthorId = ref<Record<number, boolean>>({});
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
  const preview = linkPreview as { title?: string; description?: string; host?: string; url?: string };
  return Boolean(preview.title || preview.description || preview.host || preview.url);
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
    errorText.value = "Invalid post.";
    errorModalStore.showError("Invalid post.");
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
      errorText.value = "Rate limited while loading this post. Please wait a few seconds and retry.";
      errorModalStore.showError("Rate limited while loading this post. Please wait a few seconds and retry.");
    } else {
      errorText.value = "Unable to load this post. If this keeps happening, refresh and retry.";
      errorModalStore.showError("Unable to load this post. If this keeps happening, refresh and retry.");
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

function blockAuthor(authorId: number) {
  feedStore.hydrateBlockedUsers();
  feedStore.blockAuthor(authorId);
  activeMenuPostId.value = null;
  void router.push({ name: "feed" });
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
    if (isConnectedWithAuthor(post.author_id, Boolean(post.author_is_connected))) {
      await disconnectFromUser(post.author_id);
      setConnectedForAuthor(post.author_id, false);
    } else {
      await connectToUser(post.author_id);
      setConnectedForAuthor(post.author_id, true);
    }
  } catch {
    // Ignore connection failures for now.
  } finally {
    pendingConnectionUserIds.value = pendingConnectionUserIds.value.filter((value) => value !== post.author_id);
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
      link_url: replyLinkDraft.value.trim() || undefined,
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
    link_url: shareLinkDraft.value.trim() || undefined,
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
  [showReplyModal, showShareModal, showCopyLinkModal],
  ([replyModalValue, shareModalValue, copyModalValue]) => {
    document.body.style.overflow = replyModalValue || shareModalValue || copyModalValue ? "hidden" : "";
  },
  { immediate: true },
);
</script>

<template>
  <main class="post-detail-page">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 24 24" class="icon"><path d="M15 5 8 12l7 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <p v-if="isLoading">Loading post...</p>
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
            title="Post menu"
            aria-label="Post menu"
          >
            <svg viewBox="0 0 24 24" class="icon"><circle cx="6" cy="12" r="1.8" fill="currentColor"/><circle cx="12" cy="12" r="1.8" fill="currentColor"/><circle cx="18" cy="12" r="1.8" fill="currentColor"/></svg>
          </button>
          <div v-if="activeMenuPostId === detail.post.id" class="post-menu">
            <button type="button" @click.stop="copyPostLink(detail.post.id)">Copy post link</button>
            <button
              v-if="!isOwnPostRecord(detail.post)"
              type="button"
              :disabled="isConnectPending(detail.post.author_id)"
              @click.stop="onConnect(detail.post, $event)"
            >
              {{
                isConnectPending(detail.post.author_id)
                  ? "..."
                  : isConnectedWithAuthor(detail.post.author_id, Boolean(detail.post.author_is_connected))
                    ? "Disconnect"
                    : "Connect"
              }}
            </button>
            <button type="button" @click.stop="blockAuthor(detail.post.author_id)">Block user</button>
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
          <img :src="attachment.media_url" alt="Post attachment" />
        </div>
      </div>
      <div v-if="hasLinkPreviewContent(detail.post.link_preview)" class="link-preview">
        <strong>{{ detail.post.link_preview?.title }}</strong>
        <p>{{ detail.post.link_preview?.description }}</p>
        <small>{{ detail.post.link_preview?.host }}</small>
      </div>
      <div class="post-actions">
        <button type="button" class="icon-action-button" @click.stop="onLike(detail.post)" title="Like" aria-label="Like">
          <svg viewBox="0 0 24 24" class="icon"><path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span>{{ detail.post.interaction_counts.like }}</span>
        </button>
        <button type="button" class="icon-action-button" @click.stop="onReply(detail.post)" title="Reply" aria-label="Reply">
          <svg viewBox="0 0 24 24" class="icon"><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H7l-4 3V12a8.5 8.5 0 1 1 18 0Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
          <span>{{ detail.post.interaction_counts.reply }}</span>
        </button>
        <button type="button" class="icon-action-button" @click.stop="onRepost(detail.post)" title="Repost" aria-label="Repost">
          <svg viewBox="0 0 24 24" class="icon"><path d="M7 7h11l-2.5-2.5M17 17H6l2.5 2.5M18 7v6M6 17v-6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
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
          title="Pin post"
          aria-label="Pin post"
        >
          <svg viewBox="0 0 24 24" class="icon"><path d="m8 3 8 8-2 2v6l-2-2-2 2v-6l-2-2 0 0Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
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
            <button type="button" class="post-menu-trigger" @click.stop="togglePostMenu(reply.id)" title="Post menu" aria-label="Post menu">
              <svg viewBox="0 0 24 24" class="icon"><circle cx="6" cy="12" r="1.8" fill="currentColor"/><circle cx="12" cy="12" r="1.8" fill="currentColor"/><circle cx="18" cy="12" r="1.8" fill="currentColor"/></svg>
            </button>
            <div v-if="activeMenuPostId === reply.id" class="post-menu">
              <button type="button" @click.stop="copyPostLink(reply.id)">Copy post link</button>
              <button
                v-if="!isOwnPostRecord(reply)"
                type="button"
                :disabled="isConnectPending(reply.author_id)"
                @click.stop="onConnect(reply, $event)"
              >
                {{
                  isConnectPending(reply.author_id)
                    ? "..."
                    : isConnectedWithAuthor(reply.author_id, Boolean(reply.author_is_connected))
                      ? "Disconnect"
                      : "Connect"
                }}
              </button>
              <button type="button" @click.stop="blockAuthor(reply.author_id)">Block user</button>
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
        <div v-if="hasLinkPreviewContent(reply.link_preview)" class="link-preview">
          <strong>{{ reply.link_preview?.title }}</strong>
          <p>{{ reply.link_preview?.description }}</p>
          <small>{{ reply.link_preview?.host }}</small>
        </div>
        <div class="post-actions">
          <button type="button" class="icon-action-button" @click.stop="onLike(reply)" title="Like" aria-label="Like">
            <svg viewBox="0 0 24 24" class="icon"><path d="M12 20s-7-4.5-7-10a4 4 0 0 1 7-2.5A4 4 0 0 1 19 10c0 5.5-7 10-7 10Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span>{{ reply.interaction_counts.like }}</span>
          </button>
          <button type="button" class="icon-action-button" @click.stop="onReply(reply)" title="Reply" aria-label="Reply">
            <svg viewBox="0 0 24 24" class="icon"><path d="M21 11.5a8.5 8.5 0 0 1-8.5 8.5H7l-4 3V12a8.5 8.5 0 1 1 18 0Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
            <span>{{ reply.interaction_counts.reply }}</span>
          </button>
          <button type="button" class="icon-action-button" @click.stop="onRepost(reply)" title="Repost" aria-label="Repost">
            <svg viewBox="0 0 24 24" class="icon"><path d="M7 7h11l-2.5-2.5M17 17H6l2.5 2.5M18 7v6M6 17v-6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
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
            <svg viewBox="0 0 24 24" class="icon">
              <rect x="3" y="5" width="18" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="1.8" />
              <circle cx="9" cy="10" r="1.8" fill="none" stroke="currentColor" stroke-width="1.8" />
              <path d="m5 17 4.5-4.5L13 16l2.5-2.5L19 17" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
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
            Post reply
          </button>
        </div>
      </section>
    </div>
    <div v-if="showShareModal" class="modal-overlay" @click.self="closeShareModal">
      <section class="auth-card modal-card mention-host-card">
        <h2>Share</h2>
        <MentionComposerInput
          v-model="shareDraft"
          :tagged-user-ids="shareTaggedUserIds"
          placeholder="Add your share text (optional)"
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
            <svg viewBox="0 0 24 24" class="icon">
              <rect x="3" y="5" width="18" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="1.8" />
              <circle cx="9" cy="10" r="1.8" fill="none" stroke="currentColor" stroke-width="1.8" />
              <path d="m5 17 4.5-4.5L13 16l2.5-2.5L19 17" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
            </svg>
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
            <img :src="attachment.media_url" alt="Share attachment" />
          </div>
        </div>
        <p v-if="isShareUploadingImage">Uploading image...</p>
        <input v-model="shareLinkDraft" placeholder="Optional link URL" />
        <div class="modal-actions">
          <button type="button" @click="closeShareModal">Cancel</button>
          <button type="button" :disabled="isShareUploadingImage" @click="submitShareModal">Share</button>
        </div>
      </section>
    </div>
    <div v-if="showCopyLinkModal" class="modal-overlay" @click.self="closeCopyLinkModal">
      <section class="auth-card modal-card">
        <h2>Copy post link</h2>
        <input :value="copyLinkFallbackValue" readonly />
        <div class="modal-actions">
          <button type="button" @click="closeCopyLinkModal">Close</button>
        </div>
      </section>
    </div>
  </main>
</template>
