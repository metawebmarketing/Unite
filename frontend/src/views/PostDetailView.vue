<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { connectToUser, disconnectFromUser } from "../api/connections";
import { fetchPostDetail, reactToPost, togglePostPin, type PostDetailResponse } from "../api/posts";
import { useAuthStore } from "../stores/auth";
import { useFeedStore } from "../stores/feed";

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();
const feedStore = useFeedStore();
const detail = ref<PostDetailResponse | null>(null);
const isLoading = ref(false);
const errorText = ref("");
const activeMenuPostId = ref<number | null>(null);
const showReplyModal = ref(false);
const replyDraft = ref("");
const replyTargetPostId = ref<number | null>(null);
const showCopyLinkModal = ref(false);
const copyLinkFallbackValue = ref("");
const connectionStatusByAuthorId = ref<Record<number, boolean>>({});
const pendingConnectionUserIds = ref<number[]>([]);

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

async function loadPost() {
  const postId = Number(route.params.postId);
  if (!Number.isInteger(postId) || postId <= 0) {
    errorText.value = "Invalid post.";
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
    } else {
      errorText.value = "Unable to load this post. If this keeps happening, refresh and retry.";
    }
    detail.value = null;
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
  const previousCount = target.interaction_counts.repost;
  target.interaction_counts.repost = previousCount > 0 ? Math.max(0, previousCount - 1) : previousCount + 1;
  try {
    await reactToPost(target.id, { action: "repost" });
  } catch {
    target.interaction_counts.repost = previousCount;
  }
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
  replyDraft.value = "";
  showReplyModal.value = true;
}

async function submitReplyModal() {
  const postId = replyTargetPostId.value;
  if (!postId || !replyDraft.value.trim()) {
    return;
  }
  try {
    await reactToPost(postId, { action: "reply", content: replyDraft.value.trim() });
    showReplyModal.value = false;
    replyTargetPostId.value = null;
    replyDraft.value = "";
    await loadPost();
  } catch {
    // Keep current state untouched when reply fails.
  }
}

function closeReplyModal() {
  showReplyModal.value = false;
  replyTargetPostId.value = null;
  replyDraft.value = "";
}

function closeCopyLinkModal() {
  showCopyLinkModal.value = false;
  copyLinkFallbackValue.value = "";
}

onMounted(() => {
  feedStore.hydrateBlockedUsers();
  void loadPost();
});

watch(
  () => route.params.postId,
  () => {
    void loadPost();
  },
);
</script>

<template>
  <main class="post-detail-page">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 24 24" class="icon"><path d="M15 5 8 12l7 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <p v-if="isLoading">Loading post...</p>
    <p v-else-if="errorText">{{ errorText }}</p>
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
          <button type="button" class="author-username-link" @click="openAuthorProfile(detail.post.author_id)">
            @{{ detail.post.author_username }}
          </button>
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
      <p>{{ detail.post.content }}</p>
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
            <button type="button" class="author-username-link" @click="openAuthorProfile(reply.author_id)">
              @{{ reply.author_username }}
            </button>
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
        <p>{{ reply.content }}</p>
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
  </main>
</template>
