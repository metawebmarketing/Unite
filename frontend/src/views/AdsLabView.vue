<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";

import {
  createAdConfig,
  fetchAdMetrics,
  listAdConfigs,
  updateAdConfig,
  type AdMetrics,
  type AdSlotConfig,
} from "../api/ads";

const router = useRouter();
const regionCode = ref("global");
const campaignFilter = ref("");
const configs = ref<AdSlotConfig[]>([]);
const metrics = ref<AdMetrics | null>(null);
const statusText = ref("");

const form = reactive({
  region_code: "global",
  campaign_key: "",
  experiment_key: "",
  interval: 3,
  enabled: true,
  account_tier_target: "any" as "any" | "human" | "ai",
  target_interest_tags: "",
});

function goBack() {
  void router.push({ name: "feed" });
}

async function loadConfigs() {
  try {
    configs.value = await listAdConfigs(regionCode.value);
    statusText.value = "";
  } catch (error: unknown) {
    const status = Number((error as { response?: { status?: number } })?.response?.status || 0);
    if (status === 429) {
      statusText.value = "Rate limited while loading ad configs. Please retry shortly.";
    } else {
      statusText.value = "Unable to load ad configs.";
    }
    configs.value = [];
  }
}

async function loadMetrics() {
  try {
    metrics.value = await fetchAdMetrics(regionCode.value, campaignFilter.value);
  } catch (error: unknown) {
    const status = Number((error as { response?: { status?: number } })?.response?.status || 0);
    if (status === 429) {
      statusText.value = "Rate limited while loading ad metrics. Please retry shortly.";
    } else {
      statusText.value = "Unable to load ad metrics.";
    }
    metrics.value = null;
  }
}

async function onCreateConfig() {
  statusText.value = "";
  try {
    await createAdConfig({
      region_code: form.region_code.trim().toLowerCase(),
      campaign_key: form.campaign_key.trim().toLowerCase() || undefined,
      experiment_key: form.experiment_key.trim().toLowerCase() || undefined,
      interval: Number(form.interval),
      enabled: Boolean(form.enabled),
      account_tier_target: form.account_tier_target,
      target_interest_tags: form.target_interest_tags
        .split(",")
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean),
    });
    statusText.value = "Ad config created.";
    await loadConfigs();
  } catch (error: unknown) {
    const status = Number((error as { response?: { status?: number } })?.response?.status || 0);
    if (status === 429) {
      statusText.value = "Rate limited while creating ad config. Please wait and retry.";
    } else {
      statusText.value = "Unable to create ad config.";
    }
  }
}

async function onToggleEnabled(config: AdSlotConfig) {
  try {
    await updateAdConfig(config.id, { enabled: !config.enabled });
    await loadConfigs();
  } catch (error: unknown) {
    const status = Number((error as { response?: { status?: number } })?.response?.status || 0);
    if (status === 429) {
      statusText.value = "Rate limited while updating ad config. Please retry shortly.";
    } else {
      statusText.value = "Unable to update ad config.";
    }
  }
}

onMounted(async () => {
  await loadConfigs();
  await loadMetrics();
});
</script>

<template>
  <section class="auth-card">
    <button class="back-button icon-only-button" type="button" @click="goBack" title="Back" aria-label="Back">
      <svg viewBox="0 0 24 24" class="icon"><path d="M15 5 8 12l7 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
    </button>
    <h1>Ads Lab</h1>
    <div class="stack">
      <input v-model="regionCode" placeholder="Region code" />
      <input v-model="campaignFilter" placeholder="Campaign filter (optional)" />
      <button @click="loadConfigs">Refresh configs</button>
      <button @click="loadMetrics">Refresh metrics</button>
      <p v-if="metrics">
        Impressions: {{ metrics.impressions }} / Clicks: {{ metrics.clicks }} / CTR:
        {{ metrics.ctr }}
      </p>
      <p v-if="metrics && Object.keys(metrics.by_campaign).length">
        Campaigns:
        {{
          Object.entries(metrics.by_campaign)
            .map(([key, value]) => `${key} (${value.impressions} imp / ${value.clicks} clk)`)
            .join(", ")
        }}
      </p>
    </div>

    <hr />

    <form class="stack" @submit.prevent="onCreateConfig">
      <input v-model="form.region_code" placeholder="Region code (e.g. global, us)" required />
      <input v-model="form.campaign_key" placeholder="Campaign key (optional)" />
      <input v-model="form.experiment_key" placeholder="Experiment key (optional)" />
      <input v-model.number="form.interval" type="number" min="0" placeholder="Interval" />
      <select v-model="form.account_tier_target">
        <option value="any">Any account tier</option>
        <option value="human">Human only</option>
        <option value="ai">AI only</option>
      </select>
      <input
        v-model="form.target_interest_tags"
        placeholder="Target interest tags (comma-separated, optional)"
      />
      <label>
        <input v-model="form.enabled" type="checkbox" />
        Enabled
      </label>
      <button type="submit">Create ad config</button>
      <p v-if="statusText">{{ statusText }}</p>
    </form>

    <h2>Ad Configs</h2>
    <ul class="interest-list">
      <li v-for="config in configs" :key="config.id">
        {{ config.region_code }} / {{ config.campaign_key || "no-campaign" }} / every
        {{ config.interval }} / {{ config.account_tier_target }} /
        {{ config.enabled ? "enabled" : "disabled" }}
        <button @click="onToggleEnabled(config)">
          {{ config.enabled ? "Disable" : "Enable" }}
        </button>
      </li>
    </ul>
  </section>
</template>
