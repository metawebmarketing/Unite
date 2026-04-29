<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { fetchAiAuditRecords, type AiAuditRecord } from "../api/ai-audit";
import { useErrorModalStore } from "../stores/error-modal";

const router = useRouter();
const errorModalStore = useErrorModalStore();
const filters = reactive({
  user_id: "",
  action_name: "",
  method: "",
  status_code: "",
  limit: 100,
});
const records = ref<AiAuditRecord[]>([]);
const statusText = ref("");
const errorText = ref("");

function goBack() {
  void router.push({ name: "feed" });
}

async function loadAudits() {
  statusText.value = "Loading audit records...";
  errorText.value = "";
  try {
    records.value = await fetchAiAuditRecords({
      user_id: filters.user_id ? Number(filters.user_id) : undefined,
      action_name: filters.action_name || undefined,
      method: filters.method ? filters.method.toUpperCase() : undefined,
      status_code: filters.status_code ? Number(filters.status_code) : undefined,
      limit: Number(filters.limit) || 100,
    });
    statusText.value = `Loaded ${records.value.length} records.`;
  } catch (error: unknown) {
    const status = Number((error as { response?: { status?: number } })?.response?.status || 0);
    statusText.value = "";
    if (status === 429) {
      errorText.value = "Rate limited while loading audit records. Please wait and retry.";
      errorModalStore.showError("Rate limited while loading audit records. Please wait and retry.");
    } else {
      errorText.value = "Unable to load audit records. Confirm account permissions.";
      errorModalStore.showError("Unable to load audit records. Confirm account permissions.");
    }
  }
}

onMounted(async () => {
  await loadAudits();
});
</script>

<template>
  <section class="auth-card">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 16 16" class="icon"><path d="M5 1H4L0 5L4 9H5V6H11C12.6569 6 14 7.34315 14 9C14 10.6569 12.6569 12 11 12H4V14H11C13.7614 14 16 11.7614 16 9C16 6.23858 13.7614 4 11 4H5V1Z" fill="currentColor"/></svg>
    </button>
    <h1>AI Audit Lab</h1>
    <form class="stack" @submit.prevent="loadAudits">
      <input v-model="filters.user_id" placeholder="User ID filter (staff only)" />
      <input v-model="filters.action_name" placeholder="Action name (e.g. post_create)" />
      <input v-model="filters.method" placeholder="Method (GET, POST, PATCH...)" />
      <input v-model="filters.status_code" placeholder="Status code (e.g. 201)" />
      <input v-model.number="filters.limit" type="number" min="1" max="500" />
      <button type="submit">Apply filters</button>
      <p v-if="statusText">{{ statusText }}</p>
    </form>

    <h2>Records</h2>
    <ul class="interest-list">
      <li v-for="record in records" :key="record.id">
        #{{ record.id }} | user {{ record.user_id }} | {{ record.method }} {{ record.endpoint }} |
        {{ record.action_name }} | status {{ record.status_code ?? "n/a" }}
      </li>
    </ul>
  </section>
</template>
