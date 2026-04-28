<script setup lang="ts">
import { onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";

import { fetchProfile } from "../api/profile";
import { useErrorModalStore } from "../stores/error-modal";
import { useNotificationsStore } from "../stores/notifications";

const router = useRouter();
const route = useRoute();
const errorModalStore = useErrorModalStore();
const notificationsStore = useNotificationsStore();
const status = ref("checking");
const errorText = ref("");

async function checkStatus() {
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
  } catch {
    errorText.value = "Unable to check profile generation status.";
    errorModalStore.showError("Unable to check profile generation status.");
    status.value = "timeout";
  }
}

async function continueToFeed() {
  await router.replace(String(route.query.next || "/"));
}

onMounted(async () => {
  notificationsStore.ensureRealtimeConnection();
  await checkStatus();
});

watch(
  () => notificationsStore.profileGenerationStatus,
  (nextStatus) => {
    if (!nextStatus) {
      return;
    }
    status.value = nextStatus;
    if (nextStatus === "ready") {
      void router.replace(String(route.query.next || "/"));
    }
    if (nextStatus === "failed") {
      status.value = "failed";
    }
  },
);
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
