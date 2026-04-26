<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { connectToUser, disconnectFromUser, fetchConnections, type ConnectionListItem } from "../api/connections";

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
const afterDateFilter = ref("");
const beforeDateFilter = ref("");
const isFilterMenuOpen = ref(false);
let observer: IntersectionObserver | null = null;
let filterTimer: ReturnType<typeof setTimeout> | null = null;
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
  } finally {
    isLoading.value = false;
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
  afterDateFilter.value = "";
  beforeDateFilter.value = "";
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

function closeCopyLinkModal() {
  showCopyLinkModal.value = false;
  copyLinkFallbackValue.value = "";
}

onMounted(() => {
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
  }
});

onUnmounted(() => {
  if (observer) {
    observer.disconnect();
  }
  if (filterTimer) {
    clearTimeout(filterTimer);
    filterTimer = null;
  }
});

watch(
  () => props.userId,
  () => {
    items.value = [];
    nextCursor.value = null;
    hasMore.value = true;
    void loadConnections(true);
  },
);

watch([searchText, fromProfileFilter, afterDateFilter, beforeDateFilter], () => {
  scheduleFilterReload();
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
        <button type="button" class="icon-only-button small-round-button" @click="isFilterMenuOpen = !isFilterMenuOpen">
          <svg viewBox="0 0 24 24" class="icon"><path d="M6 8h12M8 12h8M10 16h4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>
        </button>
      </div>
      <p v-if="props.mode === 'users' && searchText.trim().length < minSearchChars" class="suggestion-meta">
        Type at least {{ minSearchChars }} characters to search.
      </p>
      <div v-if="isFilterMenuOpen" class="connections-filter-menu">
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
          <input v-model="fromProfileFilter" type="text" placeholder="username or name" />
        </label>
        <button v-if="hasAnyFilters" type="button" @click="clearFilters">Clear filters</button>
      </div>
    </div>

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
        <button type="button" class="author-username-link" @click="openProfile(connection.user_id)">
          @{{ connection.username }}
        </button>
        <p class="suggestion-meta">Shared interests: {{ connection.shared_interest_count }}</p>
      </div>
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
      <p v-if="errorText">{{ errorText }}</p>
    </div>
    <div v-if="showCopyLinkModal" class="modal-overlay">
      <section class="auth-card modal-card">
        <h2>Copy profile link</h2>
        <input :value="copyLinkFallbackValue" readonly />
        <div class="modal-actions">
          <button type="button" @click="closeCopyLinkModal">Close</button>
        </div>
      </section>
    </div>
  </section>
</template>
