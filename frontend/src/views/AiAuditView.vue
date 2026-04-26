<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";

import { fetchAiAuditRecords, type AiAuditRecord } from "../api/ai-audit";

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
  } catch {
    statusText.value = "";
    errorText.value = "Unable to load audit records. Confirm account permissions.";
  }
}

onMounted(async () => {
  await loadAudits();
});
</script>

<template>
  <section class="auth-card">
    <h1>AI Audit Lab</h1>
    <form class="stack" @submit.prevent="loadAudits">
      <input v-model="filters.user_id" placeholder="User ID filter (staff only)" />
      <input v-model="filters.action_name" placeholder="Action name (e.g. post_create)" />
      <input v-model="filters.method" placeholder="Method (GET, POST, PATCH...)" />
      <input v-model="filters.status_code" placeholder="Status code (e.g. 201)" />
      <input v-model.number="filters.limit" type="number" min="1" max="500" />
      <button type="submit">Apply filters</button>
      <p v-if="statusText">{{ statusText }}</p>
      <p v-if="errorText">{{ errorText }}</p>
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
