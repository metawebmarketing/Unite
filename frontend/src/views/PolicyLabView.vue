<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";

import {
  createPolicyPack,
  listPolicyPacks,
  resolvePolicy,
  type PolicyPack,
  type PolicyResolveResponse,
} from "../api/policy";
import { useErrorModalStore } from "../stores/error-modal";

const router = useRouter();
const errorModalStore = useErrorModalStore();
const regionCode = ref("global");
const userKey = ref("sample-user");
const packs = ref<PolicyPack[]>([]);
const resolved = ref<PolicyResolveResponse | null>(null);
const statusText = ref("");
const errorText = ref("");

const form = reactive({
  version: "v-next",
  categories: "harassment,illegal_promotion",
  rollout_percentage: 100,
});

function goBack() {
  void router.push({ name: "feed" });
}

async function loadPacks() {
  try {
    packs.value = await listPolicyPacks(regionCode.value);
    errorText.value = "";
  } catch (error: unknown) {
    const status = Number((error as { response?: { status?: number } })?.response?.status || 0);
    if (status === 429) {
      errorText.value = "Rate limited while loading policy packs. Please wait a few seconds and retry.";
      errorModalStore.showError("Rate limited while loading policy packs. Please wait a few seconds and retry.");
    } else {
      errorText.value = "Unable to load policy packs right now.";
      errorModalStore.showError("Unable to load policy packs right now.");
    }
    packs.value = [];
  }
}

async function onCreatePack() {
  statusText.value = "";
  errorText.value = "";
  try {
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
  } catch (error: unknown) {
    const status = Number((error as { response?: { status?: number } })?.response?.status || 0);
    statusText.value = "";
    if (status === 429) {
      errorText.value = "Rate limited while creating policy pack. Please wait and try again.";
      errorModalStore.showError("Rate limited while creating policy pack. Please wait and try again.");
    } else {
      errorText.value = "Unable to create policy pack.";
      errorModalStore.showError("Unable to create policy pack.");
    }
  }
}

async function onResolve() {
  errorText.value = "";
  try {
    resolved.value = await resolvePolicy(regionCode.value, userKey.value);
  } catch (error: unknown) {
    const status = Number((error as { response?: { status?: number } })?.response?.status || 0);
    if (status === 429) {
      errorText.value = "Rate limited while resolving policy. Please retry shortly.";
      errorModalStore.showError("Rate limited while resolving policy. Please retry shortly.");
    } else {
      errorText.value = "Unable to resolve policy.";
      errorModalStore.showError("Unable to resolve policy.");
    }
    resolved.value = null;
  }
}

onMounted(async () => {
  await loadPacks();
});
</script>

<template>
  <section class="auth-card">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 24 24" class="icon"><path d="M15 5 8 12l7 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
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
