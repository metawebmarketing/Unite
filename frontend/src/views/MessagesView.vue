<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { fetchDMThreadUserSuggestions, fetchDMUserSuggestions, type DMUserSuggestion } from "../api/messages";
import { useErrorModalStore } from "../stores/error-modal";
import { useMessagesStore } from "../stores/messages";
import { formatLocalizedPostDateTime } from "../utils/date-display";

const router = useRouter();
const messagesStore = useMessagesStore();
const errorModalStore = useErrorModalStore();
const loadMoreAnchor = ref<HTMLElement | null>(null);
const recipientWrapRef = ref<HTMLElement | null>(null);
const fromProfileWrapRef = ref<HTMLElement | null>(null);
const searchText = ref("");
const fromProfileFilter = ref("");
const fromProfileDraft = ref("");
const afterDateFilter = ref("");
const beforeDateFilter = ref("");
const showFilterModal = ref(false);
const recipientUsernameDraft = ref("");
const selectedRecipientId = ref<number | null>(null);
const suggestions = ref<DMUserSuggestion[]>([]);
const filterSuggestions = ref<DMUserSuggestion[]>([]);
const isLoadingSuggestions = ref(false);
const isLoadingFilterSuggestions = ref(false);
const showRecipientSuggestionBox = ref(false);
const showFilterSuggestionBox = ref(false);
const isRecipientInputFocused = ref(false);
const isFromProfileInputFocused = ref(false);
const isStartingThread = ref(false);
let observer: IntersectionObserver | null = null;
let filterTimer: ReturnType<typeof setTimeout> | null = null;
let suggestionTimer: ReturnType<typeof setTimeout> | null = null;
let filterSuggestionTimer: ReturnType<typeof setTimeout> | null = null;

