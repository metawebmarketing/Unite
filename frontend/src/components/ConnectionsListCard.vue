<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import {
  approveConnection,
  connectToUser,
  denyConnection,
  disconnectFromUser,
  fetchConnections,
  fetchPendingConnections,
  type ConnectionListItem,
} from "../api/connections";
import { fetchDMUserSuggestions, type DMUserSuggestion } from "../api/messages";
import { useErrorModalStore } from "../stores/error-modal";

const props = withDefaults(
  defineProps<{
    userId?: number | null;
    title?: string;
    mode?: "connections" | "users";
  }>(),
  {
    userId: null,
    title: "Connections",
    mode: "connections",
  },
);

const router = useRouter();
const errorModalStore = useErrorModalStore();
const items = ref<ConnectionListItem[]>([]);
const nextCursor = ref<string | null>(null);
const hasMore = ref(true);
const isLoading = ref(false);
const errorText = ref("");
const loadMoreAnchor = ref<HTMLElement | null>(null);
const activeMenuUserId = ref<number | null>(null);
const showCopyLinkModal = ref(false);
const copyLinkFallbackValue = ref("");
const searchText = ref("");
const fromProfileFilter = ref("");
const fromProfileDraft = ref("");
const afterDateFilter = ref("");
const beforeDateFilter = ref("");
const isFilterMenuOpen = ref(false);
const pendingItems = ref<ConnectionListItem[]>([]);
const fromProfileWrapRef = ref<HTMLElement | null>(null);
const fromProfileSuggestions = ref<DMUserSuggestion[]>([]);
const showFromProfileSuggestionBox = ref(false);
const isFromProfileInputFocused = ref(false);
const isLoadingFromProfileSuggestions = ref(false);
let observer: IntersectionObserver | null = null;
let filterTimer: ReturnType<typeof setTimeout> | null = null;
let fromProfileSuggestionTimer: ReturnType<typeof setTimeout> | null = null;
const minSearchChars = 3;

const hasAnyFilters = computed(
  () => Boolean(searchText.value || fromProfileFilter.value || afterDateFilter.value || beforeDateFilter.value),
);

function placeholderAvatar(name: string) {
  const initial = (name || "U").trim().charAt(0).toUpperCase() || "U";
  return `data:image/svg+xml;utf8,${encodeURIComponent(
    `<svg xmlns="http://www.w3.org/2000/svg" width="48" height="48"><rect width="100%" height="100%" fill="#1c2440"/><text x="50%" y="54%" dominant-baseline="middle" text-anchor="middle" fill="#d8def9" font-size="22" font-family="Arial">${initial}</text></svg>`,
  )}`;
}

async function loadConnections(reset = false) {
  const trimmedSearch = searchText.value.trim();
  if (props.mode === "users" && trimmedSearch.length < minSearchChars) {
    items.value = [];
    nextCursor.value = null;
    hasMore.value = false;
    errorText.value = "";
    return;
  }
  if (isLoading.value) {
    return;
  }
  if (!reset && !hasMore.value) {
    return;
  }
  isLoading.value = true;
  if (reset) {
    errorText.value = "";
  }
  try {
    const page = await fetchConnections(props.userId, {
      cursor: reset ? null : nextCursor.value,
      search: trimmedSearch,
      fromProfile: fromProfileFilter.value,
      afterDate: afterDateFilter.value,
      beforeDate: beforeDateFilter.value,
      pageSize: 20,
      scope: props.mode,
    });
    items.value = reset ? page.items : [...items.value, ...page.items];
    nextCursor.value = page.next_cursor;
    hasMore.value = page.has_more;
  } catch {
    errorText.value = "Unable to load connections.";
    errorModalStore.showError("Unable to load connections.");
  } finally {
    isLoading.value = false;
  }
}

async function loadPendingConnections() {
  if (props.mode !== "connections" || props.userId !== null) {
    pendingItems.value = [];
    return;
  }
  try {
    const response = await fetchPendingConnections();
    pendingItems.value = response.items || [];
  } catch {
    pendingItems.value = [];
  }
}

