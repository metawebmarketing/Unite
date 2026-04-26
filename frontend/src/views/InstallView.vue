<script setup lang="ts">
import { computed, onUnmounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";

import { fetchInstallStatus, runInstall, type InstallStatus } from "../api/install";
import { useAuthStore } from "../stores/auth";

const router = useRouter();
const authStore = useAuthStore();
const errorText = ref("");
const statusText = ref("");
const isBusy = ref(false);
const installStatus = ref<InstallStatus | null>(null);
const showSeedProgressModal = ref(false);
let pollTimer: ReturnType<typeof setInterval> | null = null;
const form = reactive({
  username: "",
  email: "",
  password: "",
  display_name: "",
  location: "",
  seed_demo_data: false,
});

const userProgressPercent = computed(() => {
  const total = installStatus.value?.seed_total_users || 0;
  const created = installStatus.value?.seed_created_users || 0;
  if (!total) {
    return 0;
  }
  return Math.min(100, Math.round((created / total) * 100));
});

const recordProgressPercent = computed(() => {
  const total = (installStatus.value?.seed_total_users || 0) + (installStatus.value?.seed_total_posts || 0);
  const created = (installStatus.value?.seed_created_users || 0) + (installStatus.value?.seed_created_posts || 0);
  if (!total) {
    return 0;
  }
  return Math.min(100, Math.round((created / total) * 100));
});

const createdRecordCount = computed(
  () => (installStatus.value?.seed_created_users || 0) + (installStatus.value?.seed_created_posts || 0),
);
const totalRecordCount = computed(
  () => (installStatus.value?.seed_total_users || 0) + (installStatus.value?.seed_total_posts || 0),
);

function startPolling() {
  if (pollTimer) {
    return;
  }
  pollTimer = setInterval(async () => {
    try {
      const status = await fetchInstallStatus();
      installStatus.value = status;
      if (!["queued", "running"].includes(status.seed_status)) {
        stopPolling();
        setTimeout(() => {
          showSeedProgressModal.value = false;
          void router.push("/");
        }, 500);
      }
    } catch {
      stopPolling();
    }
  }, 1200);
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function onSubmit() {
  errorText.value = "";
  statusText.value = "Installing...";
  isBusy.value = true;
  try {
    const result = await runInstall(form);
    authStore.setAuthPayload(result.auth);
    await authStore.refreshUserMeta();
    authStore.persist();
    sessionStorage.setItem("unite_install_known", "true");
    installStatus.value = await fetchInstallStatus();
    statusText.value = result.seed_requested ? "Install complete. Seeding demo data..." : "Install complete.";
    if (result.seed_requested) {
      showSeedProgressModal.value = true;
      startPolling();
    } else {
      await router.push("/");
    }
  } catch (error: unknown) {
    statusText.value = "";
    errorText.value = "Install failed. Verify values and try again.";
    if (typeof error === "object" && error && "response" in error) {
      const response = (error as { response?: { data?: { detail?: string } } }).response;
      if (response?.data?.detail) {
        errorText.value = response.data.detail;
      }
    }
  } finally {
    isBusy.value = false;
  }
}

onUnmounted(() => {
  stopPolling();
});
</script>

<template>
  <div class="modal-overlay">
    <section class="auth-card modal-card">
      <h1>Unite Setup</h1>
      <p>Create the master admin account to finish first-time installation.</p>
      <form class="stack" @submit.prevent="onSubmit">
        <input v-model="form.username" placeholder="Master admin username" required />
        <input v-model="form.email" type="email" placeholder="Master admin email" required />
        <input v-model="form.password" type="password" placeholder="Master admin password" required />
        <input v-model="form.display_name" placeholder="Display name (optional)" />
        <input v-model="form.location" placeholder="Default location (optional)" />
        <label>
          <input v-model="form.seed_demo_data" type="checkbox" />
          Create demo data (1000 users with 10 posts each)
        </label>
        <button type="submit">Install Unite</button>
        <p v-if="statusText">{{ statusText }}</p>
        <div
          v-if="installStatus && ['queued', 'running', 'completed', 'failed'].includes(installStatus.seed_status) && !showSeedProgressModal"
          class="stack"
        >
          <p>Seed status: {{ installStatus.seed_status }}</p>
          <div class="progress-track">
            <div class="progress-fill" :style="{ width: `${userProgressPercent}%` }" />
          </div>
          <p>
            Accounts: {{ installStatus.seed_created_users }} / {{ installStatus.seed_total_users }} · Posts:
            {{ installStatus.seed_created_posts }} / {{ installStatus.seed_total_posts }}
          </p>
          <p v-if="installStatus.seed_last_message">{{ installStatus.seed_last_message }}</p>
        </div>
        <p v-if="errorText">{{ errorText }}</p>
      </form>
      <div v-if="isBusy" class="loading-overlay">
        <div class="spinner" />
      </div>
    </section>

    <div v-if="showSeedProgressModal && installStatus" class="modal-overlay cropper-overlay">
      <section class="auth-card modal-card">
        <h2>Generating demo data</h2>
        <p>Seed status: {{ installStatus.seed_status }}</p>
        <div class="progress-track">
          <div class="progress-fill" :style="{ width: `${recordProgressPercent}%` }" />
        </div>
        <p><strong>Record {{ createdRecordCount }} / {{ totalRecordCount }}</strong></p>
        <p>
          Records: {{ createdRecordCount }} / {{ totalRecordCount }}
        </p>
        <p>
          Accounts: {{ installStatus.seed_created_users }} / {{ installStatus.seed_total_users }} · Posts:
          {{ installStatus.seed_created_posts }} / {{ installStatus.seed_total_posts }}
        </p>
        <p v-if="installStatus.seed_last_message">{{ installStatus.seed_last_message }}</p>
        <div class="spinner" />
      </section>
    </div>
  </div>
</template>
