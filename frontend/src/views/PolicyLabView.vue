<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";

import {
  createPolicyPack,
  listPolicyPacks,
  resolvePolicy,
  type PolicyPack,
  type PolicyResolveResponse,
} from "../api/policy";

const regionCode = ref("global");
const userKey = ref("sample-user");
const packs = ref<PolicyPack[]>([]);
const resolved = ref<PolicyResolveResponse | null>(null);
const statusText = ref("");

const form = reactive({
  version: "v-next",
  categories: "harassment,illegal_promotion",
  rollout_percentage: 100,
});

async function loadPacks() {
  packs.value = await listPolicyPacks(regionCode.value);
}

async function onCreatePack() {
  statusText.value = "";
  await createPolicyPack({
    region_code: regionCode.value,
    version: form.version,
    prohibited_categories: form.categories
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean),
    enabled: true,
    rollout_percentage: Number(form.rollout_percentage),
    effective_from: new Date().toISOString(),
    notes: "Created from Policy Lab",
  });
  statusText.value = "Policy pack created.";
  await loadPacks();
}

async function onResolve() {
  resolved.value = await resolvePolicy(regionCode.value, userKey.value);
}

onMounted(async () => {
  await loadPacks();
});
</script>

<template>
  <section class="auth-card">
    <h1>Policy Lab</h1>
    <div class="stack">
      <input v-model="regionCode" placeholder="Region code" />
      <input v-model="userKey" placeholder="User key for rollout" />
      <button @click="onResolve">Resolve policy</button>
      <p v-if="resolved">
        Active: {{ resolved.version }} ({{ resolved.source }}, {{ resolved.rollout_percentage }}%)
      </p>
    </div>

    <hr />

    <form class="stack" @submit.prevent="onCreatePack">
      <input v-model="form.version" placeholder="Version" required />
      <input v-model="form.categories" placeholder="Categories comma-separated" required />
      <input v-model.number="form.rollout_percentage" type="number" min="0" max="100" />
      <button type="submit">Create policy pack</button>
      <p v-if="statusText">{{ statusText }}</p>
    </form>

    <h2>Policy Packs</h2>
    <ul class="interest-list">
      <li v-for="pack in packs" :key="pack.id">
        {{ pack.region_code }} / {{ pack.version }} / rollout {{ pack.rollout_percentage }}%
      </li>
    </ul>
  </section>
</template>