function placeholderAvatar(name: string) {
  const initial = (name || "U").trim().charAt(0).toUpperCase() || "U";
  return `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><rect width="100%" height="100%" fill="#1c2440"/><text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" fill="#d8def9" font-size="22" font-family="Arial">${initial}</text></svg>`,
  )}`;
}

function goBack() {
  void router.push({ name: "feed" });
}

function openThread(threadId: number) {
  void router.push({ name: "message-thread", params: { threadId } });
}

async function loadThreads(reset = false) {
  try {
    await messagesStore.loadThreads(reset, {
      search: searchText.value.trim(),
      fromProfile: fromProfileFilter.value.trim(),
      afterDate: afterDateFilter.value,
      beforeDate: beforeDateFilter.value,
    });
  } catch {
    errorModalStore.showError("Unable to load messages.");
  }
}

function scheduleFilterReload() {
  if (filterTimer) {
    clearTimeout(filterTimer);
  }
  filterTimer = setTimeout(() => {
    void loadThreads(true);
  }, 360);
}

function clearFilters() {
  searchText.value = "";
  fromProfileFilter.value = "";
  fromProfileDraft.value = "";
  filterSuggestions.value = [];
  afterDateFilter.value = "";
  beforeDateFilter.value = "";
}

async function startThread() {
  const username = recipientUsernameDraft.value.trim().toLowerCase();
  let recipientId = selectedRecipientId.value;
  if (!recipientId && username) {
    const exact = suggestions.value.find((item) => item.username.toLowerCase() === username);
    recipientId = exact?.user_id || null;
  }
  if (!recipientId || recipientId <= 0) {
    errorModalStore.showError("Select a valid username from suggestions.");
    return;
  }
  isStartingThread.value = true;
  try {
    const threadId = await messagesStore.ensureThread(recipientId);
    recipientUsernameDraft.value = "";
    selectedRecipientId.value = null;
    showRecipientSuggestionBox.value = false;
    openThread(threadId);
  } catch {
    errorModalStore.showError("Unable to start conversation with that user.");
  } finally {
    isStartingThread.value = false;
  }
}

async function selectRecipientSuggestion(suggestion: DMUserSuggestion) {
  recipientUsernameDraft.value = suggestion.username;
  selectedRecipientId.value = suggestion.user_id;
  showRecipientSuggestionBox.value = false;
  await startThread();
}

function scheduleSuggestionFetch() {
  if (suggestionTimer) {
    clearTimeout(suggestionTimer);
  }
  suggestionTimer = setTimeout(async () => {
    const query = recipientUsernameDraft.value.trim();
    if (query.length < 3) {
      showRecipientSuggestionBox.value = false;
      selectedRecipientId.value = null;
      return;
    }
    showRecipientSuggestionBox.value = isRecipientInputFocused.value;
    isLoadingSuggestions.value = true;
    try {
      suggestions.value = await fetchDMUserSuggestions(query, 50);
      if (!suggestions.value.some((item) => item.user_id === selectedRecipientId.value)) {
        selectedRecipientId.value = null;
      }
    } catch {
      suggestions.value = [];
    } finally {
      isLoadingSuggestions.value = false;
    }
  }, 250);
}

function closeFilterModal() {
  showFilterModal.value = false;
  filterSuggestions.value = [];
}

function onDocumentPointerDown(event: MouseEvent) {
  const targetNode = event.target as Node | null;
  if (!targetNode) {
    return;
  }
  if (recipientWrapRef.value && !recipientWrapRef.value.contains(targetNode)) {
    isRecipientInputFocused.value = false;
    showRecipientSuggestionBox.value = false;
  }
  if (fromProfileWrapRef.value && !fromProfileWrapRef.value.contains(targetNode)) {
    isFromProfileInputFocused.value = false;
    showFilterSuggestionBox.value = false;
  }
}

function selectFromProfileSuggestion(suggestion: DMUserSuggestion) {
  fromProfileDraft.value = suggestion.username;
  fromProfileFilter.value = suggestion.username;
  filterSuggestions.value = [];
}

function scheduleFilterSuggestionFetch() {
  if (filterSuggestionTimer) {
    clearTimeout(filterSuggestionTimer);
  }
  filterSuggestionTimer = setTimeout(async () => {
    const query = fromProfileDraft.value.trim();
    if (query.length < 3) {
      showFilterSuggestionBox.value = false;
      return;
    }
    showFilterSuggestionBox.value = isFromProfileInputFocused.value;
    isLoadingFilterSuggestions.value = true;
    try {
      filterSuggestions.value = await fetchDMThreadUserSuggestions(query, 50);
    } catch {
      filterSuggestions.value = [];
    } finally {
      isLoadingFilterSuggestions.value = false;
    }
  }, 250);
}

const hasAnyFilters = computed(
  () => Boolean(searchText.value || fromProfileFilter.value || afterDateFilter.value || beforeDateFilter.value),
);
const threads = computed(() => messagesStore.threads);
const isLoading = computed(() => messagesStore.isLoadingThreads);
const hasMore = computed(() => messagesStore.threadsHasMore);

onMounted(async () => {
  document.addEventListener("mousedown", onDocumentPointerDown);
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting && hasMore.value && !isLoading.value) {
        void loadThreads(false);
      }
    },
    { threshold: 0.4 },
  );
  if (loadMoreAnchor.value) {
    observer.observe(loadMoreAnchor.value);
  }
  await loadThreads(true);
});

onUnmounted(() => {
  document.removeEventListener("mousedown", onDocumentPointerDown);
  if (observer) {
    observer.disconnect();
  }
  if (filterTimer) {
    clearTimeout(filterTimer);
  }
  if (suggestionTimer) {
    clearTimeout(suggestionTimer);
  }
  if (filterSuggestionTimer) {
    clearTimeout(filterSuggestionTimer);
  }
  document.body.style.overflow = "";
});

watch([searchText, fromProfileFilter, afterDateFilter, beforeDateFilter], () => {
  scheduleFilterReload();
});

watch(recipientUsernameDraft, () => {
  scheduleSuggestionFetch();
});

watch(fromProfileDraft, () => {
  fromProfileFilter.value = fromProfileDraft.value.trim();
  scheduleFilterSuggestionFetch();
});

watch(showFilterModal, (value) => {
  if (value) {
    fromProfileDraft.value = fromProfileFilter.value;
  } else {
    isFromProfileInputFocused.value = false;
    showFilterSuggestionBox.value = false;
  }
  document.body.style.overflow = value ? "hidden" : "";
});

function onRecipientInputFocus() {
  isRecipientInputFocused.value = true;
  if (recipientUsernameDraft.value.trim().length >= 3) {
    showRecipientSuggestionBox.value = true;
  }
}

function onFromProfileInputFocus() {
  isFromProfileInputFocused.value = true;
  if (fromProfileDraft.value.trim().length >= 3) {
    showFilterSuggestionBox.value = true;
  }
}
</script>

<template>
  <main class="post-detail-page">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 24 24" class="icon"><path d="M15 5 8 12l7 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <h1 class="feed-title">Messages</h1>
    <section class="feed-item connections-card">
      <div class="search-input-row">
        <svg viewBox="0 0 24 24" class="icon"><circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="m16 16 4 4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        <input v-model="searchText" type="text" placeholder="Search messages" />
        <button type="button" class="icon-only-button small-round-button" @click="showFilterModal = true">
          <svg viewBox="0 0 24 24" class="icon"><path d="M6 8h12M8 12h8M10 16h4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        </button>
      </div>
      <div class="dm-start-thread-row">
        <div ref="recipientWrapRef" class="dm-recipient-wrap">
          <input
            v-model="recipientUsernameDraft"
            type="text"
            placeholder="Username"
            autocomplete="off"
            @focus="onRecipientInputFocus"
          />
          <div v-if="showRecipientSuggestionBox" class="dm-suggestion-box">
            <p v-if="isLoadingSuggestions" class="suggestion-meta">Loading...</p>
            <button
              v-for="suggestion in suggestions"
              :key="suggestion.user_id"
              type="button"
              class="dm-suggestion-item"
              @click="selectRecipientSuggestion(suggestion)"
            >
              <span>@{{ suggestion.username }}</span>
              <span class="suggestion-meta">
                {{ suggestion.display_name }}
                <span v-if="suggestion.is_connected"> · Connected</span>
              </span>
            </button>
            <p v-if="!isLoadingSuggestions && suggestions.length === 0" class="suggestion-meta">
              No matches.
            </p>
          </div>
        </div>
        <button type="button" :disabled="isStartingThread" @click="startThread">
          {{ isStartingThread ? "Starting..." : "Start thread" }}
        </button>
      </div>
    </section>

    <article
      v-for="thread in threads"
      :key="thread.thread_id"
      class="feed-item clickable-post-card dm-thread-card"
      @click="openThread(thread.thread_id)"
    >
      <header class="post-header">
        <img
          :src="thread.other_profile_image_url || placeholderAvatar(thread.other_display_name)"
          alt="Profile"
          class="feed-avatar"
        />
        <span class="post-header-main">
          <strong>{{ thread.other_display_name || thread.other_username }}</strong>
          <span class="suggestion-meta">
            @{{ thread.other_username }}
            <span v-if="formatLocalizedPostDateTime(thread.latest_message_at)">
              · {{ formatLocalizedPostDateTime(thread.latest_message_at) }}
            </span>
          </span>
        </span>
        <span v-if="thread.unread_count > 0" class="dm-unread-pill">{{ thread.unread_count }}</span>
      </header>
      <p class="dm-thread-preview">{{ thread.latest_message_preview || "No messages yet." }}</p>
    </article>

    <div ref="loadMoreAnchor" class="feed-status">
      <p v-if="isLoading">Loading...</p>
      <p v-else-if="hasMore">Scroll to load more</p>
      <p v-else-if="threads.length">End of messages</p>
      <p v-else>No direct messages yet.</p>
    </div>

    <div v-if="showFilterModal" class="modal-overlay" @click.self="closeFilterModal">
      <section class="auth-card modal-card mention-host-card filter-modal-card">
        <h2>Filter messages</h2>
        <label class="connections-filter-row">
          <span>After date</span>
          <input v-model="afterDateFilter" type="date" />
        </label>
        <label class="connections-filter-row">
          <span>Before date</span>
          <input v-model="beforeDateFilter" type="date" />
        </label>
        <label class="connections-filter-row">
          <span>From profile</span>
          <div ref="fromProfileWrapRef" class="dm-recipient-wrap">
            <input
              v-model="fromProfileDraft"
              type="text"
              placeholder="Username"
              autocomplete="off"
              @focus="onFromProfileInputFocus"
            />
            <div v-if="showFilterSuggestionBox" class="dm-suggestion-box">
              <p v-if="isLoadingFilterSuggestions" class="suggestion-meta">Loading...</p>
              <button
                v-for="suggestion in filterSuggestions"
                :key="`filter-${suggestion.user_id}`"
                type="button"
                class="dm-suggestion-item"
                @click="selectFromProfileSuggestion(suggestion)"
              >
                <span>@{{ suggestion.username }}</span>
                <span class="suggestion-meta">{{ suggestion.display_name }}</span>
              </button>
              <p v-if="!isLoadingFilterSuggestions && filterSuggestions.length === 0" class="suggestion-meta">
                No matches.
              </p>
            </div>
          </div>
        </label>
        <div class="modal-actions">
          <button v-if="hasAnyFilters" type="button" @click="clearFilters">Clear filters</button>
          <button type="button" @click="closeFilterModal">Close</button>
        </div>
      </section>
    </div>
  </main>
</template>