function scheduleFilterReload() {
  if (filterTimer) {
    clearTimeout(filterTimer);
  }
  filterTimer = setTimeout(() => {
    items.value = [];
    nextCursor.value = null;
    hasMore.value = true;
    void loadConnections(true);
  }, 360);
}

function clearFilters() {
  searchText.value = "";
  fromProfileFilter.value = "";
  fromProfileDraft.value = "";
  fromProfileSuggestions.value = [];
  showFromProfileSuggestionBox.value = false;
  afterDateFilter.value = "";
  beforeDateFilter.value = "";
}

function closeFilterModal() {
  isFilterMenuOpen.value = false;
}

function selectFromProfileSuggestion(suggestion: DMUserSuggestion) {
  fromProfileDraft.value = suggestion.username;
  fromProfileFilter.value = suggestion.username;
  fromProfileSuggestions.value = [];
  showFromProfileSuggestionBox.value = false;
}

function scheduleFromProfileSuggestionFetch() {
  if (fromProfileSuggestionTimer) {
    clearTimeout(fromProfileSuggestionTimer);
    fromProfileSuggestionTimer = null;
  }
  fromProfileSuggestionTimer = setTimeout(async () => {
    const query = fromProfileDraft.value.trim();
    if (query.length < 3) {
      showFromProfileSuggestionBox.value = false;
      fromProfileSuggestions.value = [];
      return;
    }
    showFromProfileSuggestionBox.value = isFromProfileInputFocused.value;
    isLoadingFromProfileSuggestions.value = true;
    try {
      fromProfileSuggestions.value = await fetchDMUserSuggestions(query, 50);
      showFromProfileSuggestionBox.value = isFromProfileInputFocused.value && fromProfileSuggestions.value.length > 0;
    } catch {
      fromProfileSuggestions.value = [];
      showFromProfileSuggestionBox.value = false;
    } finally {
      isLoadingFromProfileSuggestions.value = false;
    }
  }, 220);
}

function onFromProfileInputFocus() {
  isFromProfileInputFocused.value = true;
  if (fromProfileDraft.value.trim().length >= 3) {
    showFromProfileSuggestionBox.value = true;
  }
}

function onDocumentPointerDown(event: MouseEvent) {
  const targetNode = event.target as Node | null;
  if (!targetNode) {
    return;
  }
  if (fromProfileWrapRef.value && !fromProfileWrapRef.value.contains(targetNode)) {
    isFromProfileInputFocused.value = false;
    showFromProfileSuggestionBox.value = false;
  }
}

function openProfile(userId: number) {
  void router.push({ name: "user-profile", params: { userId } });
}

function toggleMenu(userId: number) {
  activeMenuUserId.value = activeMenuUserId.value === userId ? null : userId;
}

async function copyProfileLink(userId: number) {
  const profilePath = router.resolve({ name: "user-profile", params: { userId } }).href;
  const profileUrl = new URL(profilePath, window.location.origin).toString();
  try {
    await navigator.clipboard.writeText(profileUrl);
  } catch {
    copyLinkFallbackValue.value = profileUrl;
    showCopyLinkModal.value = true;
  }
  activeMenuUserId.value = null;
}

async function disconnectUser(userId: number) {
  try {
    await disconnectFromUser(userId);
    if (props.mode === "connections") {
      items.value = items.value.filter((item) => item.user_id !== userId);
    } else {
      items.value = items.value.map((item) =>
        item.user_id === userId ? { ...item, is_connected: false } : item,
      );
    }
  } catch {
    // Keep list usable even when connect fails.
  } finally {
    activeMenuUserId.value = null;
  }
}

async function connectUser(userId: number) {
  try {
    await connectToUser(userId);
    items.value = items.value.map((item) => (item.user_id === userId ? { ...item, is_connected: true } : item));
  } catch {
    // Keep list usable even when connect fails.
  } finally {
    activeMenuUserId.value = null;
  }
}

