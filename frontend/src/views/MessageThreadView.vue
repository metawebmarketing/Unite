<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { useErrorModalStore } from "../stores/error-modal";
import { useMessagesStore } from "../stores/messages";
import { formatLocalizedPostDateTime } from "../utils/date-display";

const route = useRoute();
const router = useRouter();
const messagesStore = useMessagesStore();
const errorModalStore = useErrorModalStore();
const messageDraft = ref("");
const linkUrlDraft = ref("");
const attachmentTypeDraft = ref<"image" | "video">("image");
const attachmentUrlDraft = ref("");
const attachmentDrafts = ref<Array<{ media_type: "image" | "video"; media_url: string }>>([]);
const isSending = ref(false);
const isLoading = ref(false);
const messageScrollContainer = ref<HTMLElement | null>(null);
const messageTopAnchor = ref<HTMLElement | null>(null);
let observer: IntersectionObserver | null = null;
const maxMessageChars = 2000;

const threadId = computed(() => Number(route.params.threadId || 0));
const currentUserId = computed(() => Number(messagesStore.currentUserId || 0));
const threadMessages = computed(() => messagesStore.messagesByThreadId[threadId.value] || []);
const orderedMessages = computed(() =>
  [...threadMessages.value].sort((left, right) => {
    const leftTime = new Date(left.created_at).getTime();
    const rightTime = new Date(right.created_at).getTime();
    if (leftTime !== rightTime) {
      return leftTime - rightTime;
    }
    return left.id - right.id;
  }),
);
const hasMore = computed(() => messagesStore.messageHasMoreByThreadId[threadId.value] !== false);
const isLoadingMore = computed(() => Boolean(messagesStore.messageLoadingByThreadId[threadId.value]));
const activeThread = computed(() => messagesStore.threads.find((thread) => thread.thread_id === threadId.value) || null);
const messageCharCount = computed(() => messageDraft.value.length);

function goBack() {
  void router.push({ name: "messages" });
}

function addAttachmentDraft() {
  const url = attachmentUrlDraft.value.trim();
  if (!url) {
    return;
  }
  attachmentDrafts.value = [...attachmentDrafts.value, { media_type: attachmentTypeDraft.value, media_url: url }];
  attachmentUrlDraft.value = "";
}

function removeAttachmentDraft(index: number) {
  attachmentDrafts.value = attachmentDrafts.value.filter((_, itemIndex) => itemIndex !== index);
}

function hasLinkPreviewContent(linkPreview: unknown): boolean {
  if (!linkPreview || typeof linkPreview !== "object") {
    return false;
  }
  const preview = linkPreview as { title?: string; description?: string; host?: string; url?: string };
  return Boolean(preview.title || preview.description || preview.host || preview.url);
}

async function loadThreadMessages(reset = false) {
  if (!Number.isInteger(threadId.value) || threadId.value <= 0) {
    errorModalStore.showError("Invalid message thread.");
    return;
  }
  if (reset) {
    isLoading.value = true;
  }
  try {
    await messagesStore.ensureCurrentUserId();
    if (!messagesStore.threads.length) {
      await messagesStore.loadThreads(true);
    }
    await messagesStore.loadThreadMessages(threadId.value, reset);
  } catch {
    errorModalStore.showError("Unable to load thread messages.");
  } finally {
    if (reset) {
      isLoading.value = false;
      await nextTick();
      if (messageScrollContainer.value) {
        messageScrollContainer.value.scrollTop = messageScrollContainer.value.scrollHeight;
      }
    }
  }
}

async function submitMessage() {
  const content = messageDraft.value.trim();
  if (!content && !linkUrlDraft.value.trim() && attachmentDrafts.value.length === 0) {
    return;
  }
  isSending.value = true;
  try {
    await messagesStore.sendMessage(threadId.value, {
      content,
      link_url: linkUrlDraft.value.trim(),
      attachments: attachmentDrafts.value,
    });
    messageDraft.value = "";
    linkUrlDraft.value = "";
    attachmentDrafts.value = [];
    await nextTick();
    if (messageScrollContainer.value) {
      messageScrollContainer.value.scrollTop = messageScrollContainer.value.scrollHeight;
    }
  } catch {
    errorModalStore.showError("Unable to send message.");
  } finally {
    isSending.value = false;
  }
}

