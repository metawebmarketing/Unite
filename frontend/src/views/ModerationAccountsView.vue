<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { useRouter } from "vue-router";

import {
  banModerationAccount,
  clearModerationPenalties,
  listModerationPenalties,
  removeModerationPenalty,
  searchModerationAccounts,
  unbanModerationAccount,
  type ModerationAccountRecord,
  type ModerationPenaltyRecord,
} from "../api/moderation";
import { useErrorModalStore } from "../stores/error-modal";
import { navigateBack } from "../utils/navigation";

const router = useRouter();
const errorModalStore = useErrorModalStore();

const searchQuery = ref("");
const isLoading = ref(false);
const isPenaltiesLoading = ref(false);
const accounts = ref<ModerationAccountRecord[]>([]);
const selectedAccount = ref<ModerationAccountRecord | null>(null);
const penalties = ref<ModerationPenaltyRecord[]>([]);

const page = ref(1);
const pageSize = ref(25);
const totalCount = ref(0);
const sortBy = ref<"user_id" | "username" | "email" | "active_penalty_count" | "is_banned" | "banned_at">(
  "active_penalty_count",
);
const sortDir = ref<"asc" | "desc">("desc");
const minSearchChars = 3;
let searchTimer: ReturnType<typeof setTimeout> | null = null;

const totalPages = computed(() => {
  if (totalCount.value <= 0) {
    return 1;
  }
  return Math.max(1, Math.ceil(totalCount.value / pageSize.value));
});

function goBack() {
  void navigateBack(router, { name: "moderation" });
}

async function loadAccounts() {
  isLoading.value = true;
  try {
    const response = await searchModerationAccounts({
      query: searchQuery.value.trim(),
      page: page.value,
      page_size: pageSize.value,
      sort_by: sortBy.value,
      sort_dir: sortDir.value,
    });
    accounts.value = response.results;
    totalCount.value = Number(response.count || 0);
  } catch {
    errorModalStore.showError("Unable to load moderated accounts.");
  } finally {
    isLoading.value = false;
  }
}

async function runSearch() {
  page.value = 1;
  if (searchQuery.value.trim().length > 0 && searchQuery.value.trim().length < minSearchChars) {
    accounts.value = [];
    totalCount.value = 0;
    return;
  }
  await loadAccounts();
}

async function changeSort(nextSortBy: "user_id" | "username" | "email" | "active_penalty_count" | "is_banned" | "banned_at") {
  if (sortBy.value === nextSortBy) {
    sortDir.value = sortDir.value === "asc" ? "desc" : "asc";
  } else {
    sortBy.value = nextSortBy;
    sortDir.value = "desc";
  }
  await loadAccounts();
}

async function setPage(nextPage: number) {
  if (nextPage < 1 || nextPage > totalPages.value) {
    return;
  }
  page.value = nextPage;
  await loadAccounts();
}

async function viewPenalties(account: ModerationAccountRecord) {
  selectedAccount.value = account;
  isPenaltiesLoading.value = true;
  try {
    penalties.value = await listModerationPenalties(account.user_id);
  } catch {
    errorModalStore.showError("Unable to load penalties.");
  } finally {
    isPenaltiesLoading.value = false;
  }
}

async function toggleBan(account: ModerationAccountRecord) {
  try {
    if (account.is_banned) {
      await unbanModerationAccount(account.user_id);
    } else {
      await banModerationAccount(account.user_id, "Banned by moderator");
    }
    await loadAccounts();
    if (selectedAccount.value?.user_id === account.user_id) {
      await viewPenalties(account);
    }
  } catch {
    errorModalStore.showError("Unable to update ban status.");
  }
}

async function removePenalty(penaltyId: number) {
  if (!selectedAccount.value) {
    return;
  }
  try {
    await removeModerationPenalty(penaltyId, "Removed by moderator");
    await viewPenalties(selectedAccount.value);
    await loadAccounts();
  } catch {
    errorModalStore.showError("Unable to remove penalty.");
  }
}

async function clearPenalties() {
  if (!selectedAccount.value) {
    return;
  }
  try {
    await clearModerationPenalties(selectedAccount.value.user_id, "Cleared by moderator");
    await viewPenalties(selectedAccount.value);
    await loadAccounts();
  } catch {
    errorModalStore.showError("Unable to clear penalties.");
  }
}

onMounted(async () => {
  await loadAccounts();
});

onUnmounted(() => {
  if (searchTimer) {
    clearTimeout(searchTimer);
    searchTimer = null;
  }
});

watch(searchQuery, () => {
  if (searchTimer) {
    clearTimeout(searchTimer);
  }
  searchTimer = setTimeout(() => {
    void runSearch();
  }, 360);
});
</script>