async function approvePendingUser(userId: number) {
  try {
    await approveConnection(userId);
    pendingItems.value = pendingItems.value.filter((item) => item.user_id !== userId);
    void loadConnections(true);
  } catch {
    // Keep list usable even when approval fails.
  }
}

async function denyPendingUser(userId: number) {
  try {
    await denyConnection(userId);
    pendingItems.value = pendingItems.value.filter((item) => item.user_id !== userId);
  } catch {
    // Keep list usable even when deny fails.
  }
}

function closeCopyLinkModal() {
  showCopyLinkModal.value = false;
  copyLinkFallbackValue.value = "";
}

onMounted(() => {
  document.addEventListener("mousedown", onDocumentPointerDown);
  observer = new IntersectionObserver(
    (entries) => {
      if (entries[0]?.isIntersecting) {
        void loadConnections(false);
      }
    },
    { threshold: 0.4 },
  );
  if (loadMoreAnchor.value) {
    observer.observe(loadMoreAnchor.value);
  }
  if (props.mode === "connections") {
    void loadConnections(true);
    void loadPendingConnections();
  }
});

onUnmounted(() => {
  document.removeEventListener("mousedown", onDocumentPointerDown);
  if (observer) {
    observer.disconnect();
  }
  if (filterTimer) {
    clearTimeout(filterTimer);
    filterTimer = null;
  }
  if (fromProfileSuggestionTimer) {
    clearTimeout(fromProfileSuggestionTimer);
    fromProfileSuggestionTimer = null;
  }
  document.body.style.overflow = "";
});

watch(
  () => props.userId,
  () => {
    items.value = [];
    nextCursor.value = null;
    hasMore.value = true;
    void loadConnections(true);
    void loadPendingConnections();
  },
);

watch([searchText, fromProfileFilter, afterDateFilter, beforeDateFilter], () => {
  scheduleFilterReload();
});

watch(fromProfileDraft, () => {
  fromProfileFilter.value = fromProfileDraft.value.trim();
  scheduleFromProfileSuggestionFetch();
});

watch(isFilterMenuOpen, (isOpen) => {
  if (isOpen) {
    fromProfileDraft.value = fromProfileFilter.value;
  } else {
    isFromProfileInputFocused.value = false;
    showFromProfileSuggestionBox.value = false;
  }
  document.body.style.overflow = isOpen ? "hidden" : "";
});
</script>

<script lang="ts">
export default {
  name: "ConnectionsListCard",
};
</script>