onMounted(async () => {
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting && hasMore.value && !isLoadingMore.value) {
        void loadThreadMessages(false);
      }
    },
    {
      root: messageScrollContainer.value,
      threshold: 0.2,
    },
  );
  if (messageTopAnchor.value) {
    observer.observe(messageTopAnchor.value);
  }
  await loadThreadMessages(true);
});

onUnmounted(() => {
  if (observer) {
    observer.disconnect();
  }
});

watch(
  () => route.params.threadId,
  async () => {
    await loadThreadMessages(true);
  },
);
</script>

<template>
  <main class="post-detail-page dm-thread-page">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 24 24" class="icon"><path d="M15 5 8 12l7 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <h1 class="feed-title">
      {{ activeThread?.other_display_name || "Thread" }}
    </h1>
    <p v-if="activeThread?.other_username" class="suggestion-meta">@{{ activeThread.other_username }}</p>
    <p v-if="isLoading">Loading messages...</p>
    <section ref="messageScrollContainer" class="feed-item dm-thread-scroll">
      <div ref="messageTopAnchor" class="feed-status dm-thread-top-anchor">
        <p v-if="isLoadingMore">Loading older messages...</p>
        <p v-else-if="hasMore">Scroll up for older messages</p>
      </div>
      <article
        v-for="message in orderedMessages"
        :key="message.id"
        class="dm-message-row"
        :class="{ own: message.sender_id === currentUserId }"
      >
        <div class="dm-message-bubble">
          <p v-if="message.content">{{ message.content }}</p>
          <div v-if="message.attachments?.length" class="dm-attachment-list">
            <a
              v-for="(attachment, index) in message.attachments"
              :key="`${message.id}-${index}`"
              :href="attachment.media_url"
              class="dm-attachment-link"
              target="_blank"
              rel="noreferrer"
            >
              {{ attachment.media_type }} attachment
            </a>
          </div>
          <div v-if="hasLinkPreviewContent(message.link_preview)" class="link-preview">
            <strong>{{ message.link_preview?.title }}</strong>
            <p>{{ message.link_preview?.description }}</p>
            <small>{{ message.link_preview?.host }}</small>
          </div>
          <p class="suggestion-meta dm-message-meta">
            <span v-if="formatLocalizedPostDateTime(message.created_at)">
              {{ formatLocalizedPostDateTime(message.created_at) }}
            </span>
            <span v-if="message.sender_id === currentUserId"> · {{ message.status === "read" ? "Read" : "Sent" }}</span>
          </p>
        </div>
      </article>
      <p v-if="!orderedMessages.length" class="feed-status">No messages yet.</p>
    </section>

    <section class="feed-item dm-compose-card">
      <h2>New message</h2>
      <textarea
        v-model="messageDraft"
        :maxlength="maxMessageChars"
        rows="5"
        placeholder="Type your message"
      />
      <p class="suggestion-meta">{{ messageCharCount }} / {{ maxMessageChars }}</p>
      <input v-model="linkUrlDraft" type="url" placeholder="Optional link URL" />
      <div class="dm-attachment-draft-row">
        <select v-model="attachmentTypeDraft">
          <option value="image">Image</option>
          <option value="video">Video</option>
        </select>
        <input v-model="attachmentUrlDraft" type="url" placeholder="Attachment URL" />
        <button type="button" @click="addAttachmentDraft">Add</button>
      </div>
      <ul v-if="attachmentDrafts.length" class="dm-attachment-draft-list">
        <li v-for="(attachment, index) in attachmentDrafts" :key="`${attachment.media_url}-${index}`">
          {{ attachment.media_type }}: {{ attachment.media_url }}
          <button type="button" @click="removeAttachmentDraft(index)">Remove</button>
        </li>
      </ul>
      <div class="modal-actions">
        <button
          type="button"
          :disabled="isSending || (!messageDraft.trim() && !linkUrlDraft.trim() && attachmentDrafts.length === 0)"
          @click="submitMessage"
        >
          {{ isSending ? "Sending..." : "Send" }}
        </button>
      </div>
    </section>
  </main>
</template>
