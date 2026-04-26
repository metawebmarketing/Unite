<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { fetchProfile } from "../api/profile";

const router = useRouter();
const route = useRoute();
const status = ref("checking");
const errorText = ref("");
const attempts = ref(0);
const maxAttempts = 12;
let pollTimer: ReturnType<typeof setInterval> | null = null;

async function checkStatus() {
  attempts.value += 1;
  try {
    const profile = await fetchProfile();
    const profileStatus = profile.algorithm_profile_status;
    if (profileStatus === "ready") {
      await router.replace(String(route.query.next || "/"));
      return;
    }
    if (profileStatus === "failed") {
      status.value = "failed";
      return;
    }
    status.value = profileStatus || "processing";
    if (attempts.value >= maxAttempts) {
      status.value = "timeout";
      stopPolling();
    }
  } catch {
    errorText.value = "Unable to check profile generation status.";
    status.value = "timeout";
    stopPolling();
  }
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function continueToFeed() {
  await router.replace(String(route.query.next || "/"));
}

onMounted(async () => {
  await checkStatus();
  pollTimer = setInterval(async () => {
    await checkStatus();
  }, 2500);
});

onUnmounted(() => {
  stopPolling();
});
</script>

<template>
  <section class="auth-card">
    <h1>Preparing your feed</h1>
    <p v-if="status === 'processing' || status === 'not_started'">
      Building your recommendation profile...
    </p>
    <p v-else-if="status === 'failed'">
      Profile generation failed. You can continue with fallback feed ranking.
    </p>
    <p v-else-if="status === 'timeout'">
      Profile generation is taking longer than expected. You can continue now.
    </p>
    <p v-if="errorText">{{ errorText }}</p>
    <div v-if="status === 'processing' || status === 'not_started' || status === 'checking'" class="progress-track">
      <div class="progress-fill progress-indeterminate" />
    </div>
    <div v-if="status === 'processing' || status === 'not_started' || status === 'checking'" class="loading-overlay">
      <div class="spinner" />
    </div>
    <button v-if="status === 'failed' || status === 'timeout'" @click="continueToFeed">
      Continue to feed
    </button>
  </section>
</template>