<template>
  <section class="feed-item connections-card">
    <header v-if="title" class="connections-header">
      <h2>{{ title }}</h2>
    </header>
    <div class="connections-search-wrap">
      <div class="search-input-row">
        <svg viewBox="0 0 24 24" class="icon"><circle cx="11" cy="11" r="6.5" fill="none" stroke="currentColor" stroke-width="1.8"/><path d="m16 16 4 4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        <input v-model="searchText" type="text" placeholder="Search" />
        <button type="button" class="icon-only-button small-round-button" @click="isFilterMenuOpen = true">
          <svg viewBox="0 0 24 24" class="icon"><path d="M6 8h12M8 12h8M10 16h4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        </button>
      </div>
      <p v-if="props.mode === 'users' && searchText.trim().length < minSearchChars" class="suggestion-meta">
        Type at least {{ minSearchChars }} characters to search.
      </p>
    </div>

    <section v-if="props.mode === 'connections' && props.userId === null && pendingItems.length" class="stack">
      <h3>Pending Approvals</h3>
      <article v-for="pending in pendingItems" :key="`pending-${pending.connection_id}`" class="feed-item connection-row">
        <button type="button" class="author-link feed-avatar-button" @click="openProfile(pending.user_id)">
          <img
            :src="pending.profile_image_url || placeholderAvatar(pending.display_name)"
            alt="Profile"
            class="feed-avatar"
          />
        </button>
        <div class="connection-main">
          <button type="button" class="author-link" @click="openProfile(pending.user_id)">
            {{ pending.display_name }}
          </button>
          <p class="suggestion-meta">@{{ pending.username }}</p>
        </div>
        <div class="post-actions">
          <button type="button" class="icon-action-button" @click="approvePendingUser(pending.user_id)">Approve</button>
          <button type="button" class="icon-action-button" @click="denyPendingUser(pending.user_id)">Deny</button>
        </div>
      </article>
    </section>

    <article v-for="connection in items" :key="connection.connection_id" class="connection-row">
      <button type="button" class="author-link feed-avatar-button" @click="openProfile(connection.user_id)">
        <img
          :src="connection.profile_image_url || placeholderAvatar(connection.display_name)"
          alt="Profile"
          class="feed-avatar"
        />
      </button>
      <div class="connection-main">
        <button type="button" class="author-link" @click="openProfile(connection.user_id)">
          {{ connection.display_name }}
        </button>
        <p class="suggestion-meta">Shared interests: {{ connection.shared_interest_count }}</p>
      </div>
      <button
        v-if="props.mode === 'connections'"
        type="button"
        class="icon-action-button"
        @click="disconnectUser(connection.user_id)"
      >
        Remove
      </button>
      <div class="post-menu-wrap">
        <button type="button" class="post-menu-trigger" @click="toggleMenu(connection.user_id)">
          <svg viewBox="0 0 24 24" class="icon"><circle cx="6" cy="12" r="1.8" fill="currentColor"/><circle cx="12" cy="12" r="1.8" fill="currentColor"/><circle cx="18" cy="12" r="1.8" fill="currentColor"/></svg>
        </button>
        <div v-if="activeMenuUserId === connection.user_id" class="post-menu">
          <button type="button" @click="copyProfileLink(connection.user_id)">Copy profile link</button>
          <button
            v-if="props.mode === 'users' && !connection.is_connected"
            type="button"
            @click="connectUser(connection.user_id)"
          >
            Connect
          </button>
          <button v-else type="button" @click="disconnectUser(connection.user_id)">Disconnect</button>
        </div>
      </div>
    </article>

    <div ref="loadMoreAnchor" class="feed-status">
      <p v-if="isLoading">Loading...</p>
      <p v-else-if="hasMore">Scroll to load more</p>
      <p v-else-if="items.length">End of list</p>
      <p v-else>No connections found.</p>
    </div>
    <div v-if="showCopyLinkModal" class="modal-overlay" @click.self="closeCopyLinkModal">
      <section class="auth-card modal-card">
        <h2>Copy profile link</h2>
        <input :value="copyLinkFallbackValue" readonly />
        <div class="modal-actions">
          <button type="button" @click="closeCopyLinkModal">Close</button>
        </div>
      </section>
    </div>
    <div v-if="isFilterMenuOpen" class="modal-overlay" @click.self="closeFilterModal">
      <section class="auth-card modal-card mention-host-card filter-modal-card">
        <h2>Filter {{ props.mode === "users" ? "search" : "connections" }}</h2>
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
              placeholder="username or name"
              autocomplete="off"
              @focus="onFromProfileInputFocus"
            />
            <div v-if="showFromProfileSuggestionBox" class="dm-suggestion-box">
              <p v-if="isLoadingFromProfileSuggestions" class="suggestion-meta">Loading...</p>
              <button
                v-for="suggestion in fromProfileSuggestions"
                :key="`connections-filter-${suggestion.user_id}`"
                type="button"
                class="dm-suggestion-item"
                @click="selectFromProfileSuggestion(suggestion)"
              >
                <span>@{{ suggestion.username }}</span>
                <span class="suggestion-meta">{{ suggestion.display_name }}</span>
              </button>
              <p v-if="!isLoadingFromProfileSuggestions && fromProfileSuggestions.length === 0" class="suggestion-meta">
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
  </section>
</template>