<template>
  <section class="moderation-accounts-page">
    <div class="moderation-header">
      <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
        <svg viewBox="0 0 16 16" class="icon"><path d="M5 1H4L0 5L4 9H5V6H11C12.6569 6 14 7.34315 14 9C14 10.6569 12.6569 12 11 12H4V14H11C13.7614 14 16 11.7614 16 9C16 6.23858 13.7614 4 11 4H5V1Z" fill="currentColor"/></svg>
      </button>
      <h1>Moderated Accounts</h1>
    </div>

    <div class="moderation-toolbar">
      <input
        v-model="searchQuery"
        type="text"
        placeholder="Search user id, username, or email (shows zero-penalty matches too)"
        @keyup.enter="runSearch"
      />
      <span v-if="searchQuery.trim().length > 0 && searchQuery.trim().length < minSearchChars" class="suggestion-meta">
        Type at least {{ minSearchChars }} characters to search.
      </span>
      <label>
        Page size
        <select v-model.number="pageSize" @change="runSearch">
          <option :value="10">10</option>
          <option :value="25">25</option>
          <option :value="50">50</option>
          <option :value="100">100</option>
        </select>
      </label>
    </div>

    <div class="table-wrap">
      <table class="spreadsheet-table">
        <thead>
          <tr>
            <th><button type="button" @click="changeSort('user_id')">User ID</button></th>
            <th><button type="button" @click="changeSort('username')">Username</button></th>
            <th><button type="button" @click="changeSort('email')">Email</button></th>
            <th><button type="button" @click="changeSort('active_penalty_count')">Active Penalties</button></th>
            <th><button type="button" @click="changeSort('is_banned')">Banned</button></th>
            <th><button type="button" @click="changeSort('banned_at')">Banned At</button></th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="account in accounts" :key="account.user_id">
            <td>{{ account.user_id }}</td>
            <td>{{ account.username }}</td>
            <td>{{ account.email }}</td>
            <td>{{ account.active_penalty_count }}</td>
            <td>{{ account.is_banned ? "Yes" : "No" }}</td>
            <td>{{ account.banned_at || "-" }}</td>
            <td class="actions-cell">
              <button type="button" @click="viewPenalties(account)">Penalties</button>
              <button type="button" @click="toggleBan(account)">{{ account.is_banned ? "Unban" : "Ban" }}</button>
            </td>
          </tr>
          <tr v-if="!accounts.length">
            <td colspan="7" class="empty-cell">No accounts found for current filters.</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="pagination-bar">
      <button type="button" :disabled="page <= 1 || isLoading" @click="setPage(page - 1)">Previous</button>
      <span>Page {{ page }} / {{ totalPages }} · {{ totalCount }} total</span>
      <button type="button" :disabled="page >= totalPages || isLoading" @click="setPage(page + 1)">Next</button>
    </div>

    <div v-if="selectedAccount" class="penalty-panel">
      <h3>Penalties: {{ selectedAccount.username }}</h3>
      <button type="button" @click="clearPenalties">Clear all active penalties</button>
      <div v-if="isPenaltiesLoading">Loading penalties...</div>
      <table v-else class="spreadsheet-table">
        <thead>
          <tr>
            <th>Penalty ID</th>
            <th>Reason</th>
            <th>Points</th>
            <th>Active</th>
            <th>Expires</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="penalty in penalties" :key="penalty.id">
            <td>{{ penalty.id }}</td>
            <td>{{ penalty.reason_type }}</td>
            <td>{{ penalty.points }}</td>
            <td>{{ penalty.active ? "Yes" : "No" }}</td>
            <td>{{ penalty.expires_at }}</td>
            <td>
              <button v-if="penalty.active" type="button" @click="removePenalty(penalty.id)">Remove</button>
            </td>
          </tr>
          <tr v-if="!penalties.length">
            <td colspan="6" class="empty-cell">No penalties found.</td>
          </tr>
        </tbody>
      </table>
    </div>
  </section>
</template>

<style scoped>
.moderation-accounts-page {
  width: 100%;
  max-width: none;
  padding: 1rem;
  display: grid;
  gap: 1rem;
}

.moderation-header,
.moderation-toolbar,
.pagination-bar {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  flex-wrap: wrap;
}

.table-wrap {
  overflow-x: auto;
}

.spreadsheet-table {
  width: 100%;
  border-collapse: collapse;
  table-layout: auto;
}

.spreadsheet-table th,
.spreadsheet-table td {
  border: 1px solid var(--color-border, #3a3a3a);
  padding: 0.5rem 0.6rem;
  text-align: left;
  white-space: nowrap;
}

.spreadsheet-table th button {
  width: 100%;
  text-align: left;
  background: transparent;
  border: 0;
  color: inherit;
  cursor: pointer;
  font: inherit;
  padding: 0;
}

.actions-cell {
  display: flex;
  gap: 0.35rem;
}

.empty-cell {
  text-align: center;
  color: var(--color-text-muted, #999);
}

.penalty-panel {
  display: grid;
  gap: 0.75rem;
}
</style>
