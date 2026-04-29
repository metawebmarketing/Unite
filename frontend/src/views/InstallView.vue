<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { useRouter } from "vue-router";

import { fetchInstallStatus, runInstall, type InstallStatus } from "../api/install";
import { useAuthStore } from "../stores/auth";
import { useErrorModalStore } from "../stores/error-modal";
import { useNotificationsStore } from "../stores/notifications";

const router = useRouter();
const authStore = useAuthStore();
const notificationsStore = useNotificationsStore();
const errorModalStore = useErrorModalStore();
const errorText = ref("");
const statusText = ref("");
const isBusy = ref(false);
const installStatus = ref<InstallStatus | null>(null);
const showSeedProgressModal = ref(false);
const form = reactive({
  username: "",
  email: "",
  password: "",
  display_name: "",
  location: "",
  seed_demo_data: false,
  seed_total_users: 1000,
  seed_posts_per_user: 10,
});

function resolveSeedTotalPosts(): number {
  const users = Math.max(1, Math.trunc(Number(form.seed_total_users) || 0));
  const postsPerUser = Math.max(1, Math.trunc(Number(form.seed_posts_per_user) || 0));
  return Math.max(1, Math.min(200000, users * postsPerUser));
}

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

async function onSubmit() {
  errorText.value = "";
  statusText.value = "Installing...";
  isBusy.value = true;
  try {
    const result = await runInstall({
      username: form.username,
      email: form.email,
      password: form.password,
      display_name: form.display_name,
      location: form.location,
      seed_demo_data: form.seed_demo_data,
      seed_total_users: Math.max(1, Math.trunc(Number(form.seed_total_users) || 1)),
      seed_total_posts: resolveSeedTotalPosts(),
    });
    authStore.setAuthPayload(result.auth);
    await authStore.refreshUserMeta();
    authStore.persist();
    sessionStorage.setItem("unite_install_known", "true");
    installStatus.value = await fetchInstallStatus();
    statusText.value = result.seed_requested ? "Install complete. Seeding demo data..." : "Install complete.";
    if (result.seed_requested) {
      showSeedProgressModal.value = true;
      notificationsStore.ensureRealtimeConnection();
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
    errorModalStore.showError(errorText.value || "Install failed. Verify values and try again.");
  } finally {
    isBusy.value = false;
  }
}

watch(
  () => authStore.isAuthenticated,
  (isAuthenticated) => {
    if (isAuthenticated) {
      notificationsStore.ensureRealtimeConnection();
    }
  },
  { immediate: true },
);

watch(
  () => notificationsStore.installStatusRealtime,
  (status) => {
    if (!status) {
      return;
    }
    installStatus.value = status;
    if (showSeedProgressModal.value && !["queued", "running"].includes(status.seed_status)) {
      setTimeout(() => {
        showSeedProgressModal.value = false;
        void router.push("/");
      }, 500);
    }
  },
  { deep: true },
);
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
          Create demo data
        </label>
        <div v-if="form.seed_demo_data" class="stack">
          <input
            v-model.number="form.seed_total_users"
            type="number"
            min="1"
            max="10000"
            step="1"
            placeholder="Total demo users"
            required
          />
          <input
            v-model.number="form.seed_posts_per_user"
            type="number"
            min="1"
            max="5000"
            step="1"
            placeholder="Conversations per demo user"
            required
          />
          <p>Estimated total conversations: {{ resolveSeedTotalPosts() }}</p>
        </div>
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
            Accounts: {{ installStatus.seed_created_users }} / {{ installStatus.seed_total_users }} · Conversations:
            {{ installStatus.seed_created_posts }} / {{ installStatus.seed_total_posts }}
          </p>
          <p v-if="installStatus.seed_last_message">{{ installStatus.seed_last_message }}</p>
        </div>
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
          Accounts: {{ installStatus.seed_created_users }} / {{ installStatus.seed_total_users }} · Conversations:
          {{ installStatus.seed_created_posts }} / {{ installStatus.seed_total_posts }}
        </p>
        <p v-if="installStatus.seed_last_message">{{ installStatus.seed_last_message }}</p>
        <div class="spinner" />
      </section>
    </div>
  </div>
</template>
