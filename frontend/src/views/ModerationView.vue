<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";

import { decideModerationFlag, listModerationFlags, type ModerationFlagRecord } from "../api/moderation";
import { useErrorModalStore } from "../stores/error-modal";
import { navigateBack } from "../utils/navigation";

const router = useRouter();
const errorModalStore = useErrorModalStore();
const isLoadingFlags = ref(false);
const flags = ref<ModerationFlagRecord[]>([]);
const flagStatusFilter = ref("pending");
const flagSearchQuery = ref("");
const decisionNote = ref("");
const statusText = ref("");

function goBack() {
  void navigateBack(router, { name: "feed" });
}

function openAccountsPage() {
  void router.push({ name: "moderation-accounts" });
}

async function loadFlags() {
  isLoadingFlags.value = true;
  try {
    flags.value = await listModerationFlags({
      status: flagStatusFilter.value || undefined,
      query: flagSearchQuery.value || undefined,
      limit: 200,
    });
  } catch {
    errorModalStore.showError("Unable to load moderation queue.");
  } finally {
    isLoadingFlags.value = false;
  }
}

async function applyDecision(
  flag: ModerationFlagRecord,
  payload: { decision: "approved" | "denied"; applyPenalty: boolean; reportOutcome: "valid_report" | "false_report" },
) {
  try {
    await decideModerationFlag(flag.id, {
      decision: payload.decision,
      apply_penalty: payload.applyPenalty,
      report_outcome: payload.reportOutcome,
      review_note: decisionNote.value.trim(),
    });
    statusText.value = `Flag #${flag.id} updated.`;
    await loadFlags();
  } catch {
    errorModalStore.showError("Unable to update moderation decision.");
  }
}

onMounted(async () => {
  await loadFlags();
});
</script>

<template>
  <section class="auth-card">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 16 16" class="icon"><path d="M5 1H4L0 5L4 9H5V6H11C12.6569 6 14 7.34315 14 9C14 10.6569 12.6569 12 11 12H4V14H11C13.7614 14 16 11.7614 16 9C16 6.23858 13.7614 4 11 4H5V1Z" fill="currentColor"/></svg>
    </button>
    <h1>Moderation Queue</h1>
    <p v-if="statusText">{{ statusText }}</p>
    <div class="stack">
      <button type="button" @click="openAccountsPage">Open Moderated Accounts</button>
    </div>
    <div class="stack">
      <h3>Flagged Items</h3>
      <div class="stack">
        <select v-model="flagStatusFilter" @change="loadFlags">
          <option value="">All statuses</option>
          <option value="pending">Pending</option>
          <option value="approved">Approved</option>
          <option value="denied">Denied</option>
        </select>
        <input v-model="flagSearchQuery" placeholder="Search reason, category, type" />
        <input v-model="decisionNote" placeholder="Decision note (optional)" />
      </div>
      <ul class="interest-list">
        <li v-for="flag in flags" :key="flag.id" class="stack">
          <strong>#{{ flag.id }} · {{ flag.category }} · {{ flag.status }}</strong>
          <span>Target: {{ flag.target_user_id || "n/a" }} · Reporter: {{ flag.reporter_user_id || "n/a" }}</span>
          <span>{{ flag.reason }}</span>
          <div class="stack">
            <button type="button" @click="applyDecision(flag, { decision: 'approved', applyPenalty: true, reportOutcome: 'valid_report' })">Approve + Penalty</button>
            <button type="button" @click="applyDecision(flag, { decision: 'approved', applyPenalty: false, reportOutcome: 'valid_report' })">Approve (Bypass Penalty)</button>
            <button
              v-if="flag.category === 'user_report'"
              type="button"
              @click="applyDecision(flag, { decision: 'approved', applyPenalty: true, reportOutcome: 'false_report' })"
            >
              Mark False Report + Penalty Reporter
            </button>
            <button type="button" @click="applyDecision(flag, { decision: 'denied', applyPenalty: false, reportOutcome: 'valid_report' })">Deny</button>
          </div>
        </li>
      </ul>
    </div>
  </section>
</template>
